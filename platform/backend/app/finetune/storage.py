"""Per-run output folder in File Storage:

    finetuning/runs/<run_id>/
        config/     request.json, selection.json, parameters.json, runtime.json, job.json
        notebook/   source.ipynb, parameterized.ipynb, executed.ipynb
        logs/       run.log, runner.out, status.json, progress.json
        metrics/    metrics.json (+ any metrics/eval JSON the notebook wrote)
        model/      copied output files + MANIFEST.json (all files, sizes, sha256, where they are)
        summary.md  (and report.md when the reporter used a model)

Everything goes through filestore, so paths stay confined to the storage root.
"""
from __future__ import annotations

import json
from typing import Any

from .. import filestore
from . import config

SUBDIRS = ("config", "notebook", "logs", "metrics", "model")


def run_dir(run_id: str) -> str:
    return f"{config.get()['runs_dir'].strip('/')}/{run_id}"


def ensure(run_id: str) -> str:
    d = run_dir(run_id)
    for s in SUBDIRS:
        filestore.mkdir(f"{d}/{s}")
    return d


def write_json(run_id: str, rel: str, obj: Any) -> str:
    path = f"{run_dir(run_id)}/{rel}"
    filestore.write_text(path, json.dumps(obj, indent=2, default=str), actor="finetune",
                         enforce_limits=False)
    return path


def write_text(run_id: str, rel: str, text: str) -> str:
    path = f"{run_dir(run_id)}/{rel}"
    filestore.write_text(path, text, actor="finetune", enforce_limits=False)
    return path


def write_bytes(run_id: str, rel: str, data: bytes) -> str:
    path = f"{run_dir(run_id)}/{rel}"
    filestore.write_bytes(path, data, actor="finetune", enforce_limits=False)
    return path


def local_path(run_id: str, rel: str = ""):
    """Absolute local path (for MLflow log_artifact). Confined to the storage root."""
    return filestore._resolve(f"{run_dir(run_id)}/{rel}".rstrip("/"))


def artifact(run_id: str, rel: str, mime: str = "application/octet-stream", preview: str = "") -> dict:
    """A run.artifacts entry that points at the file in File Storage."""
    import urllib.parse
    path = f"{run_dir(run_id)}/{rel}"
    name = rel.rsplit("/", 1)[-1]
    return {"id": name, "name": name, "path": path, "mime": mime,
            "uri": f"/api/v1/files/download?path={urllib.parse.quote(path)}",
            **({"preview": preview} if preview else {})}
