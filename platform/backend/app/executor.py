"""Central run executor (Phase A hardened).

Every run — from Chat, Workflow Studio, agent Test, Templates, or Schedules —
goes through `run_workflow()`. Guarantees:
  * bounded concurrency (a semaphore sized from Governance -> Platform Settings),
  * a per-run wall-clock timeout (settings-driven),
  * the run ALWAYS reaches a terminal state (pollers/chat never hang),
  * the run is ALWAYS recorded to the observability sink (MLflow/local).
All limits are read from the UI settings at run time, so they can be changed
from Governance -> Platform Settings without touching the backend.
"""
from __future__ import annotations

import asyncio
import logging

from .activity import bus, cancel
from .config import get_runtime
from .schemas import ActivityEvent, ActivityKind, Run, RunStatus
from .store import runs as runs_repo

_log = logging.getLogger("tcs.executor")

# concurrency gates; resized lazily to match the configured limits. Long-running workflows
# (workflow.config.long_running — e.g. fine-tuning) get their own lane so an hours-long job
# never occupies one of the ordinary run slots.
_sems: dict[str, tuple[asyncio.Semaphore, int]] = {}


def _semaphore(lane: str = "default") -> asyncio.Semaphore:
    from .governance import platform_settings
    ps = platform_settings()
    if lane == "long":
        want = max(1, int(ps.get("max_concurrent_long_runs", 2)))
    else:
        want = max(1, int(ps.get("max_concurrent_runs", 5)))
    cur = _sems.get(lane)
    if cur is None or cur[1] != want:
        cur = (asyncio.Semaphore(want), want)
        _sems[lane] = cur
    return cur[0]


def is_long_running(wf) -> bool:
    cfg = (getattr(wf, "config", None) or {}) if not isinstance(wf, dict) else (wf.get("config") or {})
    return bool(cfg.get("long_running"))


def timeout_for(wf) -> float:
    """Per-run wall-clock limit. A workflow may set config.run_timeout_seconds; long-running
    workflows default to platform.long_run_timeout_seconds; everything else is unchanged
    (platform.run_timeout_seconds, default 180 s)."""
    from .governance import platform_settings
    ps = platform_settings()
    cfg = (getattr(wf, "config", None) or {}) if not isinstance(wf, dict) else (wf.get("config") or {})
    if cfg.get("run_timeout_seconds"):
        return float(cfg["run_timeout_seconds"])
    if is_long_running(wf):
        return float(ps.get("long_run_timeout_seconds", 86400))
    return float(ps.get("run_timeout_seconds", 180))


async def run_workflow(run: Run, wf) -> None:
    rid = run.run_id
    timeout = timeout_for(wf)
    lane = "long" if is_long_running(wf) else "default"

    async with _semaphore(lane):
        try:
            await asyncio.wait_for(get_runtime().execute(run, wf), timeout=timeout)
        except asyncio.TimeoutError:
            run.status = RunStatus.failed
            run.error = f"Run exceeded the {int(timeout)}s time limit and was stopped."
            runs_repo.upsert(run.model_dump(by_alias=True))
            await _emit(rid, run.error)
        except Exception as e:  # never let a fire-and-forget task die silently
            run.status = RunStatus.failed
            run.error = f"Execution error: {e}"
            runs_repo.upsert(run.model_dump(by_alias=True))
            await _emit(rid, run.error)
        finally:
            cancel.clear(rid)
            _record(rid)


async def _emit(rid: str, msg: str) -> None:
    try:
        await bus.publish(ActivityEvent(run_id=rid, seq=bus.next_seq(rid),
                                        kind=ActivityKind.error, label=msg, level="error"))
    except Exception:
        pass


def _record(rid: str) -> None:
    try:
        latest = runs_repo.get(rid)
        if latest:
            from .observability import get_sink
            get_sink().record_run(Run(**latest))
    except Exception as e:
        _log.warning("observability logging failed: %s", e)
        try:
            from .observability import STATUS
            STATUS["last_error"] = f"record_run failed: {e}"
        except Exception:
            pass


def _reattachable(r: dict) -> bool:
    """A run whose long-running remote job was launched and has not finished. Its work keeps
    going on the remote machine, so on restart we re-attach to it instead of failing it."""
    prog = r.get("progress") or {}
    return bool(prog.get("reattach")) and bool((prog.get("job") or {}).get("id"))


def reattachable_runs() -> list[dict]:
    return runs_repo.list(lambda x: x.get("status") in ("running", "pending") and _reattachable(x))


def recover_orphans() -> int:
    """On startup, fail any run left 'running'/'pending' from a previous crash so
    nothing is stuck forever. Returns the number of runs recovered.
    Runs attached to a still-running remote job (see _reattachable) are left alone; the
    startup hook re-attaches them (app.finetune.resume)."""
    n = 0
    for r in runs_repo.list(lambda x: x.get("status") in ("running", "pending")):
        if _reattachable(r):
            continue
        r["status"] = RunStatus.failed.value if hasattr(RunStatus.failed, "value") else "failed"
        r["error"] = "Interrupted by a server restart."
        runs_repo.upsert(r)
        n += 1
    if n:
        _log.info("recovered %d orphaned run(s) on startup", n)
    return n
