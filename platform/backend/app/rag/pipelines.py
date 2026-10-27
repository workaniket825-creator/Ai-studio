"""Pipeline + Index entities and their config, persisted in the JSON store.
Vectors live in the vector store (pgvector or local fallback); this holds the metadata."""
from __future__ import annotations

from datetime import datetime, timezone

from ..store import make_repo
from ..schemas import _id

pipelines = make_repo("rag_pipelines", "id")
documents = make_repo("rag_documents", "id")   # per-ingested-document metadata + stats


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_CONFIG = {
    "sources": ["file_storage"],                 # where docs come from
    "processing": {                              # cleaning / OCR (Phase 2 wires OCR fully)
        "clean": True, "dehyphenate": True, "strip_boilerplate": True,
        "ocr": {"backend": "off", "endpoint_id": "", "language": "en"},   # off|local|api
        "tables": {"backend": "local"},
        "images": {"backend": "off", "endpoint_id": ""},                  # off|api (multimodal)
    },
    "chunking": {"strategy": "recursive", "size": 800, "overlap": 120, "unit": "tokens"},
    "embeddings": {"backend": "local", "endpoint_id": "", "model": "local-minilm", "dim": 384, "batch": 64},
    "index": {"metric": "cosine", "store": "auto"},   # auto = pgvector if available else local
    "retrieval": {"top_k": 5, "min_score": 0.0, "hybrid": True,
                  "rerank": {"backend": "off", "endpoint_id": ""}},
}


def create_pipeline(data: dict) -> dict:
    cfg = {**DEFAULT_CONFIG, **(data.get("config") or {})}
    p = {
        "id": _id("pipe"),
        "name": data.get("name", "Untitled pipeline"),
        "description": data.get("description", ""),
        "config": cfg,
        "status": "empty",                 # empty | ingesting | ready | error
        "stats": {"documents": 0, "chunks": 0, "tokens": 0, "bytes": 0,
                  "failed": 0, "pages_ocr": 0, "tables": 0, "last_sync": ""},
        "created_at": _now(), "updated_at": _now(),
    }
    return pipelines.upsert(p)


def update_pipeline(pid: str, patch: dict) -> dict | None:
    p = pipelines.get(pid)
    if not p:
        return None
    for k in ("name", "description"):
        if k in patch:
            p[k] = patch[k]
    if "config" in patch:
        p["config"] = {**p["config"], **patch["config"]}
    p["updated_at"] = _now()
    return pipelines.upsert(p)


def delete_pipeline(pid: str) -> bool:
    if not pipelines.get(pid):
        return False
    for d in documents.list(lambda x: x.get("pipeline_id") == pid):
        documents.delete(d["id"])
    from . import vectorstore
    vectorstore.drop(pid)
    pipelines.delete(pid)
    return True


def list_pipelines() -> list[dict]:
    return pipelines.list(lambda _: True)


def get_pipeline(pid: str) -> dict | None:
    return pipelines.get(pid)


def recompute_stats(pid: str) -> dict:
    """Aggregate per-document stats up to the pipeline for the catalog view."""
    p = pipelines.get(pid)
    if not p:
        return {}
    docs = documents.list(lambda x: x.get("pipeline_id") == pid)
    ok = [d for d in docs if d.get("status") == "indexed"]
    p["stats"] = {
        "documents": len(ok),
        "failed": len([d for d in docs if d.get("status") == "failed"]),
        "chunks": sum(d.get("chunks", 0) for d in ok),
        "tokens": sum(d.get("tokens", 0) for d in ok),
        "bytes": sum(d.get("bytes", 0) for d in ok),
        "pages_ocr": sum(d.get("pages_ocr", 0) for d in ok),
        "tables": sum(d.get("tables", 0) for d in ok),
        "images": sum(d.get("images", 0) for d in ok),
        "last_sync": _now(),
    }
    p["status"] = "ready" if ok else ("error" if docs else "empty")
    pipelines.upsert(p)
    return p["stats"]


def list_documents(pid: str) -> list[dict]:
    return documents.list(lambda x: x.get("pipeline_id") == pid)
