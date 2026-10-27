"""Registry of MCP servers the platform can connect to (e.g. MLflow's MCP server).

Backed by the same repository factory as everything else, so it follows STORE_BACKEND
(json | postgres) automatically. A server entry:
  { id, name, transport: sse|streamable-http|stdio, url?, command?, args?, env?, enabled }
"""
from __future__ import annotations

from .schemas import _id
from .store import make_repo

_repo = make_repo("mcp_servers", "id")


def list_servers() -> list[dict]:
    return _repo.list()


def enabled_servers() -> list[dict]:
    return [s for s in _repo.list() if s.get("enabled")]


def get_server(sid: str) -> dict | None:
    return _repo.get(sid)


def add_server(data: dict) -> dict:
    server = {
        "id": data.get("id") or _id("mcp"),
        "name": data.get("name", "MCP server"),
        "transport": (data.get("transport") or "sse").lower(),
        "url": data.get("url", ""),
        "command": data.get("command", ""),
        "args": data.get("args", []),
        "env": data.get("env", {}),
        "headers": data.get("headers", {}),          # for network transports (auth etc.)
        "tool_filter": data.get("tool_filter", []),  # scope exposed tools (ADK best practice)
        "timeout": data.get("timeout", 10),
        # Jupyter target — set from the UI, applied at runtime via `connect` (no rebuild/restart).
        "jupyter_url": data.get("jupyter_url", ""),
        "jupyter_token": data.get("jupyter_token", ""),
        "mcp_server_url": data.get("mcp_server_url", ""),  # the jupyter-mcp admin URL for `connect`
        "enabled": bool(data.get("enabled", True)),
    }
    _repo.upsert(server)
    return server


def update_server(sid: str, patch: dict) -> dict | None:
    s = _repo.get(sid)
    if not s:
        return None
    allowed = {"name", "transport", "url", "command", "args", "env", "enabled",
               "headers", "tool_filter", "timeout",
               "jupyter_url", "jupyter_token", "mcp_server_url"}
    s.update({k: v for k, v in patch.items() if k in allowed})
    _repo.upsert(s)
    from . import mcp_client
    mcp_client.invalidate(sid)      # config changed → drop cached tool list
    return s


def delete_server(sid: str) -> bool:
    from . import mcp_client
    mcp_client.invalidate(sid)
    return _repo.delete(sid)
