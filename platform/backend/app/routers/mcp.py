"""MCP server registry API: register servers, test connectivity, list their tools."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import mcp_store, mcp_client

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@router.get("/servers")
def list_servers():
    return mcp_store.list_servers()


@router.post("/servers")
def add_server(body: dict):
    if not body.get("name"):
        raise HTTPException(400, "name required")
    return mcp_store.add_server(body)


@router.put("/servers/{sid}")
def update_server(sid: str, body: dict):
    s = mcp_store.update_server(sid, body)
    if not s:
        raise HTTPException(404, "server not found")
    return s


@router.delete("/servers/{sid}")
def delete_server(sid: str):
    if not mcp_store.delete_server(sid):
        raise HTTPException(404, "server not found")
    return {"deleted": sid}


@router.post("/servers/{sid}/test")
def test_server(sid: str):
    s = mcp_store.get_server(sid)
    if not s:
        raise HTTPException(404, "server not found")
    return mcp_client.test_connection(s)


@router.get("/servers/{sid}/tools")
def list_server_tools(sid: str, refresh: bool = False):
    s = mcp_store.get_server(sid)
    if not s:
        raise HTTPException(404, "server not found")
    tools = mcp_client.list_tools(s, force=refresh)
    out = {"tools": tools}
    if not tools:
        # don't return a silent empty list — tell the UI why (not linked / command missing / etc.)
        diag = mcp_client.test_connection(s)
        out["error"] = diag.get("detail", "") or mcp_client.last_error(sid)
        out["reason"] = diag.get("reason", "")
    return out


@router.post("/jupyter/link/{rid}")
def link_jupyter(rid: str):
    """Point the Jupyter MCP server at a DSLab runtime's open JupyterLab so agents drive
    notebooks inside that DSLab environment (fills jupyter_url/token, then connects)."""
    from ..seed import link_jupyter_mcp_to_runtime
    return link_jupyter_mcp_to_runtime(rid)


@router.post("/servers/{sid}/connect")
def connect_server(sid: str, body: dict | None = None):
    """Apply a Jupyter target to the jupyter-mcp service (Option Y). Saves the UI values to the
    registry AND writes them to infra/.env so the service picks them up on the next quick refresh:
        docker compose up -d jupyter-mcp
    Returns that one-line apply command. No backend CLI, no rebuild, no code change."""
    s = mcp_store.get_server(sid)
    if not s:
        raise HTTPException(404, "server not found")
    body = body or {}
    patch = {}
    if "jupyter_url" in body:
        patch["jupyter_url"] = body["jupyter_url"]
    if "jupyter_token" in body:
        patch["jupyter_token"] = body["jupyter_token"]
    if patch:
        s = mcp_store.update_server(sid, patch)

    jurl = (s.get("jupyter_url") or "").strip()
    jtok = (s.get("jupyter_token") or "")  # empty is valid (Option 3, no auth)
    if not jurl:
        raise HTTPException(400, "set Jupyter URL first (e.g. http://host.docker.internal:8888)")

    written = _write_env_file({"JUPYTER_URL": jurl, "JUPYTER_TOKEN": jtok})
    mcp_client.invalidate(sid)   # drop any cached (stale) tool list
    return {
        "ok": True,
        "detail": (f"Saved Jupyter target ({jurl}). The jupyter-mcp container reads it only at "
                   f"start-up: run the command below once on the AI Studio host (in platform/infra)."),
        "env_written": written,
        "apply_command": "docker compose up -d jupyter-mcp",
        "token_set": bool(jtok),
    }


def _write_env_file(values: dict) -> bool:
    """Upsert KEY=VALUE pairs into infra/.env (create if missing). Best-effort: returns whether
    it wrote. The file is read by docker compose for the jupyter-mcp service's environment."""
    import os
    # backend runs at /app; infra/.env is mounted/located relative to the compose project. Try a
    # few likely locations so this works in-container and in local dev.
    # COMPOSE_ENV_FILE (set in compose) always wins; otherwise fall back to likely locations.
    path = os.getenv("COMPOSE_ENV_FILE", "").strip()
    if not path:
        candidates = ["/app/infra/.env", "/infra/.env",
                      os.path.join(os.path.dirname(__file__), "..", "..", "..", "infra", ".env")]
        path = next((p for p in candidates if os.path.isdir(os.path.dirname(p))), candidates[-1])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = {}
        if os.path.isfile(path):
            for line in open(path):
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.rstrip("\n")
        existing.update({k: v for k, v in values.items()})
        with open(path, "w") as f:
            for k, v in existing.items():
                f.write(f"{k}={v}\n")
        return True
    except Exception:
        return False
