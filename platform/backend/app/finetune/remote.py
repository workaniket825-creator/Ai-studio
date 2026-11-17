"""DSLab runtime access for fine-tuning jobs.

Job control (stage the notebook, start, status, cancel, list outputs) goes through the
runtime's DSLab MCP server (app/mcp_servers/dslab_runtime.py) via the platform's MCP client —
the same server and client agents use. Bulk file transfer (datasets in, model files out) uses
the same authenticated lab proxy directly, because multi-MB payloads do not belong in MCP
JSON-RPC messages. All functions here are blocking; callers run them in a worker thread.
"""
from __future__ import annotations

import base64
import json
import os

from .. import mcp_client, mcp_store
from ..modules.data_science_lab import agent_access
from ..modules.data_science_lab import config as dsl_cfg
from ..modules.data_science_lab import store as dsl_store
from ..modules.data_science_lab.jupyter_remote import LabClient, LabError, LabNotOpen
from . import config


class RemoteError(RuntimeError):
    pass


# ------------------------------------------------------------------ runtime selection
def resolve_runtime(requested: str = "") -> dict:
    """Pick the DSLab runtime for a job: the requested one (id or name), the configured
    default, the single runtime with agent access, or the only runtime. Raises RemoteError
    with an actionable message otherwise."""
    if not dsl_cfg.is_enabled():
        raise RemoteError("Data Science Lab is disabled. Enable it (Data Science Lab > settings) "
                          "and register a runtime first.")
    rows = [dsl_store.get_runtime(r["id"]) or r for r in dsl_store.list_runtimes()]
    if not rows:
        raise RemoteError("No DSLab runtime is registered. Add one in Data Science Lab > Runtimes.")
    names = ", ".join(f"{r.get('name')} ({r['id']})" for r in rows)
    want = (requested or "").strip() or config.get().get("default_runtime_id", "")
    if want:
        for r in rows:
            if want in (r["id"],) or want.lower() == str(r.get("name", "")).lower():
                return r
        raise RemoteError(f"DSLab runtime '{want}' not found. Available: {names}")
    enabled = [r for r in rows if r.get("agent_mcp_server")]
    if len(enabled) == 1:
        return enabled[0]
    if len(rows) == 1:
        return rows[0]
    raise RemoteError(f"Several DSLab runtimes are registered - choose one in the request "
                      f"(runtime_id) or set a default in fine-tuning settings. Available: {names}")


def ensure_server(rt: dict) -> dict:
    """The runtime's DSLab MCP server; registered on first use (no agent is created)."""
    sid = agent_access.server_id(rt["id"])
    server = mcp_store.get_server(sid)
    if not server:
        res = agent_access.enable(rt["id"], {"create_agent": False})
        server = mcp_store.get_server(sid)
        if not server:
            raise RemoteError(f"could not register the DSLab MCP server: {res.get('detail', res)}")
    if not server.get("enabled", True):
        raise RemoteError(f"the MCP server '{server.get('name')}' is disabled (MCP Servers screen)")
    return server


def runtime_mlflow_uri(rt: dict) -> str:
    return (config.get().get("remote_mlflow_uri") or rt.get("mlflow_uri")
            or config.backend_mlflow_uri() or "")


# ------------------------------------------------------------------ MCP job control
def call(server: dict, tool: str, args: dict) -> dict:
    text = mcp_client.call_tool(server, tool, args) or ""
    t = text.strip()
    if t.startswith("ERROR:"):
        raise RemoteError(t[6:].strip())
    try:
        out = json.loads(t)
    except Exception:
        raise RemoteError(f"{tool}: unexpected reply: {t[:500]}")
    if isinstance(out, dict) and out.get("error") and not out.get("ok", False) and "state" not in out:
        raise RemoteError(f"{tool}: {out['error']}")
    return out


def stage_text(server: dict, job_id: str, name: str, content: str) -> None:
    call(server, "stage_job_file", {"job_id": job_id, "name": name, "content": content,
                                    "encoding": "text"})


def start(server: dict, job_id: str, env: dict, timeout_hours: float) -> dict:
    c = config.get()
    res = call(server, "start_notebook_job", {
        "job_id": job_id, "notebook": "notebook.ipynb", "env": env,
        "timeout_hours": float(timeout_hours),
        "log_outputs_to_mlflow": bool(c["log_outputs_to_mlflow"]),
        "mlflow_max_gb": float(c["mlflow_max_gb"])})
    if not res.get("ok"):
        raise RemoteError(f"job did not start: {res.get('error') or res}")
    return res


def status(server: dict, job_id: str) -> dict:
    return call(server, "notebook_job_status", {"job_id": job_id})


def cancel(server: dict, job_id: str) -> dict:
    return call(server, "cancel_notebook_job", {"job_id": job_id})


def outputs(server: dict, job_id: str) -> dict:
    return call(server, "list_job_outputs", {"job_id": job_id})


# ------------------------------------------------------------------ bulk transfer (lab proxy)
def _lab_url(server: dict, rt: dict) -> str:
    env = server.get("env") or {}
    if env.get("DSLAB_LAB_URL"):
        return env["DSLAB_LAB_URL"]
    api = (env.get("DSLAB_API_BASE") or os.getenv("DSLAB_API_BASE")
           or f"http://127.0.0.1:{os.getenv('BACKEND_PORT', '8099')}").rstrip("/")
    return f"{api}/api/v1/dsl/runtimes/{rt['id']}/lab/"


def lab(server: dict, rt: dict, fn):
    """Run fn(LabClient); if the lab is not open, open it once and retry."""
    client = LabClient(_lab_url(server, rt))
    try:
        return fn(client)
    except LabNotOpen:
        from ..modules.data_science_lab import session as dsl_session
        r = dsl_session.open_lab(rt["id"])
        if not r.get("ok"):
            raise RemoteError(f"the DSLab lab is not open and could not be opened: {r.get('detail')}")
        return fn(client)
    except LabError as e:
        raise RemoteError(str(e))


def jobs_dir(server: dict) -> str:
    return ((server.get("env") or {}).get("DSLAB_JOBS_DIR") or "studio-jobs").strip("/")


def upload_bytes(server: dict, rt: dict, job_id: str, rel: str, data: bytes) -> str:
    target = f"{jobs_dir(server)}/{job_id}/{rel}"

    def go(c: LabClient):
        c.mkdirs(target.rsplit("/", 1)[0])
        c.put_base64(target, base64.b64encode(data).decode())
        return target
    return lab(server, rt, go)


def download(server: dict, rt: dict, job_id: str, rel: str) -> bytes:
    target = f"{jobs_dir(server)}/{job_id}/{rel}"
    return lab(server, rt, lambda c: c.read_bytes(target))
