"""The three fine-tuning workflow steps (registered in app/runtime/handlers.py):

  finetune_planner   requirement -> validated notebook selection          (model-assisted)
  finetune_executor  stage -> launch -> monitor -> collect -> MLflow       (deterministic)
  finetune_reporter  final answer for Chat                                 (model-assisted,
                                                                            deterministic fallback)

The executor never lets a model drive the hours-long job: it controls the job through the
DSLab MCP server and records structured progress on run.progress after every poll.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

from .. import filestore
from ..activity import cancel as cancel_reg
from ..runtime.handlers import StepContext, StepResult
from ..schemas import ActivityKind
from . import SHUTTING_DOWN, catalog, config, llm, mlflow_log, planner, remote, storage
from . import progress as P
from .notebook import inject

OUTPUT_PARAM_NAMES = ("output_dir", "OUTPUT_DIR", "output_path", "model_output_dir", "save_dir")
METRIC_FILES = ("metrics.json", "eval_results.json", "all_results.json", "train_results.json",
                "results.json", "test_results.json")
TERMINAL = ("completed", "failed", "cancelled", "timeout", "lost", "not_found")
_INLINE_STAGE_BYTES = 5 * 1024 * 1024        # datasets up to 5 MB are staged through MCP


async def _say(ctx: StepContext, label: str, kind=ActivityKind.phase, level="info", **kw):
    try:
        await ctx.emit(kind, label, level=level, node_id=ctx.node_id, agent=ctx.agent,
                       phase="finetune", **kw)
    except Exception:
        pass


def _fmt_bytes(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_dur(s) -> str:
    s = int(s or 0)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {sec:02d}s"


def _secs_since(iso: str | None) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return 0.0


def _job_duration(job: dict) -> float:
    try:
        end = datetime.fromisoformat(job["ended_at"]) if job.get("ended_at") else datetime.now(timezone.utc)
        return (end - datetime.fromisoformat(job["started_at"])).total_seconds()
    except Exception:
        return 0.0


def _fail(ctx: StepContext, stage: str, msg: str, output: str = "") -> StepResult:
    P.stage(ctx.run, stage, "failed", msg)
    P.set(ctx.run, error=msg[:2000], reattach=False)
    P.finish(ctx.run, "failed")
    ctx.save()
    return StepResult(status="failed", error=msg, output=output or f"**Fine-tuning stopped:** {msg}")


# =========================================================================== planner
async def planner_step(ctx: StepContext) -> StepResult:
    run = ctx.run
    P.ensure(run)
    P.stage(run, "plan", "active")
    ctx.save()
    req = planner.request_from_input(run.input)
    items = await asyncio.to_thread(catalog.list_notebooks)
    valid = [e for e in items if e["valid"]]
    folder = config.get()["notebooks_dir"]
    if not valid:
        return _fail(ctx, "plan", f"No fine-tuning notebooks found. Upload .ipynb files to File "
                                  f"Storage > {folder}/ and try again.")
    avail = ", ".join(e["name"] for e in valid)
    await _say(ctx, f"Analysing the request against {len(valid)} notebook(s) in {folder}/…")

    entry, raw, method, conf, reason = None, None, "", 0.0, ""
    tin = tout = 0
    if req["notebook"]:
        entry = await asyncio.to_thread(catalog.find, req["notebook"])
        if not entry:
            return _fail(ctx, "plan", f"Notebook '{req['notebook']}' is not in {folder}/. "
                                      f"Available: {avail}")
        method, conf, reason = "explicit", 1.0, "Notebook chosen explicitly in the request."

    system = ((ctx.card.get("prompts") or {}).get("system_prompt")
              or "You select the best fine-tuning notebook for a request.")
    try:
        text, tin, tout, note = await llm.complete(
            ctx.card, system, planner.build_prompt(req, [entry] if entry else valid),
            run.run_id, ctx.agent)
        if note:
            P.warn(run, note)
        raw = llm.parse_json(text)
        if raw is None:
            P.warn(run, "the model's reply was not valid JSON - used keyword matching instead")
    except llm.NoModel as e:
        P.warn(run, f"{e} - notebook selected by keyword matching")
    except Exception as e:
        P.warn(run, f"model call failed ({type(e).__name__}: {str(e)[:200]}) - notebook selected "
                    f"by keyword matching")

    if not entry and raw is not None:
        proposed = raw.get("notebook")
        if proposed:
            entry = await asyncio.to_thread(catalog.find, str(proposed))
            if entry:
                method = "llm"
                try:
                    conf = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
                except (TypeError, ValueError):
                    conf = 0.0
                reason = str(raw.get("reason") or "")
            else:
                P.warn(run, f"the model proposed `{proposed}`, which is not in the catalog - "
                            f"used keyword matching instead")
                raw = None
        else:
            why = str(raw.get("reason") or "no notebook matches the request").rstrip(". ")
            return _fail(ctx, "plan", f"No suitable notebook: {why}. Available: {avail}",
                         output=f"**No suitable fine-tuning notebook found.**\n\n{why}\n\n"
                                f"Available notebooks: {avail}.\nUpload a matching notebook to "
                                f"`{folder}/` or name one explicitly.")

    kw_entry, kw_conf, kw_alts = planner.keyword_pick(req["text"], valid)
    if not entry:
        if not kw_entry:
            return _fail(ctx, "plan", f"Could not match the request to any notebook. Describe the "
                                      f"task/model, or name a notebook. Available: {avail}")
        entry, conf, method = kw_entry, kw_conf, "keyword"
        reason = (f"Best keyword match among {len(valid)} notebook(s) for: "
                  f"\"{req['text'][:160]}\"")
    alts = [n for n in ([kw_entry["name"]] if kw_entry else []) + kw_alts if n != entry["name"]][:3]

    sel = planner.finalize(entry, method, req, raw, conf, reason, alts)
    for w in sel["warnings"]:
        P.warn(run, w)
    P.set(run, selection=sel, requirement=req["text"], runtime_request=req["runtime_id"])
    P.stage(run, "plan", "done", f"{sel['notebook']} ({method})")
    ctx.save()
    await _say(ctx, f"Selected {sel['notebook']} ({method}"
                    + (f", confidence {conf:.2f}" if method == "llm" else "") + f"): {reason[:200]}")

    rows = "\n".join(f"| `{k}` | `{json.dumps(v)}` |" for k, v in sel["parameters"].items()) \
        or "| _(notebook defaults)_ | |"
    md = (f"**Selected notebook:** `{sel['notebook']}` — {sel['title'] or ''}\n\n"
          f"**How:** {method}" + (f" (confidence {conf:.2f})" if method == "llm" else "") +
          f"\n\n**Why:** {reason}\n\n| Parameter | Value |\n|---|---|\n{rows}\n"
          + (f"\n**Dataset:** `{sel['dataset']['path']}` → `{sel['dataset_parameter'] or 'STUDIO_DATASET'}`\n"
             if sel["dataset"] else "")
          + (f"\n**Alternatives considered:** {', '.join(f'`{a}`' for a in alts)}\n" if alts else ""))
    return StepResult(output=md, in_tokens=tin, out_tokens=tout,
                      steps=[f"Selected {sel['notebook']} by {method}"])


# =========================================================================== executor
async def executor_step(ctx: StepContext) -> StepResult:
    run = ctx.run
    rid = run.run_id
    p = P.ensure(run)
    sel = p.get("selection")
    if not sel:
        return _fail(ctx, "stage", "No notebook was selected. Run this agent through the "
                                   "'Fine-Tuning (DSLab)' workflow so the planner runs first.")
    c = config.get()
    job = p.get("job") or {}
    resumed = bool(job.get("started_at"))
    try:
        rt = await asyncio.to_thread(remote.resolve_runtime,
                                     job.get("runtime_id") or p.get("runtime_request") or "")
        server = await asyncio.to_thread(remote.ensure_server, rt)
    except remote.RemoteError as e:
        return _fail(ctx, "stage", str(e))
    except Exception as e:
        return _fail(ctx, "stage", f"DSLab runtime unavailable: {type(e).__name__}: {e}")
    P.set(run, runtime={"id": rt["id"], "name": rt.get("name", rt["id"]),
                        "gpu_type": rt.get("gpu_type", ""), "host": rt.get("host", "")})
    ctx.save()

    try:
        if resumed:
            await _say(ctx, f"Re-attached to the running job on {rt.get('name')} (pid {job.get('pid')}).")
            P.warn(run, "the backend restarted during this run - re-attached to the running job")
        else:
            failed = await _stage_and_launch(ctx, rt, server, sel, c)
            if failed:
                return failed
        final, err = await _monitor(ctx, server, c)
    except asyncio.CancelledError:
        if SHUTTING_DOWN["value"]:
            # the job keeps running on the runtime; startup re-attaches (app/finetune/resume.py)
            P.set(run, note="backend stopping - the job keeps running and will be re-attached")
            ctx.save()
            raise
        # run timeout (executor) - stop the remote job too
        try:
            await asyncio.to_thread(remote.cancel, server, rid)
        except Exception:
            pass
        mid = (run.progress.get("mlflow") or {}).get("run_id")
        if mid:
            try:
                await asyncio.to_thread(mlflow_log.finalize, mid, "failed", {"success": 0},
                                        {"studio.status": "timeout"})
            except Exception:
                pass
        P.set(run, reattach=False, error="run time limit reached - the job was stopped")
        P.finish(run, "failed")
        ctx.save()
        raise

    # ---------------- collect + MLflow (also after failure/cancel: keep what exists)
    P.set(run, job={**(p.get("job") or {}), "ended_at": P.now(), "final_state": final})
    P.stage(run, "execute", "done" if final == "completed" else "failed",
            {"completed": "notebook executed", "cancelled": "stopped by user"}.get(final, err[:200]))
    await _say(ctx, f"Job {final}. Collecting outputs…", level="info" if final == "completed" else "warn")
    await _collect(ctx, rt, server, c)
    await _log_mlflow(ctx, final)

    summary = _summary_md(run)
    try:
        storage.write_text(rid, "summary.md", summary)
        storage.write_json(rid, "logs/progress.json", run.progress)
        run_arts = [storage.artifact(rid, "summary.md", "text/markdown", summary[:4000])]
        if (p.get("outputs") or {}).get("executed_notebook"):
            run_arts.append(storage.artifact(rid, "notebook/executed.ipynb", "application/x-ipynb+json"))
        if (p.get("outputs") or {}).get("log_copied"):
            run_arts.append(storage.artifact(rid, "logs/run.log", "text/plain"))
        if filestore.stat(f"{storage.run_dir(rid)}/model/MANIFEST.json"):
            run_arts.append(storage.artifact(rid, "model/MANIFEST.json", "application/json"))
    except Exception as e:
        run_arts = []
        P.warn(run, f"could not write the summary: {e}")
    P.set(run, reattach=False)

    if final == "completed":
        ctx.save()
        return StepResult(output=summary, artifacts=run_arts,
                          steps=[f"Executed {sel['notebook']} on {rt.get('name')}"])
    P.finish(run, "cancelled" if final == "cancelled" else "failed")
    ctx.save()
    return StepResult(status="cancelled" if final == "cancelled" else "failed", output=summary,
                      artifacts=run_arts, error=err or f"fine-tuning job {final}")


async def _stage_and_launch(ctx: StepContext, rt: dict, server: dict, sel: dict, c: dict):
    run, rid = ctx.run, ctx.run.run_id
    P.stage(run, "stage", "active")
    ctx.save()
    await _say(ctx, f"Staging {sel['notebook']} on DSLab runtime '{rt.get('name')}'…")
    try:
        nb = await asyncio.to_thread(catalog.load_notebook, sel["path"])
    except Exception as e:
        return _fail(ctx, "stage", f"could not read {sel['path']}: {e}")
    out_dir = await asyncio.to_thread(storage.ensure, rid)
    P.set(run, output_dir=out_dir)

    params = dict(sel.get("parameters") or {})
    declared = {d["name"] for d in sel.get("declared_parameters") or []}
    for n in OUTPUT_PARAM_NAMES:
        if n in declared and n not in params:
            params[n] = "outputs"          # = STUDIO_OUTPUT_DIR, relative to the job directory
    env = {"STUDIO_RUN_ID": rid, "STUDIO_NOTEBOOK": sel["notebook"],
           "STUDIO_WORKFLOW_ID": run.workflow_id or ""}

    # dataset from File Storage -> <job>/data/<name>
    ds = sel.get("dataset")
    if ds:
        if ds["size"] > c["dataset_max_mb"] * 1024 * 1024:
            return _fail(ctx, "stage", f"dataset {ds['path']} is {_fmt_bytes(ds['size'])}, above the "
                                       f"{c['dataset_max_mb']} MB staging limit. Put it on the runtime "
                                       f"and pass its path as a parameter instead.")
        name = ds["path"].rsplit("/", 1)[-1]
        rel = f"data/{name}"
        try:
            data = await asyncio.to_thread(filestore.read_bytes, ds["path"])
            if len(data) <= _INLINE_STAGE_BYTES:
                import base64
                await asyncio.to_thread(remote.call, server, "stage_job_file",
                                        {"job_id": rid, "name": rel, "encoding": "base64",
                                         "content": base64.b64encode(data).decode()})
            else:
                await asyncio.to_thread(remote.upload_bytes, server, rt, rid, rel, data)
        except Exception as e:
            return _fail(ctx, "stage", f"could not stage the dataset: {e}")
        env["STUDIO_DATASET"] = rel
        if sel.get("dataset_parameter"):
            params[sel["dataset_parameter"]] = rel
        else:
            P.warn(run, f"dataset staged at `{rel}` (env `STUDIO_DATASET`); the notebook declares no "
                        f"dataset parameter")

    # MLflow run first, so the job logs into it
    remote_uri = remote.runtime_mlflow_uri(rt)
    info, merr = await asyncio.to_thread(
        mlflow_log.start_run, rid, run.workflow_id or "", sel, rt, params,
        (run.progress or {}).get("requirement", ""))
    if merr:
        P.warn(run, merr)
    if info:
        env.update({"MLFLOW_RUN_ID": info["run_id"], "MLFLOW_EXPERIMENT_NAME": info["experiment"],
                    "MLFLOW_EXPERIMENT_ID": str(info["experiment_id"])})
        if remote_uri:
            env["MLFLOW_TRACKING_URI"] = remote_uri
        else:
            P.warn(run, "no MLflow URI for the runtime - set it on the DSLab runtime or in "
                        "fine-tuning settings so the notebook can log")
    P.set(run, mlflow={**info, "remote_tracking_uri": remote_uri} if info else
          {"error": merr, "remote_tracking_uri": remote_uri})

    pnb = inject(nb, params, f"run {rid} · {sel['notebook']}")
    try:
        await asyncio.to_thread(_write_config, rid, run, sel, params, rt, env, nb, pnb)
    except Exception as e:
        P.warn(run, f"could not write the run configuration: {e}")
    try:
        await asyncio.to_thread(remote.stage_text, server, rid, "notebook.ipynb", json.dumps(pnb))
    except Exception as e:
        return _fail(ctx, "stage", f"could not stage the notebook on the runtime: {e}")
    P.stage(run, "stage", "done", f"studio-jobs/{rid}/ on {rt.get('name')}")
    P.stage(run, "launch", "active")
    ctx.save()

    try:
        res = await asyncio.to_thread(remote.start, server, rid, env, float(c["job_timeout_hours"]))
    except Exception as e:
        return _fail(ctx, "launch", f"could not start the job: {e}")
    job = {"id": rid, "pid": res.get("pid"), "remote_dir": res.get("job_dir"),
           "python": res.get("python"), "started_at": P.now(), "runtime_id": rt["id"]}
    P.set(run, job=job, reattach=True)
    try:
        storage.write_json(rid, "config/job.json", {**job, "env": {k: v for k, v in env.items()}})
    except Exception:
        pass
    P.stage(run, "launch", "done", f"pid {job['pid']}")
    P.stage(run, "execute", "active")
    ctx.save()
    await _say(ctx, f"Job started on {rt.get('name')} (pid {job['pid']}) in {job['remote_dir']}. "
                    f"Execution continues in the background; progress updates every "
                    f"{c['poll_seconds']}s.")
    return None


def _write_config(rid, run, sel, params, rt, env, nb, pnb):
    req = {"input": {k: v for k, v in (run.input or {}).items() if k != "history"},
           "workflow_id": run.workflow_id, "workflow_name": run.workflow_name,
           "created_at": run.created_at}
    storage.write_json(rid, "config/request.json", req)
    storage.write_json(rid, "config/selection.json",
                       {k: v for k, v in sel.items() if k != "declared_parameters"})
    storage.write_json(rid, "config/parameters.json",
                       {"injected": params,
                        "notebook_defaults": {d["name"]: d["default"]
                                              for d in sel.get("declared_parameters") or []}})
    storage.write_json(rid, "config/runtime.json",
                       {k: rt.get(k) for k in ("id", "name", "provider", "host", "gpu_type",
                                               "workdir", "python_path", "mlflow_uri")})
    storage.write_json(rid, "notebook/source.ipynb", nb)
    storage.write_json(rid, "notebook/parameterized.ipynb", pnb)


async def _sleep(rid: str, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end and not cancel_reg.is_cancelled(rid):
        await asyncio.sleep(min(1.0, max(0.05, end - time.time())))


def _apply_status(run, st: dict) -> None:
    p = run.progress
    cells = st.get("cells") or {}
    bar = st.get("bar")
    # progress-bar rate / ETA (exponential smoothing over successive polls)
    if bar and bar.get("total"):
        prev = p.get("bar") or {}
        now = time.time()
        if prev.get("desc") == bar.get("desc") and prev.get("total") == bar["total"] \
                and bar["n"] > prev.get("n", 0) and prev.get("_t"):
            inst = (bar["n"] - prev["n"]) / max(1e-6, now - prev["_t"])
            bar["rate"] = round(0.6 * inst + 0.4 * prev.get("rate", inst), 4)
        elif prev.get("rate") and prev.get("desc") == bar.get("desc"):
            bar["rate"] = prev["rate"]
        if bar.get("rate"):
            bar["eta_s"] = int((bar["total"] - bar["n"]) / bar["rate"])
        bar["_t"] = now if bar["n"] != prev.get("n") or not prev.get("_t") else prev["_t"]
    total = int(cells.get("total") or 0)
    done = int(cells.get("completed") or 0)
    custom = st.get("custom") or {}
    frac = 0.0
    # within-cell progress: the notebook's own ##STUDIO_PROGRESS step/total for the CURRENT cell
    # wins over a tqdm bar (often a data-loading bar), else the bar
    if (st.get("custom_cell") == cells.get("current") and custom.get("total_steps")
            and isinstance(custom.get("step"), (int, float))):
        frac = min(1.0, float(custom["step"]) / max(1.0, float(custom["total_steps"])))
    elif bar and bar.get("total"):
        frac = min(1.0, bar["n"] / bar["total"])
    # ETA for the current cell from the within-cell progress rate (smoothed across polls)
    now, cur = time.time(), cells.get("current")
    obs = p.get("_frac_obs") or {}
    if obs.get("cell") == cur and obs.get("t") and frac > obs.get("frac", 0):
        inst = (frac - obs["frac"]) / max(1e-6, now - obs["t"])
        rate = 0.6 * inst + 0.4 * obs.get("rate", inst)
        p["_frac_obs"] = {"cell": cur, "frac": frac, "t": now, "rate": rate}
        p["cell_eta_s"] = int((1 - frac) / rate) if rate > 0 else None
    elif obs.get("cell") != cur or frac < obs.get("frac", 0):
        p["_frac_obs"] = {"cell": cur, "frac": frac, "t": now}
        p["cell_eta_s"] = None
    p["cell_fraction"] = round(frac, 4)
    if isinstance(custom.get("percent"), (int, float)):
        percent = float(custom["percent"])
    elif total:
        percent = 100.0 * (done + (frac if done < total else 0)) / total
    else:
        percent = 0.0
    p.update({
        "remote_state": st.get("state"), "cells": cells, "bar": bar, "custom": custom,
        "log_tail": (st.get("log_tail") or [])[-15:], "engine": st.get("engine"),
        "heartbeat": st.get("heartbeat"), "failed_cell": st.get("failed_cell"),
        "remote_outputs": st.get("outputs"), "mlflow_artifacts": st.get("mlflow_artifacts"),
        "mlflow_reachable": st.get("mlflow_reachable"), "mlflow_detail": st.get("mlflow_detail"),
        "remote_error": st.get("error") or "", "percent": round(min(100.0, percent), 1),
        "elapsed_s": int(_secs_since((p.get("job") or {}).get("started_at"))),
        "updated_at": P.now(), "contact_warning": "",
    })
    if st.get("runner_out"):
        p["runner_out"] = st["runner_out"][-2000:]


def _apply_metrics(run, m: dict) -> None:
    if not m or m.get("error"):
        return
    latest = m.get("latest") or {}
    custom = run.progress.get("custom") or {}
    train = {"latest": {k: round(v, 6) for k, v in list(latest.items())[:40]},
             "loss_key": m.get("loss_key"), "loss": latest.get(m.get("loss_key") or ""),
             "eval_loss": latest.get(m.get("eval_key") or ""), "epoch": latest.get("epoch"),
             "step": m.get("step"), "loss_history": m.get("loss_history") or [],
             "mlflow_status": m.get("status")}
    for k in ("step", "total_steps", "epoch", "loss", "eval_loss"):
        if custom.get(k) is not None and train.get(k) is None:
            train[k] = custom[k]
    run.progress["train"] = train


async def _monitor(ctx: StepContext, server: dict, c: dict) -> tuple[str, str]:
    run, rid = ctx.run, ctx.run.run_id
    poll = max(3, int(c["poll_seconds"]))
    lost_after = max(1, int(c["lost_contact_minutes"])) * 60
    last_ok = time.time()
    last_cell = None
    last_metric_emit = 0.0
    mlflow_warned = False
    mid = (run.progress.get("mlflow") or {}).get("run_id", "")
    while True:
        if cancel_reg.is_cancelled(rid):
            await _say(ctx, "Stop requested - stopping the job on the runtime…", level="warn")
            try:
                await asyncio.to_thread(remote.cancel, server, rid)
            except Exception as e:
                P.warn(run, f"could not confirm the job stopped: {e}")
            try:
                _apply_status(run, await asyncio.to_thread(remote.status, server, rid))
            except Exception:
                pass
            ctx.save()
            return "cancelled", "Interrupted by user."
        try:
            st = await asyncio.to_thread(remote.status, server, rid)
            last_ok = time.time()
        except Exception as e:
            gap = time.time() - last_ok
            P.set(run, contact_warning=f"cannot reach the runtime for {_fmt_dur(gap)}: {str(e)[:200]}")
            ctx.save()
            if gap > lost_after:
                return "failed", (f"lost contact with the DSLab runtime for {_fmt_dur(gap)} "
                                  f"({str(e)[:200]}). The job may still be running in "
                                  f"studio-jobs/{rid}/ on the runtime.")
            await _sleep(rid, poll)
            continue

        _apply_status(run, st)
        if mid:
            _apply_metrics(run, await asyncio.to_thread(mlflow_log.poll_metrics, mid))
        ctx.save()

        if st.get("mlflow_reachable") is False and not mlflow_warned:
            mlflow_warned = True
            msg = (f"The notebook cannot reach MLflow from the runtime ({st.get('mlflow_detail', '')}). "
                   f"Set the runtime's MLflow URI (DSLab) to an address reachable from that machine. "
                   f"The platform still records configuration, logs and results.")
            P.warn(run, msg)
            await _say(ctx, msg, level="warn")
        cells = st.get("cells") or {}
        if cells.get("current") is not None and cells.get("current") != last_cell:
            last_cell = cells.get("current")
            await _say(ctx, f"Cell {cells.get('number', '?')}/{cells.get('total', '?')}"
                            + (f" · {cells['title']}" if cells.get("title") else ""),
                       kind=ActivityKind.state_update)
        tr = run.progress.get("train") or {}
        if tr.get("loss") is not None and time.time() - last_metric_emit > 300:
            last_metric_emit = time.time()
            await _say(ctx, f"Training metrics: {tr.get('loss_key') or 'loss'} {tr['loss']:.4g}"
                            + (f" · eval_loss {tr['eval_loss']:.4g}" if tr.get("eval_loss") is not None else "")
                            + (f" · epoch {tr['epoch']:.2f}" if tr.get("epoch") is not None else ""),
                       kind=ActivityKind.state_update)
        state = st.get("state")
        if state in TERMINAL:
            fc = st.get("failed_cell") or {}
            err = {"completed": "",
                   "failed": (f"cell {fc.get('number', fc.get('index'))}"
                              + (f" ({fc['title']})" if fc.get("title") else "")
                              + " failed: "
                              + (f"{fc['ename']}: {fc.get('evalue', '')}" if fc.get("ename")
                                 else (fc.get("detail") or st.get("error") or "unknown error")[-600:])),
                   "cancelled": "the job was stopped on the runtime",
                   "timeout": f"the job exceeded its {c['job_timeout_hours']} h limit and was stopped",
                   "lost": st.get("error") or "the job process disappeared on the runtime",
                   "not_found": f"no job studio-jobs/{rid}/ on the runtime"}[state]
            return ("completed" if state == "completed" else
                    "cancelled" if state == "cancelled" else "failed"), err
        await _sleep(rid, poll)


async def _collect(ctx: StepContext, rt: dict, server: dict, c: dict) -> None:
    run, rid = ctx.run, ctx.run.run_id
    P.stage(run, "collect", "active")
    ctx.save()
    max_file = int(c["copy_max_file_mb"]) * 1024 * 1024
    max_total = int(c["copy_max_total_mb"]) * 1024 * 1024
    summary = {"executed_notebook": False, "log_copied": False, "files": 0, "bytes": 0,
               "copied": 0, "copied_bytes": 0, "skipped": 0}
    try:
        await asyncio.to_thread(storage.ensure, rid)
        listing = await asyncio.to_thread(remote.outputs, server, rid)
    except Exception as e:
        P.warn(run, f"could not list job outputs: {e}")
        P.set(run, outputs=summary)
        P.stage(run, "collect", "failed", str(e)[:200])
        ctx.save()
        return
    sizes = {f["name"]: f.get("size") or 0 for f in listing.get("job_files") or []}

    async def fetch(remote_rel: str, local_rel: str) -> bool:
        data = await asyncio.to_thread(remote.download, server, rt, rid, remote_rel)
        await asyncio.to_thread(storage.write_bytes, rid, local_rel, data)
        return True

    for rname, lrel in (("executed.ipynb", "notebook/executed.ipynb"), ("run.log", "logs/run.log"),
                        ("status.json", "logs/status.json"), ("runner.out", "logs/runner.out")):
        if rname not in sizes:
            continue
        if sizes[rname] > max_file:
            P.warn(run, f"`{rname}` is {_fmt_bytes(sizes[rname])} - left on the runtime "
                        f"(`studio-jobs/{rid}/{rname}`)")
            continue
        try:
            await fetch(rname, lrel)
            if rname == "executed.ipynb":
                summary["executed_notebook"] = True
            if rname == "run.log":
                summary["log_copied"] = True
        except Exception as e:
            P.warn(run, f"could not copy {rname}: {str(e)[:200]}")

    manifest = listing.get("manifest") or {}
    files = manifest.get("files") or []
    summary["files"] = len(files)
    summary["bytes"] = int(manifest.get("total_bytes") or 0)
    entries, metric_values = [], {}
    for f in files:
        rel = f.get("path", "")
        size = int(f.get("size") or 0)
        e = {**f, "remote_path": f"{manifest.get('root', '')}/{rel}", "copied": False}
        if f.get("error"):
            pass
        elif size > max_file:
            e["reason"] = f"larger than {c['copy_max_file_mb']} MB"
        elif summary["copied_bytes"] + size > max_total:
            e["reason"] = f"total copy limit {c['copy_max_total_mb']} MB reached"
        elif summary["copied"] >= int(c["copy_max_files"]):
            e["reason"] = "file count limit reached"
        else:
            try:
                await fetch(f"outputs/{rel}", f"model/{rel}")
                e["copied"] = True
                e["local_path"] = f"{storage.run_dir(rid)}/model/{rel}"
                summary["copied"] += 1
                summary["copied_bytes"] += size
                base = rel.rsplit("/", 1)[-1]
                if base in METRIC_FILES and size < 2 * 1024 * 1024:
                    try:
                        raw = filestore.read_text(e["local_path"])
                        await asyncio.to_thread(storage.write_text, rid, f"metrics/notebook_{base}", raw)
                        vals = json.loads(raw)
                        if isinstance(vals, dict):
                            metric_values.update({k: v for k, v in vals.items()
                                                  if isinstance(v, (int, float)) and not isinstance(v, bool)})
                    except Exception:
                        pass
            except Exception as ex:
                e["reason"] = f"copy failed: {str(ex)[:160]}"
        if not e["copied"]:
            summary["skipped"] += 1
        entries.append(e)

    p = run.progress
    mart = p.get("mlflow_artifacts") or {}
    mlf = p.get("mlflow") or {}
    model_manifest = {
        "run_id": rid, "runtime": p.get("runtime"), "remote_root": manifest.get("root"),
        "generated_at": manifest.get("generated_at"), "total_files": summary["files"],
        "total_bytes": summary["bytes"], "copied_files": summary["copied"],
        "copied_bytes": summary["copied_bytes"],
        "copy_limits": {"max_file_mb": c["copy_max_file_mb"], "max_total_mb": c["copy_max_total_mb"]},
        "mlflow": {"run_id": mlf.get("run_id"), "url": mlf.get("url"),
                   "artifacts_logged": bool(mart.get("logged")),
                   "artifact_path": mart.get("artifact_path"), "detail": mart.get("detail")},
        "files": entries,
    }
    try:
        storage.write_json(rid, "model/MANIFEST.json", model_manifest)
        tr = p.get("train") or {}
        storage.write_json(rid, "metrics/metrics.json", {
            "notebook": metric_values, "mlflow_latest": tr.get("latest") or {},
            "job": {"state": (p.get("job") or {}).get("final_state"),
                    "cells_completed": (p.get("cells") or {}).get("completed"),
                    "cells_total": (p.get("cells") or {}).get("total"),
                    "duration_s": int(_secs_since((p.get("job") or {}).get("started_at")))}})
    except Exception as e:
        P.warn(run, f"could not write the manifest: {e}")
    summary["metrics"] = metric_values
    P.set(run, outputs=summary)
    P.stage(run, "collect", "done",
            f"{summary['copied']}/{summary['files']} file(s), {_fmt_bytes(summary['copied_bytes'])} copied")
    ctx.save()


async def _log_mlflow(ctx: StepContext, final: str) -> None:
    run, rid = ctx.run, ctx.run.run_id
    p = run.progress
    mid = (p.get("mlflow") or {}).get("run_id")
    if not mid:
        P.stage(run, "mlflow", "skipped", (p.get("mlflow") or {}).get("error") or "MLflow is off")
        ctx.save()
        return
    P.stage(run, "mlflow", "active")
    ctx.save()
    errs = []
    for sub, ap in (("notebook", "studio/notebook"), ("logs", "studio/logs"),
                    ("config", "studio/config"), ("metrics", "studio/metrics")):
        e = await asyncio.to_thread(mlflow_log.log_artifacts, mid, storage.local_path(rid, sub), ap)
        if e:
            errs.append(f"{sub}: {e}")
    e = await asyncio.to_thread(mlflow_log.log_artifact, mid,
                                storage.local_path(rid, "model/MANIFEST.json"), "studio/model")
    if e:
        errs.append(f"manifest: {e}")
    out = p.get("outputs") or {}
    cells = p.get("cells") or {}
    metrics = {"duration_s": int(_job_duration(p.get("job") or {})),
               "cells_completed": cells.get("completed") or 0, "cells_total": cells.get("total") or 0,
               "outputs_files": out.get("files", 0), "outputs_bytes": out.get("bytes", 0),
               "copied_bytes": out.get("copied_bytes", 0), "success": 1 if final == "completed" else 0}
    e = await asyncio.to_thread(mlflow_log.finalize, mid, final, metrics,
                                {"studio.status": final, "studio.output_dir": storage.run_dir(rid)})
    if e:
        errs.append(f"finalize: {e}")
    if errs:
        P.warn(run, "MLflow: " + "; ".join(errs)[:400])
    P.stage(run, "mlflow", "done" if not errs else "failed",
            f"run {mid}" if not errs else "; ".join(errs)[:200])
    ctx.save()


def _summary_md(run) -> str:
    p = run.progress
    sel = p.get("selection") or {}
    job = p.get("job") or {}
    state = job.get("final_state") or p.get("state")
    cells = p.get("cells") or {}
    out = p.get("outputs") or {}
    tr = p.get("train") or {}
    mlf = p.get("mlflow") or {}
    mart = p.get("mlflow_artifacts") or {}
    head = {"completed": "completed", "cancelled": "stopped", "failed": "failed"}.get(state, state)
    lines = [f"### Fine-tuning run `{run.run_id}` — {head}", "",
             "| | |", "|---|---|",
             f"| Notebook | `{sel.get('notebook', '')}` ({sel.get('method', '')}) |",
             f"| Runtime | {(p.get('runtime') or {}).get('name', '')} |",
             f"| Duration | {_fmt_dur(_job_duration(job))} |",
             f"| Cells | {cells.get('completed', 0)}/{cells.get('total', 0)} |"]
    if sel.get("parameters"):
        lines.append("| Parameters | " + ", ".join(f"`{k}={json.dumps(v)}`"
                                                  for k, v in sel["parameters"].items()) + " |")
    lines.append("")
    if state != "completed" and (p.get("failed_cell") or p.get("error") or p.get("remote_error")):
        fc = p.get("failed_cell") or {}
        detail = (fc.get("detail") or p.get("remote_error") or p.get("error") or "")[-1200:]
        lines += [("**Stopped during** (cell " if state == "cancelled" else "**What went wrong** (cell ")
                  + f"{fc.get('number', '?')}"
                  + (f" · {fc['title']}" if fc.get("title") else "") + "):", "", "```", detail, "```", ""]
    mvals = {}
    if tr.get("latest"):
        mvals.update(tr["latest"])
    mvals.update(out.get("metrics") or {})
    if mvals:
        keys = sorted(mvals, key=lambda k: (0 if "loss" in k else 1 if "eval" in k else 2, k))[:12]
        lines += ["**Metrics**", "", "| Metric | Value |", "|---|---|"]
        lines += [f"| `{k}` | {mvals[k]:.6g} |" if isinstance(mvals[k], (int, float)) else
                  f"| `{k}` | {mvals[k]} |" for k in keys]
        lines.append("")
    lines += ["**Outputs**", "",
              f"- {out.get('files', 0)} file(s), {_fmt_bytes(out.get('bytes', 0))}, on the runtime in "
              f"`{job.get('remote_dir', '')}/outputs`",
              f"- {out.get('copied', 0)} copied ({_fmt_bytes(out.get('copied_bytes', 0))}) to File Storage "
              f"`{p.get('output_dir', '')}/model/` — see `model/MANIFEST.json` for every file and checksum",
              f"- MLflow artifacts: " + ("uploaded under `outputs/`" if mart.get("logged")
                                         else (mart.get("detail") or "not uploaded"))]
    if mlf.get("run_id"):
        lines.append(f"- MLflow run `{mlf['run_id']}` in experiment `{mlf.get('experiment', '')}`"
                     + (f" — [open]({mlf['url']})" if mlf.get("url") else ""))
    if p.get("warnings"):
        lines += ["", "**Notes**", ""] + [f"- {w}" for w in p["warnings"][:10]]
    return "\n".join(lines)


# =========================================================================== reporter
async def reporter_step(ctx: StepContext) -> StepResult:
    run, rid = ctx.run, ctx.run.run_id
    p = P.ensure(run)
    P.stage(run, "report", "active")
    ctx.save()
    try:
        summary = filestore.read_text(f"{storage.run_dir(rid)}/summary.md")
    except Exception:
        summary = _summary_md(run)
    facts = {"requirement": p.get("requirement"), "selection": {k: v for k, v in (p.get("selection") or {}).items()
                                                                if k not in ("declared_parameters",)},
             "runtime": p.get("runtime"), "state": (p.get("job") or {}).get("final_state"),
             "cells": p.get("cells"), "training": {k: v for k, v in (p.get("train") or {}).items()
                                                   if k != "loss_history"},
             "outputs": p.get("outputs"), "mlflow": p.get("mlflow"), "output_dir": p.get("output_dir"),
             "warnings": p.get("warnings")}
    system = ((ctx.card.get("prompts") or {}).get("system_prompt")
              or "You write concise fine-tuning run reports.")
    user = ("Write the final report for this fine-tuning run for a business user, in markdown, "
            "under 250 words: outcome, key metrics with values, where the model and outputs are "
            "(File Storage folder and MLflow run), anything to watch out for, and 1-3 concrete next "
            "steps. Use ONLY these facts; do not invent numbers.\n\nFacts (JSON):\n"
            + json.dumps(facts, default=str)[:12000])
    text, tin, tout, how = "", 0, 0, "model"
    try:
        text, tin, tout, note = await llm.complete(ctx.card, system, user, rid, ctx.agent, max_tokens=900)
        if note:
            P.warn(run, note)
    except Exception as e:
        how = f"deterministic ({type(e).__name__})"
    arts = []
    if text.strip():
        try:
            storage.write_text(rid, "report.md", text)
            arts.append(storage.artifact(rid, "report.md", "text/markdown", text[:4000]))
        except Exception:
            pass
        output = text.strip() + "\n\n---\n\n" + summary
    else:
        output = summary
    out_dir = p.get("output_dir", "")
    mlf = p.get("mlflow") or {}
    output += (f"\n\n**Run folder:** `{out_dir}`"
               + (f" · **MLflow:** [{mlf.get('run_id')}]({mlf['url']})" if mlf.get("url") else ""))
    P.stage(run, "report", "done", how)
    P.finish(run, "completed")
    ctx.save()
    return StepResult(output=output, artifacts=arts, in_tokens=tin, out_tokens=tout)
