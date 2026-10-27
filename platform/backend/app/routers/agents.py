from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..activity import bus
from ..schemas import (ActivityEvent, ActivityKind, AgentCard, Run, RunStatus,
                       WorkflowEdge, WorkflowGraph, WorkflowNode)
from ..store import agents as agents_repo
from ..store import runs as runs_repo

router = APIRouter(prefix="/api/v1", tags=["agents"])


# ------------------------------- agents -------------------------------
@router.get("/agents")
def list_agents(q: str | None = None, category: str | None = None):
    def pred(a):
        ok = True
        if category:
            ok = ok and a.get("category") == category
        if q:
            hay = f"{a.get('agent_name','')} {a.get('role','')} {a.get('description','')}".lower()
            ok = ok and q.lower() in hay
        return ok
    return agents_repo.list(pred)


@router.post("/agents")
def create_agent(card: AgentCard):
    saved = agents_repo.upsert(card.model_dump(by_alias=True))
    from ..governance import audit
    audit("user", "create", "agent", saved["agent_id"], saved["agent_name"])
    return saved


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    a = agents_repo.get(agent_id)
    if not a:
        raise HTTPException(404, "agent not found")
    return a


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: str, patch: dict):
    a = agents_repo.get(agent_id)
    if not a:
        raise HTTPException(404, "agent not found")
    a.update(patch)
    a["version"] = a.get("version", 1) + 1   # editing forks a new version
    return agents_repo.upsert(a)


@router.post("/agents/{agent_id}/clone")
def clone_agent(agent_id: str):
    a = agents_repo.get(agent_id)
    if not a:
        raise HTTPException(404, "agent not found")
    src = {k: v for k, v in a.items()
           if k not in ("agent_id", "created_at", "updated_at")}
    src["agent_name"] = a["agent_name"] + " (copy)"
    src["version"] = 1
    src["category"] = "use_case"
    card = AgentCard(**src)
    return agents_repo.upsert(card.model_dump(by_alias=True))


@router.post("/agents/{agent_id}/deprecate")
def deprecate_agent(agent_id: str):
    a = agents_repo.get(agent_id)
    if not a:
        raise HTTPException(404, "agent not found")
    a["status"] = "deprecated"
    return agents_repo.upsert(a)


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    if not agents_repo.delete(agent_id):
        raise HTTPException(404, "agent not found")
    return {"deleted": agent_id}


@router.post("/agents/{agent_id}/test")
async def test_agent(agent_id: str, body: dict | None = None):
    """Ephemeral single-agent run in a sandbox; streams to the activity bus (spec §4.2)."""
    a = agents_repo.get(agent_id)
    if not a:
        raise HTTPException(404, "agent not found")
    wf = WorkflowGraph(
        name=f"Test: {a['agent_name']}",
        nodes=[WorkflowNode(node_id="n1", agent_ref=f"agent_cards/{a['agent_name']}",
                            output_key=a.get("io_contract", {}).get("output_key", "result"))],
        edges=[],
    )
    raw = (body or {}).get("input", {})
    inp = raw if isinstance(raw, dict) else {"input": raw}
    run = Run(agent_id=agent_id, workflow_name=wf.name, input=inp,
              status=RunStatus.pending)
    runs_repo.upsert(run.model_dump(by_alias=True))
    from ..executor import run_workflow
    asyncio.create_task(run_workflow(run, wf))
    return {"run_id": run.run_id, "stream": f"/api/v1/runs/{run.run_id}/stream"}
