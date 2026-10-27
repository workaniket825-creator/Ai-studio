from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..endpoints import (add_endpoint, delete_endpoint, list_endpoints, test_endpoint)

router = APIRouter(prefix="/api/v1", tags=["model-endpoints"])


@router.get("/model-endpoints")
def list_eps():
    return list_endpoints()


@router.post("/model-endpoints")
def create_ep(body: dict):
    for req in ("provider", "model"):
        if not body.get(req):
            raise HTTPException(400, f"{req} is required")
    return add_endpoint(body)


@router.delete("/model-endpoints/{eid}")
def delete_ep(eid: str):
    if not delete_endpoint(eid):
        raise HTTPException(404, "endpoint not found")
    return {"deleted": eid}


@router.post("/model-endpoints/{eid}/test")
def test_ep(eid: str):
    return test_endpoint(eid)
