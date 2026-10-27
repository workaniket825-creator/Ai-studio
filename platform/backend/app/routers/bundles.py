from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas import AgentCard, AgentCategory, Bundle
from ..store import agents as agents_repo
from ..store import bundles as bundles_repo

router = APIRouter(prefix="/api/v1", tags=["bundles"])


@router.get("/bundles")
def list_bundles():
    return bundles_repo.list()


@router.get("/bundles/{bundle_id}")
def get_bundle(bundle_id: str):
    b = bundles_repo.get(bundle_id)
    if not b:
        raise HTTPException(404, "bundle not found")
    return b


@router.post("/bundles")
def create_bundle(b: Bundle):
    return bundles_repo.upsert(b.model_dump())


@router.post("/bundles/{bundle_id}/install")
def install_bundle(bundle_id: str):
    """Install a pack: create its agent templates into the Garden (spec §19)."""
    b = bundles_repo.get(bundle_id)
    if not b:
        raise HTTPException(404, "bundle not found")
    created = []
    for tmpl in b.get("agents", []):
        existing = agents_repo.list(lambda a: a["agent_name"] == tmpl.get("agent_name"))
        if existing:
            continue  # reuse-first: don't duplicate
        card = AgentCard(agent_name=tmpl["agent_name"], role=tmpl.get("role", tmpl["agent_name"]),
                         description=tmpl.get("description", ""), category=AgentCategory.use_case,
                         tags=[b.get("category", "bundle")])
        agents_repo.upsert(card.model_dump(by_alias=True))
        created.append(card.agent_name)
    b["installs"] = b.get("installs", 0) + 1
    bundles_repo.upsert(b)
    return {"installed": bundle_id, "agents_created": created}
