from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..insights import run_insights
from ..schemas import Run, RunStatus
from ..store import DATA_DIR, Repo
from ..store import runs as runs_repo

router = APIRouter(prefix="/api/v1", tags=["insights"])
reports_repo = Repo("insights_reports", "id")

_CONFIG = DATA_DIR / "insights_config.json"
_DEFAULT_CFG = {"scope": "org", "window_days": 30, "min_severity": "low",
                "cadence": "on_demand"}


@router.get("/insights/config")
def get_config():
    if _CONFIG.exists():
        return {**_DEFAULT_CFG, **json.loads(_CONFIG.read_text())}
    return dict(_DEFAULT_CFG)


@router.put("/insights/config")
def put_config(patch: dict):
    cfg = get_config(); cfg.update(patch)
    _CONFIG.write_text(json.dumps(cfg, indent=2))
    return cfg


@router.post("/insights/run")
async def run(_: dict | None = None):
    """Execute the insights meta-workflow (streams to the activity bus, then reports)."""
    run = Run(workflow_name="Platform Insights", status=RunStatus.running, meta=True)
    runs_repo.upsert(run.model_dump(by_alias=True))

    async def _go():
        rec = await run_insights(run.run_id)
        run.status = RunStatus.succeeded
        runs_repo.upsert(run.model_dump(by_alias=True))
        try:
            from ..observability import get_sink
            get_sink().record_run(run)
        except Exception:
            pass
        return rec

    asyncio.create_task(_go())
    return {"run_id": run.run_id, "stream": f"/api/v1/runs/{run.run_id}/stream"}


@router.get("/insights/reports")
def list_reports():
    return sorted(reports_repo.list(), key=lambda r: r["generated_at"], reverse=True)


@router.get("/insights/reports/{report_id}")
def get_report(report_id: str):
    r = reports_repo.get(report_id)
    if not r:
        raise HTTPException(404, "report not found")
    return r


@router.get("/insights/reports/{report_id}/download")
def download_report(report_id: str):
    r = reports_repo.get(report_id)
    if not r:
        raise HTTPException(404, "report not found")
    return FileResponse(r["docx"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"Platform_Insights_{report_id}.docx")


@router.get("/insights/findings")
def latest_findings():
    reps = sorted(reports_repo.list(), key=lambda r: r["generated_at"], reverse=True)
    return reps[0]["findings"] if reps else []
