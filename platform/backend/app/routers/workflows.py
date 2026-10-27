from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..factory import compile_workflow, validate_workflow
from ..schemas import WorkflowGraph
from ..store import agents as agents_repo
from ..store import workflows as workflows_repo

router = APIRouter(prefix="/api/v1", tags=["workflows"])


@router.get("/workflows")
def list_workflows():
    return workflows_repo.list()


@router.post("/workflows")
def create_workflow(wf: WorkflowGraph):
    return workflows_repo.upsert(wf.model_dump(by_alias=True))


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    wf = workflows_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    return wf


@router.patch("/workflows/{workflow_id}")
def update_workflow(workflow_id: str, patch: dict):
    wf = workflows_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    wf.update(patch)
    wf["version"] = wf.get("version", 1) + 1
    return workflows_repo.upsert(wf)


@router.post("/workflows/{workflow_id}/validate")
def validate(workflow_id: str):
    wf = workflows_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    errors = validate_workflow(WorkflowGraph(**wf))
    return {"valid": not errors, "errors": errors}


@router.post("/workflows/{workflow_id}/compile")
def compile_(workflow_id: str):
    wf = workflows_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    return {"plan": compile_workflow(WorkflowGraph(**wf))}


@router.post("/workflows/design")
def design_workflow(body: dict):
    """Workflow Designer Agent (spec §6.2): goal -> reuse-first graph.
    Deterministic (no model key needed); returns an UNSAVED graph for the canvas."""
    from ..designer import design
    goal = body.get("goal", "")
    wf = design(goal)
    return wf.model_dump(by_alias=True)


@router.post("/workflows/{workflow_id}/plan")
def plan(workflow_id: str):
    """Plan Mode (spec §7): the ordered, human-readable plan to approve before running."""
    wf = workflows_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    from ..designer import plan_steps
    return {"workflow_id": workflow_id, "steps": plan_steps(WorkflowGraph(**wf))}


@router.post("/workflows/{workflow_id}/nodes/{node_id}/materialize")
def materialize(workflow_id: str, node_id: str):
    """Create a provisional (to_be_created) node's agent into the Garden (spec §6.2)."""
    wf = workflows_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "workflow not found")
    node = next((n for n in wf["nodes"] if n["node_id"] == node_id), None)
    if not node or not node.get("provisional_card"):
        raise HTTPException(400, "node has no provisional card to materialize")
    from ..schemas import AgentCard, AgentCategory
    pc = node["provisional_card"]
    card = AgentCard(agent_name=pc.get("agent_name", "New Agent"),
                     role=pc.get("agent_name", "New Agent"),
                     category=AgentCategory.use_case,
                     description=pc.get("description", "Created from workflow design."))
    agents_repo.upsert(card.model_dump(by_alias=True))
    node["status"] = "reused"
    node["agent_ref"] = f"agent_cards/{card.agent_name}"
    node["provisional_card"] = None
    workflows_repo.upsert(wf)
    return {"materialized": card.agent_id, "node_id": node_id}
