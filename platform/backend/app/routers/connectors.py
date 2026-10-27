from __future__ import annotations

from fastapi import APIRouter

from ..connectors import list_connectors, set_connector, enabled_connectors

router = APIRouter(prefix="/api/v1", tags=["connectors"])


@router.get("/connectors")
def connectors():
    return list_connectors()


@router.get("/connectors/enabled")
def connectors_enabled():
    return enabled_connectors()


@router.post("/connectors/{cid}/toggle")
def toggle(cid: str, body: dict):
    return set_connector(cid, enabled=body.get("enabled", True), config=body.get("config"))
