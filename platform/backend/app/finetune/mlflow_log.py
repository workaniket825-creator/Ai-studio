"""MLflow logging for fine-tuning jobs.

One MLflow run per workflow run, in the `finetuning` experiment (configurable):
  * created by the platform BEFORE launch, with tags, the selection and every injected
    parameter (as `studio.param.<name>` so they never collide with params the notebook or the
    HF Trainer log themselves - MLflow refuses to change a param's value);
  * its id is passed to the job as MLFLOW_RUN_ID, so mlflow.start_run() in the notebook and the
    Hugging Face MLflowCallback log into this same run;
  * polled during the job for live metrics (loss, eval loss, epoch...);
  * finalised after the job: executed notebook, logs, manifest, summary, status.

Uses MlflowClient only - never the fluent API - so it cannot disturb the platform's own
run-level observability sink, which uses the fluent API on the main thread.
All functions are blocking and never raise: failures come back as an error string.
"""
from __future__ import annotations

import logging
import os

from . import config

_log = logging.getLogger("tcs.finetune.mlflow")

LOSS_KEYS = ("loss", "train_loss", "train/loss", "training_loss")
EVAL_KEYS = ("eval_loss", "eval/loss", "val_loss", "validation_loss")


def enabled() -> bool:
    return bool(config.backend_mlflow_uri())


def _client():
    from mlflow.tracking import MlflowClient
    return MlflowClient(tracking_uri=config.backend_mlflow_uri())


def _clip(v, n=500) -> str:
    s = str(v)
    return s if len(s) <= n else s[: n - 3] + "..."


def start_run(run_id: str, workflow_id: str, selection: dict, runtime: dict, params: dict,
              requirement: str) -> tuple[dict, str]:
    """Create the MLflow run. Returns ({experiment_id, run_id, url}, error)."""
    if not enabled():
        return {}, "MLFLOW_TRACKING_URI is not set on the backend - MLflow logging is off"
    try:
        from mlflow.entities import Param, RunTag
        c = _client()
        name = config.get()["experiment"]
        exp = c.get_experiment_by_name(name)
        exp_id = exp.experiment_id if exp else c.create_experiment(name)
        nb = selection.get("notebook", "")
        tags = {"studio.run_id": run_id, "studio.workflow_id": workflow_id or "",
                "studio.notebook": nb, "studio.runtime": runtime.get("name", ""),
                "studio.runtime_id": runtime.get("id", ""),
                "studio.selection_method": selection.get("method", ""),
                "mlflow.note.content": _clip(f"Fine-tuning run started by TCS Domain AI Studio.\n\n"
                                             f"Request: {requirement}\n\nReason: "
                                             f"{selection.get('reason', '')}", 5000)}
        r = c.create_run(exp_id, run_name=f"{nb.rsplit('/', 1)[-1].removesuffix('.ipynb')} · {run_id}",
                         tags=tags)
        mid = r.info.run_id
        plist = [Param("studio.notebook", _clip(nb)),
                 Param("studio.runtime", _clip(runtime.get("name", ""))),
                 Param("studio.selection_method", _clip(selection.get("method", "")))]
        plist += [Param(_clip(f"studio.param.{k}", 250), _clip(v)) for k, v in params.items()]
        for i in range(0, len(plist), 90):
            c.log_batch(mid, params=plist[i:i + 90])
        return {"experiment_id": exp_id, "experiment": name, "run_id": mid,
                "url": run_url(exp_id, mid)}, ""
    except Exception as e:
        _log.warning("MLflow start_run failed: %s", e)
        return {}, f"MLflow run could not be created: {type(e).__name__}: {e}"


def run_url(exp_id: str, mlflow_run_id: str) -> str:
    ui = config.mlflow_ui_url()
    return f"{ui}/#/experiments/{exp_id}/runs/{mlflow_run_id}" if ui else ""


def poll_metrics(mlflow_run_id: str) -> dict:
    """Latest metrics + a short loss history for the progress view."""
    if not (enabled() and mlflow_run_id):
        return {}
    try:
        c = _client()
        r = c.get_run(mlflow_run_id)
        latest = {k: v for k, v in (r.data.metrics or {}).items() if not k.startswith("studio.")}
        out: dict = {"latest": latest, "status": r.info.status}
        lk = next((k for k in LOSS_KEYS if k in latest), None)
        if lk:
            hist = c.get_metric_history(mlflow_run_id, lk)
            pts = [{"step": h.step, "value": h.value} for h in hist]
            if len(pts) > 200:   # thin out, keep the last point
                stride = len(pts) / 200
                pts = [pts[int(i * stride)] for i in range(200)] + [pts[-1]]
            out["loss_key"], out["loss_history"] = lk, pts
            out["step"] = hist[-1].step if hist else None
        ek = next((k for k in EVAL_KEYS if k in latest), None)
        if ek:
            out["eval_key"] = ek
        return out
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def log_artifacts(mlflow_run_id: str, local_dir, artifact_path: str) -> str:
    if not (enabled() and mlflow_run_id):
        return "mlflow off"
    try:
        if os.path.isdir(local_dir) and any(os.scandir(local_dir)):
            _client().log_artifacts(mlflow_run_id, str(local_dir), artifact_path=artifact_path)
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"[:300]


def log_artifact(mlflow_run_id: str, local_file, artifact_path: str) -> str:
    if not (enabled() and mlflow_run_id):
        return "mlflow off"
    try:
        if os.path.isfile(local_file):
            _client().log_artifact(mlflow_run_id, str(local_file), artifact_path=artifact_path)
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"[:300]


def finalize(mlflow_run_id: str, state: str, metrics: dict, tags: dict) -> str:
    if not (enabled() and mlflow_run_id):
        return "mlflow off"
    try:
        import time
        from mlflow.entities import Metric, RunTag
        c = _client()
        ts = int(time.time() * 1000)
        ms = [Metric(f"studio.{k}", float(v), ts, 0) for k, v in metrics.items()
              if isinstance(v, (int, float)) and not isinstance(v, bool)]
        ts_tags = [RunTag(k, _clip(v, 5000)) for k, v in tags.items()]
        c.log_batch(mlflow_run_id, metrics=ms, tags=ts_tags)
        c.set_terminated(mlflow_run_id, {"completed": "FINISHED", "cancelled": "KILLED"}.get(state, "FAILED"))
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"[:300]
