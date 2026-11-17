"""Fine-tuning settings, stored in the Governance settings document (section "finetune")
so they can be changed at run time without a restart, like File Storage settings."""
from __future__ import annotations

import os

DEFAULTS: dict = {
    "notebooks_dir": "finetuning/notebooks",   # File Storage folder holding fine-tuning notebooks
    "datasets_dir": "finetuning/datasets",     # optional folder for training data
    "runs_dir": "finetuning/runs",             # one sub-folder per workflow run
    "experiment": "finetuning",                # MLflow experiment for job runs
    "default_runtime_id": "",                  # DSLab runtime used when the request names none
    # MLflow tracking URI the notebook uses ON the DSLab runtime. "" = the runtime's own MLflow
    # URI (DSLab > runtime settings), then the backend's MLFLOW_TRACKING_URI.
    "remote_mlflow_uri": "",
    "mlflow_ui_url": "",                       # browser URL of MLflow ("" = MLFLOW_UI_URL env)
    "poll_seconds": 15,                        # how often the platform checks job status
    "job_timeout_hours": 24,                   # hard stop enforced on the runtime
    "lost_contact_minutes": 30,                # give up after this long without reaching the runtime
    "copy_max_file_mb": 100,                   # copy job output files up to this size ...
    "copy_max_total_mb": 1024,                 # ... and up to this total, into the run folder
    "copy_max_files": 500,
    "dataset_max_mb": 200,                     # largest File Storage dataset staged to the runtime
    "log_outputs_to_mlflow": True,             # runner uploads outputs/ to the MLflow run
    "mlflow_max_gb": 20,                       # ... unless larger than this
}


def get() -> dict:
    from ..governance import get_settings
    stored = get_settings().get("finetune") or {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def update(patch: dict) -> dict:
    from ..governance import update_settings
    cur = get()
    for k, v in (patch or {}).items():
        if k not in DEFAULTS:
            continue
        d = DEFAULTS[k]
        try:
            if isinstance(d, bool):
                v = bool(v)
            elif isinstance(d, int):
                v = int(v)
            elif isinstance(d, float):
                v = float(v)
            elif isinstance(d, str):
                v = str(v).strip()
        except (TypeError, ValueError):
            continue
        cur[k] = v
    for k in ("notebooks_dir", "datasets_dir", "runs_dir"):
        cur[k] = cur[k].strip("/") or DEFAULTS[k]
    update_settings({"finetune": cur})
    return cur


def backend_mlflow_uri() -> str:
    return os.getenv("MLFLOW_TRACKING_URI", "")


def mlflow_ui_url() -> str:
    c = get()
    return (c.get("mlflow_ui_url") or os.getenv("MLFLOW_UI_URL", "")
            or backend_mlflow_uri()).rstrip("/")
