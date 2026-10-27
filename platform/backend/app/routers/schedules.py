from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..config import get_runtime
from ..schemas import Run, RunStatus, Schedule, WorkflowGraph
from ..store import runs as runs_repo
from ..store import schedules as sched_repo
from ..store import workflows as workflows_repo

router = APIRouter(prefix="/api/v1", tags=["schedules"])


def _now():
    return datetime.now(timezone.utc)


@router.get("/schedules")
def list_schedules():
    return sched_repo.list()


@router.post("/schedules")
def create_schedule(s: Schedule):
    wf = workflows_repo.get(s.workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    s.workflow_name = wf["name"]
    s.next_run = (_now() + timedelta(seconds=s.interval_seconds)).isoformat()
    return sched_repo.upsert(s.model_dump())


@router.patch("/schedules/{sid}")
def toggle_schedule(sid: str, body: dict):
    s = sched_repo.get(sid)
    if not s:
        raise HTTPException(404, "schedule not found")
    s.update(body)
    return sched_repo.upsert(s)


@router.delete("/schedules/{sid}")
def delete_schedule(sid: str):
    if not sched_repo.delete(sid):
        raise HTTPException(404, "schedule not found")
    return {"deleted": sid}


@router.post("/schedules/{sid}/trigger")
async def trigger_now(sid: str):
    s = sched_repo.get(sid)
    if not s:
        raise HTTPException(404, "schedule not found")
    rid = await _fire(s)
    return {"triggered": sid, "run_id": rid}


# ------------------------- background scheduler -------------------------
async def _fire(s: dict) -> str:
    wf = workflows_repo.get(s["workflow_id"])
    if not wf:
        return ""
    run = Run(workflow_id=wf["workflow_id"], workflow_name=wf["name"],
              input=s.get("input", {}), status=RunStatus.pending)
    runs_repo.upsert(run.model_dump(by_alias=True))
    from ..executor import run_workflow
    asyncio.create_task(run_workflow(run, WorkflowGraph(**wf)))
    s["last_run"] = _now().isoformat()
    s["last_status"] = "triggered"
    s["next_run"] = (_now() + timedelta(seconds=s.get("interval_seconds", 300))).isoformat()
    sched_repo.upsert(s)
    return run.run_id


async def scheduler_loop():
    """Checks enabled interval schedules every few seconds and fires due ones."""
    while True:
        try:
            now = _now()
            for s in sched_repo.list(lambda x: x.get("enabled") and x.get("trigger") == "interval"):
                nxt = s.get("next_run")
                if nxt and datetime.fromisoformat(nxt) <= now:
                    await _fire(s)
        except Exception:
            pass
        await asyncio.sleep(5)
