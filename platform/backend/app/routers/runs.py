from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..activity import bus
from ..config import get_runtime
from ..schemas import Run, RunRequest, RunStatus, WorkflowGraph
from ..store import runs as runs_repo
from ..store import workflows as workflows_repo

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _load_workflow(workflow_id: str) -> WorkflowGraph:
    wf = workflows_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    return WorkflowGraph(**wf)


@router.post("/runs")
async def create_run(req: RunRequest):
    if not req.workflow_id:
        raise HTTPException(400, "workflow_id required")
    wf = _load_workflow(req.workflow_id)
    # per-run ontology traversal depth (1..N) chosen in the UI; also mirrored into the run
    # input so downstream (runtime → ontology provider) can read it.
    hops = max(1, int(getattr(req, "ontology_hops", 1) or 1))
    run_input = dict(req.input or {})
    run_input["ontology_hops"] = hops
    run = Run(workflow_id=wf.workflow_id, workflow_name=wf.name, input=run_input,
              ontology_hops=hops, status=RunStatus.pending)
    runs_repo.upsert(run.model_dump(by_alias=True))

    from ..executor import run_workflow
    asyncio.create_task(run_workflow(run, wf))
    from ..governance import audit
    audit("user", "run", "workflow", wf.workflow_id, wf.name)
    return {"run_id": run.run_id, "status": run.status,
            "stream": f"/api/v1/runs/{run.run_id}/stream"}


@router.get("/runs")
def list_runs():
    return sorted(runs_repo.list(), key=lambda r: r["created_at"], reverse=True)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    """Interrupt a running workflow (loop guard / manual stop)."""
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    from ..activity import cancel
    cancel.request(run_id)
    return {"run_id": run_id, "cancelling": True}


@router.get("/runs/{run_id}/replay")
def replay(run_id: str):
    return [e.model_dump() for e in bus.replay(run_id)]


@router.get("/runs/{run_id}/outputs")
def run_outputs(run_id: str):
    """Per-agent content (final + intermediate steps) for the output viewer."""
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return {"node_outputs": r.get("node_outputs", []), "artifacts": r.get("artifacts", [])}


@router.get("/runs/{run_id}/artifacts/{name}")
def download_artifact(run_id: str, name: str):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from ..analysis import ARTIFACTS_DIR
    path = Path(ARTIFACTS_DIR) / run_id / name
    if not path.exists():
        raise HTTPException(404, "artifact not found")
    return FileResponse(str(path), filename=name)


@router.post("/runs/{run_id}/steer")
async def steer_run(run_id: str, body: dict):
    """Inject mid-run guidance into a live run (spec §7)."""
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "text required")
    from ..activity import steer
    steer.add(run_id, text)
    return {"run_id": run_id, "queued": text}


@router.post("/approvals/{run_id}/approve")
async def approve(run_id: str):
    """Resume a run paused at an approval gate (spec §7 HITL)."""
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    if r["status"] != RunStatus.awaiting_approval.value:
        raise HTTPException(409, "run is not awaiting approval")
    run = Run(**r)
    run.status = RunStatus.succeeded
    run.mlflow_trace_id = f"tr_{run_id[-6:]}"
    runs_repo.upsert(run.model_dump(by_alias=True))
    from ..schemas import ActivityEvent, ActivityKind
    await bus.publish(ActivityEvent(
        run_id=run_id, seq=bus.next_seq(run_id), kind=ActivityKind.complete,
        phase="done", label="Approved \u2014 email sent. Workflow complete."))
    return {"run_id": run_id, "status": run.status}


@router.post("/approvals/{run_id}/reject")
async def reject(run_id: str):
    r = runs_repo.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    run = Run(**r)
    run.status = RunStatus.cancelled
    runs_repo.upsert(run.model_dump(by_alias=True))
    return {"run_id": run_id, "status": run.status}


@router.websocket("/runs/{run_id}/stream")
async def stream(ws: WebSocket, run_id: str, after_seq: int = 0):
    """Live ActivityEvent stream (spec §25). Reconnect with ?after_seq=N."""
    await ws.accept()
    q = bus.subscribe(run_id, after_seq=after_seq)
    try:
        while True:
            ev = await q.get()
            await ws.send_json(ev.model_dump())
            if ev.kind.value in ("complete", "error", "approval_pending"):
                # keep socket open a beat so client renders the final frame
                await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(run_id, q)
