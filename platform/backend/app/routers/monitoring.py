from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..observability import build_trace, overview
from ..schemas import Run
from ..store import runs as runs_repo

router = APIRouter(prefix="/api/v1", tags=["monitoring"])


@router.get("/metrics/overview")
def metrics_overview():
    """Aggregated platform metrics for the Monitoring dashboards (spec §8.3)."""
    return overview(runs_repo.list())


@router.get("/traces/{run_id}")
def get_trace(run_id: str):
    """Nested span tree for a single run (spec §8.2)."""
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return build_trace(r)


@router.post("/runs/{run_id}/feedback")
def add_feedback(run_id: str, body: dict):
    """Attach 👍/👎 + optional comment to a run (spec §8.2)."""
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    run = Run(**r)
    run.feedback.append({"vote": body.get("vote", "up"), "comment": body.get("comment", "")})
    runs_repo.upsert(run.model_dump(by_alias=True))
    return {"run_id": run_id, "feedback": run.feedback}
