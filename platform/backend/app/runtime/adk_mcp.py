"""Native ADK McpToolset construction — follows the official pattern at
https://adk.dev/tools-custom/mcp-tools

For an agent bound to MCP servers (registry entries), we build one `McpToolset` per server and
add it to the agent's `tools` list, exactly as the docs prescribe:
  - stdio servers           -> StdioConnectionParams(StdioServerParameters(command, args, env))
  - network (sse / http)    -> StreamableHTTPConnectionParams(url, headers) / SseConnectionParams
  - tool_filter=[...]        -> scope exposed tools when the registry entry lists them
  - toolsets are defined synchronously and closed via close_toolsets() on shutdown.

This is additive: it only runs under the ADK runtime (RUNTIME=adk) for agents that have MCP
servers bound. The live/LiteLLM runtime continues to use the generic mcp_client seam unchanged.
"""
from __future__ import annotations

_OPEN_TOOLSETS: list = []


def build_mcp_toolsets(agent_tools: list[dict]) -> list:
    """Return a list of ADK McpToolset objects for every MCP server bound to this agent.
    Empty list if the agent has no MCP tools or the ADK/MCP libs aren't importable."""
    mcp_refs = [t.get("ref") or t.get("server_id") for t in (agent_tools or [])
                if t.get("type") == "mcp" and (t.get("ref") or t.get("server_id"))]
    if not mcp_refs:
        return []

    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import (
            StdioConnectionParams,
            StreamableHTTPConnectionParams,
            SseConnectionParams,
        )
        from mcp import StdioServerParameters
    except Exception:
        # ADK/MCP not installed in this environment — the generic seam still serves MCP tools.
        return []

    from .. import mcp_store

    toolsets = []
    for sid in mcp_refs:
        srv = mcp_store.get_server(sid)
        if not srv or not srv.get("enabled"):
            continue
        transport = (srv.get("transport") or "sse").lower()
        tool_filter = srv.get("tool_filter") or None  # optional scoping (best practice)
        try:
            if transport == "stdio":
                conn = StdioConnectionParams(
                    server_params=StdioServerParameters(
                        command=srv.get("command", "uv"),
                        args=srv.get("args", []) or [],
                        env=srv.get("env", {}) or None,
                    ),
                    timeout=srv.get("timeout", 10),
                )
            elif transport in ("streamable-http", "http", "streamable_http"):
                conn = StreamableHTTPConnectionParams(
                    url=srv["url"],
                    headers=srv.get("headers", {}) or {},
                    timeout=srv.get("timeout", 5),
                    sse_read_timeout=srv.get("sse_read_timeout", 300),
                )
            else:  # sse
                conn = SseConnectionParams(
                    url=srv["url"],
                    headers=srv.get("headers", {}) or {},
                    timeout=srv.get("timeout", 5),
                )
            ts = McpToolset(connection_params=conn, tool_filter=tool_filter)
            toolsets.append(ts)
            _OPEN_TOOLSETS.append(ts)
        except Exception:
            # One bad server must not break the agent; others still load.
            continue
    return toolsets


async def close_toolsets() -> None:
    """Gracefully close any toolsets opened outside `adk web` (lifecycle best practice)."""
    for ts in list(_OPEN_TOOLSETS):
        try:
            await ts.close()
        except Exception:
            pass
    _OPEN_TOOLSETS.clear()
