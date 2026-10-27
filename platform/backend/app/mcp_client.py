"""MCP (Model Context Protocol) client for AI Studio.

The rest of the app calls tools synchronously (build_tool_defs / execute_tool are sync, and the
live runtime calls execute_tool inside its own event loop). The MCP SDK is async. So — exactly
like app/db.py does for asyncpg — we run all MCP async work on a dedicated background event loop
and bridge sync->async with run_coroutine_threadsafe. This avoids "asyncio.run() cannot be called
from a running event loop".

Tool discovery is cached per server so build_tool_defs (called at the start of every run) stays
fast and never blocks on a network round-trip unless the cache is cold or explicitly refreshed.

Transports supported (from the server's registry entry):
  - "sse"             : network, Server-Sent Events        (cross-container)
  - "streamable-http" : network, streamable HTTP           (cross-container)
  - "stdio"           : local subprocess (command + args)  (same host)

If the `mcp` SDK isn't installed, calls return an honest, non-fabricated error so the model relays
the truth (mirrors the platform's guarded-connector philosophy).
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Optional

_LOOP: Optional[asyncio.AbstractEventLoop] = None
_LOOP_THREAD: Optional[threading.Thread] = None
_LOCK = threading.RLock()

# per-server tool-list cache: server_id -> {"ts": float, "tools": [ {name, description, schema} ]}
_TOOL_CACHE: dict[str, dict] = {}
_CACHE_TTL = 300.0  # seconds


def _start_loop() -> asyncio.AbstractEventLoop:
    global _LOOP, _LOOP_THREAD
    if _LOOP and _LOOP.is_running():
        return _LOOP
    loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    t = threading.Thread(target=_run, name="mcp-eventloop", daemon=True)
    t.start()
    _LOOP, _LOOP_THREAD = loop, t
    return loop


def _run(coro) -> Any:
    """Run a coroutine on the background loop from sync code, blocking for the result."""
    loop = _start_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result()


# --------------------------------------------------------------------------- #
# Low-level session (real MCP SDK). Isolated so tests can replace it wholesale.
# --------------------------------------------------------------------------- #
class _Session:
    """Async context manager yielding an initialized MCP ClientSession for a server dict."""

    def __init__(self, server: dict):
        self.server = server
        self._cm = None
        self._session = None
        self._session_cm = None

    async def __aenter__(self):
        transport = (self.server.get("transport") or "sse").lower()
        from mcp import ClientSession  # optional dep
        if transport in ("sse",):
            from mcp.client.sse import sse_client
            self._cm = sse_client(self.server["url"])
            read, write = await self._cm.__aenter__()
        elif transport in ("streamable-http", "http", "streamable_http"):
            try:  # mcp SDK 1.x yields (read, write, get_session_id)
                from mcp.client.streamable_http import streamablehttp_client as _http_client
            except ImportError:  # mcp SDK 2.x renamed it and yields (read, write)
                from mcp.client.streamable_http import streamable_http_client as _http_client
            self._cm = _http_client(self.server["url"])
            streams = await self._cm.__aenter__()
            read, write = streams[0], streams[1]
        elif transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(
                command=self.server.get("command", "uv"),
                args=self.server.get("args", []),
                env=self.server.get("env", {}) or None,
            )
            self._cm = stdio_client(params)
            read, write = await self._cm.__aenter__()
        else:
            raise RuntimeError(f"unsupported MCP transport: {transport}")
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self._session

    async def __aexit__(self, *exc):
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(*exc)
        finally:
            if self._cm is not None:
                await self._cm.__aexit__(*exc)


async def _alist_tools(server: dict) -> list[dict]:
    async with _Session(server) as s:
        resp = await s.list_tools()
        out = []
        for t in resp.tools:
            out.append({
                "name": t.name,
                "description": t.description or "",
                "schema": (getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)   # SDK 1.x / 2.x
                           or {"type": "object", "properties": {}}),
            })
        return out


async def _acall_tool(server: dict, tool: str, args: dict) -> str:
    async with _Session(server) as s:
        result = await s.call_tool(tool, args or {})
        # concatenate text content blocks; fall back to str()
        parts = []
        for block in (result.content or []):
            text = getattr(block, "text", None)
            parts.append(text if text is not None else str(block))
        return "\n".join(parts) if parts else "(no content returned)"


# --------------------------------------------------------------------------- #
# Public sync API (what build_tool_defs / execute_tool call)
# --------------------------------------------------------------------------- #
_LAST_ERROR: dict = {}


def last_error(sid: str) -> str:
    with _LOCK:
        return _LAST_ERROR.get(sid, "")


def list_tools(server: dict, force: bool = False) -> list[dict]:
    """Return the server's tools (cached). Never raises — returns [] on failure so a cold/broken
    server doesn't break run startup. The failure reason is recorded and retrievable via
    last_error(sid) / surfaced by the /tools and /test endpoints (so empty lists aren't silent)."""
    sid = server.get("id", server.get("url", "server"))
    now = time.time()
    with _LOCK:
        cached = _TOOL_CACHE.get(sid)
        if cached and not force and (now - cached["ts"] < _CACHE_TTL):
            return cached["tools"]
    try:
        tools = _run(_alist_tools(server))
    except Exception as e:
        with _LOCK:
            _LAST_ERROR[sid] = f"{type(e).__name__}: {e}"
        return []
    with _LOCK:
        _TOOL_CACHE[sid] = {"ts": now, "tools": tools}
        _LAST_ERROR.pop(sid, None)
    return tools


def call_tool(server: dict, tool: str, args: dict) -> str:
    """Call an MCP tool synchronously. Returns text, or an honest error string (never fabricated)."""
    try:
        return _run(_acall_tool(server, tool, args))
    except ModuleNotFoundError:
        return ('{"error": "the \'mcp\' SDK is not installed on the server. '
                'Install it (pip install mcp) to make MCP tools callable."}')
    except Exception as e:
        return '{"error": "MCP tool call failed: ' + str(e).replace('"', "'") + '"}'


def test_connection(server: dict) -> dict:
    """List tools live (bypassing cache) as a connectivity check, with precise diagnostics so an
    empty list is never silent."""
    transport = (server.get("transport") or "sse").lower()
    env = server.get("env", {}) or {}

    # Pre-flight checks that give a clear reason before we even spawn the process.
    if transport == "stdio":
        import shutil
        cmd = server.get("command", "")
        if cmd and shutil.which(cmd) is None:
            return {"ok": False, "detail": f"command '{cmd}' not found on the backend host/container — "
                    f"install the MCP server package (e.g. pip install {cmd}).", "reason": "command_missing"}
        # Jupyter-style servers need a reachable Jupyter URL; empty == not linked yet.
        url_like = env.get("JUPYTER_URL") or env.get("DOCUMENT_URL") or env.get("RUNTIME_URL")
        needs_url = any(k in env for k in ("JUPYTER_URL", "DOCUMENT_URL", "RUNTIME_URL"))
        if needs_url and not url_like:
            return {"ok": False, "reason": "not_linked",
                    "detail": "not linked to a running Jupyter yet — open a DSLab lab, then link it "
                              "(POST /api/v1/mcp/jupyter/link/{runtime_id}) before listing tools."}

    note = ""
    dslab_rid = env.get("DSLAB_RUNTIME_ID")
    if dslab_rid:
        try:
            from .modules.data_science_lab import session as _dsl_session
            if not _dsl_session.get_tunnel_port(dslab_rid):
                note = ("Lab is not open right now - it will be opened automatically on the "
                        "agent's first tool call (or click Open Lab in Data Science Lab).")
        except Exception:
            pass
    try:
        tools = _run(_alist_tools(server))
        out = {"ok": True, "tool_count": len(tools), "tools": [t["name"] for t in tools][:50]}
        if note:
            out["note"] = note
        return out
    except ModuleNotFoundError:
        return {"ok": False, "detail": "the 'mcp' SDK is not installed (pip install mcp)", "reason": "sdk_missing"}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}", "reason": "connect_failed"}


def invalidate(server_id: str = "") -> None:
    with _LOCK:
        if server_id:
            _TOOL_CACHE.pop(server_id, None)
        else:
            _TOOL_CACHE.clear()
