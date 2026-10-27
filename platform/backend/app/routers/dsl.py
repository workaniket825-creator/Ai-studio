"""Data Science Lab router (spec §5, §6) — own route tree /api/v1/dsl/*.

Behind the feature flag: when off, `/dsl/config` still answers (so the UI can show the
disabled state) but all action endpoints refuse. No existing route is touched.
"""
from __future__ import annotations

import os

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse

import asyncio
import httpx
import websockets

from ..modules.data_science_lab import config as dsl_cfg
from ..modules.data_science_lab import store as dsl_store
from ..modules.data_science_lab import session as dsl_session
from ..modules.data_science_lab.blueprints import list_blueprints

router = APIRouter(prefix="/api/v1/dsl", tags=["data-science-lab"])


def _require_enabled(tenant: str = "default"):
    if not dsl_cfg.is_enabled(tenant):
        raise HTTPException(403, "Data Science Lab is disabled (feature flag off).")


# ------------------------------- feature flag (§1) -------------------------------
@router.get("/config")
def get_config():
    return dsl_cfg.get_config()


@router.put("/config")
def set_config(body: dict):
    if "enabled" in body:
        dsl_cfg.set_enabled(bool(body["enabled"]))
    if "tenant" in body and "tenant_enabled" in body:
        dsl_cfg.set_tenant_enabled(body["tenant"], bool(body["tenant_enabled"]))
    return dsl_cfg.get_config()


@router.get("/status")
def status():
    return {"enabled": dsl_cfg.is_enabled(),
            "mlflow_uri": os.getenv("MLFLOW_TRACKING_URI", ""),
            "runtimes": len(dsl_store.list_runtimes()),
            "templates": len(dsl_store.list_templates())}


# ------------------------------- runtimes / the feed (§5.1, §10.1) -------------------------------
@router.get("/runtimes")
def list_runtimes(tenant: str = "default"):
    return dsl_store.list_runtimes(tenant)


@router.post("/runtimes")
def create_runtime(body: dict):
    _require_enabled(body.get("tenant_id", "default"))
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    return dsl_store.create_runtime(body)


@router.get("/runtimes/{rid}")
def get_runtime(rid: str):
    r = dsl_store.get_runtime(rid)
    if not r:
        raise HTTPException(404, "runtime not found")
    return dsl_store.public_view(r)


@router.put("/runtimes/{rid}")
def update_runtime(rid: str, patch: dict):
    r = dsl_store.update_runtime(rid, patch)
    if not r:
        raise HTTPException(404, "runtime not found")
    return dsl_store.public_view(r)


@router.delete("/runtimes/{rid}")
def delete_runtime(rid: str):
    dsl_session.close_lab(rid)
    try:  # remove this runtime's agent MCP server too
        from ..modules.data_science_lab import agent_access
        agent_access.revoke(rid)
    except Exception:
        pass
    if not dsl_store.delete_runtime(rid):
        raise HTTPException(404, "runtime not found")
    return {"deleted": rid}


@router.post("/runtimes/{rid}/ssh-key")
def upload_ssh_key(rid: str, body: dict):
    """Upload a private key (.pem) for an SSH runtime. Stored 0600 on the backend host and
    referenced as the runtime's auth_secret_ref — no manual ~/.ssh placement needed.
    body: { key_pem: str, passphrase?: str }"""
    import os
    from ..store import DATA_DIR
    rt = dsl_store.get_runtime(rid)
    if not rt:
        raise HTTPException(404, "runtime not found")
    pem = (body.get("key_pem") or "").strip()
    if not pem or "PRIVATE KEY" not in pem:
        raise HTTPException(400, "provide a valid PEM private key")
    keydir = DATA_DIR / "dslab_keys"
    keydir.mkdir(exist_ok=True)
    path = keydir / f"{rid}.pem"
    path.write_text(pem + ("\n" if not pem.endswith("\n") else ""))
    os.chmod(path, 0o600)
    patch = {"auth_secret_ref": str(path), "has_uploaded_key": True}
    if body.get("passphrase"):
        patch["ssh_passphrase"] = body["passphrase"]
    dsl_store.update_runtime(rid, patch)
    return {"ok": True, "auth_secret_ref": str(path), "detail": "key stored (0600) and bound to runtime"}


# ------------------------------- lifecycle & session (§6.2, §6.3, §11.4) -------------------------------
@router.post("/runtimes/{rid}/test")
def test_connection(rid: str):
    _require_enabled()
    return dsl_session.test_connection(rid)


@router.post("/runtimes/{rid}/start")
def start(rid: str):
    _require_enabled()
    return dsl_session.start(rid)


@router.post("/runtimes/{rid}/stop")
def stop(rid: str, body: dict | None = None):
    _require_enabled()
    verify = True if not body else bool(body.get("verify_backup", True))
    return dsl_session.stop(rid, verify_backup=verify)


@router.post("/runtimes/{rid}/open")
def open_lab(rid: str):
    _require_enabled()
    return dsl_session.open_lab(rid)


_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _proxy_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _HOP_HEADERS
    }


@router.api_route(
    "/runtimes/{rid}/lab/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_lab_http(rid: str, path: str, request: Request):
    _require_enabled()
    local_port = dsl_session.get_tunnel_port(rid)
    if not local_port:
        raise HTTPException(
            404, "No active SSH lab. Return to Runtimes and click Open Lab."
        )

    base_path = f"/api/v1/dsl/runtimes/{rid}/lab/"
    upstream = f"http://127.0.0.1:{local_port}{base_path}{path}"
    if request.url.query:
        upstream += "?" + request.url.query

    headers = {k: v for k, v in _proxy_headers(request.headers).items()
               if k.lower() != "authorization"}
    lab_token = dsl_session.get_lab_token(rid)
    if lab_token:  # authenticate to Jupyter server-side (passes its XSRF check; token never leaves)
        headers["authorization"] = f"token {lab_token}"
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-host"] = request.headers.get("host", "")

    client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    try:
        response = await client.send(
            client.build_request(
                request.method,
                upstream,
                headers=headers,
                content=await request.body(),
            ),
            stream=True,
        )
    except Exception as exc:
        await client.aclose()
        raise HTTPException(502, "Jupyter tunnel is unavailable") from exc

    response_headers = _proxy_headers(response.headers)

    async def response_body():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        response_body(),
        status_code=response.status_code,
        headers=response_headers,
        media_type=None,
    )


@router.websocket("/runtimes/{rid}/lab/{path:path}")
async def proxy_lab_websocket(
    websocket: WebSocket, rid: str, path: str
):
    local_port = dsl_session.get_tunnel_port(rid)
    if not local_port:
        await websocket.close(code=4404)
        return

    base_path = f"/api/v1/dsl/runtimes/{rid}/lab/"
    upstream = f"ws://127.0.0.1:{local_port}{base_path}{path}"
    if websocket.url.query:
        upstream += "?" + websocket.url.query

    extra_headers = {}
    lab_token = dsl_session.get_lab_token(rid)
    if lab_token:
        extra_headers["authorization"] = f"token {lab_token}"
    cookie = websocket.headers.get("cookie")
    if cookie:
        extra_headers["cookie"] = cookie

    requested_protocols = websocket.scope.get("subprotocols", [])

    # websockets >=14 renamed extra_headers -> additional_headers on the top-level connect().
    # Pick the kwarg the installed version actually accepts so a version drift can't break this.
    import inspect as _inspect
    _hdr_kw = ("additional_headers"
               if "additional_headers" in _inspect.signature(websockets.connect).parameters
               else "extra_headers")

    try:
        async with websockets.connect(
            upstream,
            origin=None,
            subprotocols=requested_protocols or None,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
            **{_hdr_kw: extra_headers},
        ) as remote:
            await websocket.accept(subprotocol=remote.subprotocol)

            async def browser_to_jupyter():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        await remote.send(message["bytes"])
                    elif message.get("text") is not None:
                        await remote.send(message["text"])

            async def jupyter_to_browser():
                async for message in remote:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = {
                asyncio.create_task(browser_to_jupyter()),
                asyncio.create_task(jupyter_to_browser()),
            }
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import logging

        logging.getLogger("dslab.websocket").exception(
            "Jupyter WebSocket failed for runtime %s: %s",
            rid,
            exc,
        )

        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@router.delete("/runtimes/{rid}/lab")
def close_lab(rid: str):
    _require_enabled()
    return {"ok": True, "closed": dsl_session.close_lab(rid)}


@router.get("/runtimes/{rid}/metrics")
def gpu_metrics(rid: str):
    _require_enabled()
    return dsl_session.gpu_metrics(rid)


@router.post("/runtimes/{rid}/headless")
def headless_run(rid: str, body: dict):
    _require_enabled()
    if not body.get("notebook"):
        raise HTTPException(400, "notebook is required")
    return dsl_session.headless_run(rid, body["notebook"], body.get("params", {}))


@router.post("/runtimes/{rid}/multiuser")
def spawn_multiuser(rid: str):
    _require_enabled()
    return dsl_session.spawn_multiuser(rid)


# ------------------------------- template library (§5.3, §8, §10.2) -------------------------------
@router.get("/templates")
def list_templates():
    return dsl_store.list_templates()


@router.post("/templates")
def create_template(body: dict):
    _require_enabled()
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    return dsl_store.create_template(body)


@router.delete("/templates/{tid}")
def delete_template(tid: str):
    if not dsl_store.delete_template(tid):
        raise HTTPException(404, "template not found")
    return {"deleted": tid}


@router.post("/templates/{tid}/version")
def bump_version(tid: str, body: dict):
    _require_enabled()
    if not body.get("version"):
        raise HTTPException(400, "version is required (semver)")
    t = dsl_store.bump_template_version(tid, body["version"], body.get("changelog", ""))
    if not t:
        raise HTTPException(404, "template not found")
    return t


@router.post("/templates/{tid}/ci")
def run_ci(tid: str, body: dict):
    _require_enabled()
    if not body.get("runtime_id"):
        raise HTTPException(400, "runtime_id is required to run the smoke test")
    return dsl_session.run_ci_smoke(tid, body["runtime_id"])


# ------------------------------- blueprints (§5.4, §9) -------------------------------
@router.get("/blueprints")
def blueprints():
    return list_blueprints()


# ------------------------------- experiments & models (§5.5, reuse MLflow) -------------------------------
@router.get("/mlflow")
def mlflow_link():
    uri = os.getenv("MLFLOW_TRACKING_URI", "")
    return {"tracking_uri": uri,
            "experiments_url": (uri.rstrip("/") + "/#/experiments") if uri else "",
            "models_url": (uri.rstrip("/") + "/#/models") if uri else "",
            "configured": bool(uri)}


# ------------------------------- model registry (reuse MLflow registry) -------------------------------
@router.get("/registry/models")
def registry_models():
    from ..modules.data_science_lab import registry as reg
    return {"source": reg.source(), "models": reg.list_models()}


@router.post("/registry/models")
def registry_register(body: dict):
    _require_enabled()
    from ..modules.data_science_lab import registry as reg
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    return reg.register_model(body["name"], body.get("model_uri", ""),
                              body.get("description", ""), body.get("run_id", ""))


@router.get("/registry/models/{name}")
def registry_get(name: str):
    from ..modules.data_science_lab import registry as reg
    m = reg.get_model(name)
    if not m:
        raise HTTPException(404, "model not found")
    return m


@router.post("/registry/models/{name}/stage")
def registry_stage(name: str, body: dict):
    _require_enabled()
    from ..modules.data_science_lab import registry as reg
    try:
        return reg.transition_stage(name, str(body.get("version", "")), body.get("stage", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/registry/models/{name}/invoke")
def registry_invoke(name: str, body: dict):
    _require_enabled()
    from ..modules.data_science_lab import registry as reg
    return reg.invoke(name, body.get("inputs"), body.get("serving_url", ""))


@router.delete("/registry/models/{name}")
def registry_delete(name: str):
    from ..modules.data_science_lab import registry as reg
    if not reg.delete_model(name):
        raise HTTPException(404, "model not found")
    return {"deleted": name}


# ------------------------------- agent access (DSLab runtime MCP server) -------------------------------
@router.post("/runtimes/{rid}/agent-access")
def enable_agent_access(rid: str, body: dict | None = None):
    """Register this runtime's built-in MCP server (code execution tools) and, by default, create a
    'DSLab Code Runner' agent + workflow bound to it. body: {create_agent?: bool, endpoint_id?: str,
    agent_ids?: [agent ids to also bind]}"""
    _require_enabled()
    from ..modules.data_science_lab import agent_access
    res = agent_access.enable(rid, body or {})
    if res.get("error") == "not_found":
        raise HTTPException(404, "runtime not found")
    return res


@router.delete("/runtimes/{rid}/agent-access")
def disable_agent_access(rid: str):
    from ..modules.data_science_lab import agent_access
    return {"ok": agent_access.revoke(rid)}
