"""Fine-tuning router — /api/v1/finetune/*.

Small surface on top of the existing run/workflow APIs (runs are started with POST /runs as
usual): the notebook catalog, settings, runtimes to choose from, and a run's progress.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/finetune", tags=["finetuning"])


@router.get("/config")
def get_config():
    from ..finetune import config
    return {**config.get(), "backend_mlflow_uri": config.backend_mlflow_uri(),
            "mlflow_ui_url_effective": config.mlflow_ui_url()}


@router.put("/config")
def put_config(body: dict):
    from ..finetune import config
    from ..governance import audit
    cfg = config.update(body or {})
    audit("admin", "update", "finetune_settings", detail=",".join((body or {}).keys()))
    return cfg


@router.get("/catalog")
def get_catalog():
    """Every notebook in the fine-tuning folder, as the planner sees it."""
    from ..finetune import catalog, config
    items = catalog.list_notebooks()
    return {"folder": config.get()["notebooks_dir"], "count": len(items), "notebooks": items}


@router.get("/runtimes")
def runtimes():
    """DSLab runtimes a job can run on (secrets removed) + the one used by default."""
    from ..finetune import config, remote
    from ..modules.data_science_lab import config as dsl_cfg
    from ..modules.data_science_lab import store as dsl_store
    rows = dsl_store.list_runtimes()
    default = ""
    try:
        default = remote.resolve_runtime("")["id"]
    except Exception:
        pass
    return {"dsl_enabled": dsl_cfg.is_enabled(), "default_runtime_id": default,
            "configured_default": config.get().get("default_runtime_id", ""),
            "runtimes": [{"id": r["id"], "name": r.get("name"), "gpu_type": r.get("gpu_type", ""),
                          "status": r.get("status"), "agent_access": bool(r.get("agent_mcp_server")),
                          "mlflow_uri": r.get("mlflow_uri", "")} for r in rows]}


@router.get("/runs/{run_id}/progress")
def run_progress(run_id: str):
    from ..store import runs as runs_repo
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return {"run_id": run_id, "status": r.get("status"), "error": r.get("error", ""),
            "progress": r.get("progress") or {}}


@router.get("/runs")
def finetune_runs(limit: int = 50):
    """Recent fine-tuning runs (those with fine-tuning progress), newest first."""
    from ..store import runs as runs_repo
    rows = [r for r in runs_repo.list() if (r.get("progress") or {}).get("kind") == "finetune"]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    out = []
    for r in rows[:limit]:
        p = r.get("progress") or {}
        out.append({"run_id": r["run_id"], "status": r.get("status"), "created_at": r.get("created_at"),
                    "notebook": (p.get("selection") or {}).get("notebook"),
                    "runtime": (p.get("runtime") or {}).get("name"), "stage": p.get("stage"),
                    "percent": p.get("percent"), "output_dir": p.get("output_dir"),
                    "mlflow_url": (p.get("mlflow") or {}).get("url")})
    return out
