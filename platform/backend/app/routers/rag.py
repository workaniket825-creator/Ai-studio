"""RAG / Knowledge Pipelines API."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..rag import pipelines as P
from ..rag import ingest as I
from ..rag import chunk as C
from ..rag import vectorstore as V
from ..ontology import jobs
from ..schemas import _id

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


# ---- pipelines ----
@router.get("/pipelines")
def list_pipelines():
    return P.list_pipelines()


@router.post("/pipelines")
def create_pipeline(body: dict):
    return P.create_pipeline(body)


@router.get("/pipelines/{pid}")
def get_pipeline(pid: str):
    p = P.get_pipeline(pid)
    if not p:
        raise HTTPException(404, "pipeline not found")
    return {**p, "vector_stats": V.stats(pid)}


@router.put("/pipelines/{pid}")
def update_pipeline(pid: str, body: dict):
    p = P.update_pipeline(pid, body)
    if not p:
        raise HTTPException(404, "pipeline not found")
    return p


@router.delete("/pipelines/{pid}")
def delete_pipeline(pid: str):
    if not P.delete_pipeline(pid):
        raise HTTPException(404, "pipeline not found")
    return {"deleted": pid}


# ---- designer helpers ----
@router.get("/embedding-endpoints")
def embedding_endpoints():
    """Model Endpoints usable for embeddings/OCR/multimodal (selection dropdowns)."""
    from ..endpoints import list_endpoints
    eps = list_endpoints()
    def by(t):
        return [{"id": e["id"], "label": e.get("label", ""), "model": e.get("model", "")}
                for e in eps if e.get("type") == t]
    return {"embedding": by("embedding"), "ocr": by("ocr"),
            "multimodal": by("multimodal"), "rerank": by("rerank"),
            "has_embedding": bool(by("embedding"))}


@router.post("/preview-chunking")
def preview_chunking(body: dict):
    """Live chunking preview for the designer."""
    return C.preview(body.get("text", ""), body.get("chunking", {}))


# ---- ingestion (async job with progress + stats) ----
@router.post("/pipelines/{pid}/ingest")
async def ingest(pid: str, body: dict):
    """body: { items: [{source?, text?, path?}] } → starts a background job, returns job_id."""
    if not P.get_pipeline(pid):
        raise HTTPException(404, "pipeline not found")
    items = body.get("items") or []
    if not items:
        raise HTTPException(400, "no items to ingest")
    job_id = _id("ragjob")
    jobs.create(job_id, source=f"ingest:{pid}")
    asyncio.create_task(I.run_ingest_job(pid, items, job_id))
    return {"job_id": job_id, "status": "running", "documents": len(items)}


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return {"cancelled": jobs.cancel(job_id), "job_id": job_id}


# ---- catalog / inspector ----
@router.get("/pipelines/{pid}/documents")
def documents(pid: str):
    return P.list_documents(pid)


@router.get("/pipelines/{pid}/stats")
def stats(pid: str):
    p = P.get_pipeline(pid)
    if not p:
        raise HTTPException(404, "pipeline not found")
    return {"pipeline_stats": P.recompute_stats(pid), "vector_stats": V.stats(pid),
            "backend": V.backend_name()}


# ---- retrieval (used by Chat + agent tool + the inspector's test-query box) ----
@router.post("/pipelines/{pid}/query")
def query(pid: str, body: dict):
    return I.retrieve(pid, body.get("query", ""), top_k=int(body.get("top_k", 0)))
