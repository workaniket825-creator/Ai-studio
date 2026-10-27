"""Chat conversation store (persistent chat history).

Persists chat conversations so users can revisit, search, rename, archive, and delete
them. Each conversation holds its workflow binding and the full message list. Stored in
its own JSON collection (chat_conversations) — additive, no impact on existing runs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .store import make_repo

_repo = make_repo("chat_conversations", "id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    import uuid
    return "conv_" + uuid.uuid4().hex[:12]


def list_conversations(include_archived: bool = False, q: str = "") -> list[dict]:
    rows = _repo.list()
    if not include_archived:
        rows = [r for r in rows if not r.get("archived")]
    if q:
        ql = q.lower()
        rows = [r for r in rows
                if ql in (r.get("title", "").lower())
                or any(ql in (m.get("text", "").lower()) for m in r.get("messages", []))]
    # newest first by updated_at
    rows.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    # return lightweight summaries (no full messages) for the list
    return [{"id": r["id"], "title": r["title"], "workflow_id": r.get("workflow_id"),
             "workflow_name": r.get("workflow_name", ""), "archived": r.get("archived", False),
             "created_at": r.get("created_at"), "updated_at": r.get("updated_at"),
             "message_count": len(r.get("messages", []))}
            for r in rows]


def get_conversation(cid: str) -> dict | None:
    return _repo.get(cid)


def create_conversation(workflow_id: str, workflow_name: str = "", title: str = "") -> dict:
    conv = {
        "id": _id(),
        "title": title or "New chat",
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "messages": [],
        "archived": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _repo.upsert(conv)
    return conv


def save_messages(cid: str, messages: list[dict], auto_title: bool = True) -> dict | None:
    conv = _repo.get(cid)
    if not conv:
        return None
    conv["messages"] = messages
    conv["updated_at"] = _now()
    # derive a title from the first user message if still default
    if auto_title and conv.get("title") in ("", "New chat"):
        first_user = next((m for m in messages if m.get("role") == "user" and m.get("text")), None)
        if first_user:
            conv["title"] = first_user["text"][:60] + ("…" if len(first_user["text"]) > 60 else "")
    _repo.upsert(conv)
    return conv


def rename(cid: str, title: str) -> dict | None:
    conv = _repo.get(cid)
    if not conv:
        return None
    conv["title"] = title.strip() or conv["title"]
    conv["updated_at"] = _now()
    _repo.upsert(conv)
    return conv


def set_archived(cid: str, archived: bool) -> dict | None:
    conv = _repo.get(cid)
    if not conv:
        return None
    conv["archived"] = bool(archived)
    conv["updated_at"] = _now()
    _repo.upsert(conv)
    return conv


def delete(cid: str) -> bool:
    if not _repo.get(cid):
        return False
    _repo.delete(cid)
    return True
