from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import chat_store

router = APIRouter(prefix="/api/v1/chat", tags=["chat-history"])


@router.get("/conversations")
def list_conversations(archived: bool = False, q: str = ""):
    return chat_store.list_conversations(include_archived=archived, q=q)


@router.post("/conversations")
def create_conversation(body: dict):
    if not body.get("workflow_id"):
        raise HTTPException(400, "workflow_id is required")
    return chat_store.create_conversation(body["workflow_id"], body.get("workflow_name", ""),
                                          body.get("title", ""))


@router.get("/conversations/{cid}")
def get_conversation(cid: str):
    conv = chat_store.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return conv


@router.put("/conversations/{cid}/messages")
def save_messages(cid: str, body: dict):
    conv = chat_store.save_messages(cid, body.get("messages", []))
    if not conv:
        raise HTTPException(404, "conversation not found")
    return {"id": conv["id"], "title": conv["title"], "updated_at": conv["updated_at"]}


@router.put("/conversations/{cid}/rename")
def rename(cid: str, body: dict):
    conv = chat_store.rename(cid, body.get("title", ""))
    if not conv:
        raise HTTPException(404, "conversation not found")
    return {"id": conv["id"], "title": conv["title"]}


@router.put("/conversations/{cid}/archive")
def archive(cid: str, body: dict):
    conv = chat_store.set_archived(cid, bool(body.get("archived", True)))
    if not conv:
        raise HTTPException(404, "conversation not found")
    return {"id": conv["id"], "archived": conv["archived"]}


@router.delete("/conversations/{cid}")
def delete(cid: str):
    if not chat_store.delete(cid):
        raise HTTPException(404, "conversation not found")
    return {"deleted": cid}


@router.post("/compress")
def compress_context(body: dict):
    """Compress a conversation transcript for context-window savings.
    body: { turns: [{role, text}] }. Returns {applied, summary, recent_turns, tokens_before,
    tokens_after, saved_pct, method, compressed_count}. Respects the global compression flag —
    when off or under threshold, applied=False and the caller uses the transcript as-is."""
    from ..compression import compress
    return compress(body.get("turns") or [])


@router.get("/compression-config")
def compression_config():
    """Expose the compression flag + tunables to the UI (so it knows whether to show the meter)."""
    from ..governance import get_settings
    return get_settings().get("compression", {})
