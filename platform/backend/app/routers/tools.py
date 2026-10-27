from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..schemas import ToolSpec, ToolType
from ..store import tools as tools_repo

router = APIRouter(prefix="/api/v1", tags=["tools"])


@router.get("/tools")
def list_tools():
    return tools_repo.list()


@router.get("/tools/{tool_id}")
def get_tool(tool_id: str):
    t = tools_repo.get(tool_id)
    if not t:
        raise HTTPException(404, "tool not found")
    # expose a re-editable raw OpenAPI document for the UI (reconstructed from stored parts)
    sp = t.get("spec") or {}
    if t.get("type") == "openapi":
        paths: dict = {}
        for op in sp.get("operation_details", []) or []:
            method = (op.get("method") or "get").lower()
            entry = {"operationId": op.get("operationId"), "summary": op.get("summary", "")}
            params = []
            body_props = {}
            body_required = []
            for p in op.get("parameters", []) or []:
                if p.get("in") == "body":
                    body_props[p["name"]] = {"type": p.get("type", "string")}
                    if p.get("enum"):
                        body_props[p["name"]]["enum"] = p["enum"]
                    if p.get("required"):
                        body_required.append(p["name"])
                else:
                    pd = {"name": p["name"], "in": p.get("in", "query"),
                          "required": bool(p.get("required")),
                          "schema": {"type": p.get("type", "string")}}
                    if p.get("enum"):
                        pd["schema"]["enum"] = p["enum"]
                    params.append(pd)
            if params:
                entry["parameters"] = params
            if body_props:
                bsch = {"type": "object", "properties": body_props}
                if body_required:
                    bsch["required"] = body_required
                entry["requestBody"] = {"content": {"application/json": {"schema": bsch}}}
            paths.setdefault(op.get("path", "/"), {})[method] = entry
        t = {**t, "spec_document": {
            "openapi": sp.get("openapi") or "3.0.0",
            "info": {"title": sp.get("title") or t.get("name", "API")},
            "servers": sp.get("servers", []),
            "paths": paths,
        }}
    return t


@router.put("/tools/{tool_id}")
def update_tool(tool_id: str, patch: dict):
    """Edit a registered tool. For OpenAPI tools the FULL spec document can be replaced via
    `spec_document` (or `spec`), which re-parses every operation/parameter. Also supports
    name/description/auth_token/servers edits."""
    t = tools_repo.get(tool_id)
    if not t:
        raise HTTPException(404, "tool not found")
    for k in ("name", "description", "auth_ref"):
        if k in patch:
            t[k] = patch[k]
    spec = t.get("spec") or {}
    # full OpenAPI document replacement (edit any parameter, path, body, server, etc.)
    raw_doc = patch.get("spec_document", patch.get("spec"))
    if raw_doc is not None and t.get("type") == "openapi":
        doc = _parse_spec(raw_doc)
        if not isinstance(doc, dict) or "paths" not in doc:
            raise HTTPException(400, "not a valid OpenAPI document (missing 'paths')")
        operations = _extract_operations(doc)
        info = doc.get("info", {})
        spec["openapi"] = doc.get("openapi") or doc.get("swagger")
        spec["title"] = info.get("title") or t.get("name")
        spec["servers"] = doc.get("servers", [])
        spec["operation_details"] = operations
        t["operations"] = [op["operationId"] for op in operations]
        if info.get("description"):
            t["description"] = info["description"]
    # individual field edits
    for k in ("webhook_url", "auth_token", "signature", "servers"):
        if k in patch:
            spec[k] = patch[k]
    t["spec"] = spec
    saved = tools_repo.upsert(t)
    return {"tool": saved, "operations": spec.get("operation_details", [])}


@router.delete("/tools/{tool_id}")
def delete_tool(tool_id: str):
    if not tools_repo.get(tool_id):
        raise HTTPException(404, "tool not found")
    tools_repo.delete(tool_id)
    return {"deleted": tool_id}


@router.post("/tools/{tool_id}/test")
def test_tool(tool_id: str, body: dict):
    """Execute a tool directly from the UI to verify it works (spec §6b.1).
    body: { operationId?, args? } — for openapi pick an operation; for function/builtin pass args."""
    import time as _t
    t = tools_repo.get(tool_id)
    if not t:
        raise HTTPException(404, "tool not found")
    from ..tool_exec import build_tool_defs, execute_tool
    defs, registry = build_tool_defs([{"type": t["type"], "ref": tool_id, "name": t.get("name")}])
    fname = body.get("operationId")
    if not fname:
        # default to the tool's function name or first available
        fname = next(iter(registry), None)
    if fname not in registry:
        return {"ok": False, "detail": f"no callable '{fname}'. Available: {list(registry)}",
                "available": list(registry)}
    t0 = _t.time()
    try:
        result = execute_tool(registry, fname, body.get("args", {}) or {})
        return {"ok": True, "operation": fname, "result": result,
                "elapsed_ms": round((_t.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "operation": fname, "detail": str(e),
                "elapsed_ms": round((_t.time() - t0) * 1000)}


@router.post("/tools/function")
def register_function(body: dict):
    """Register a function tool.
    body: { name, description, parameters?/signature? (JSON schema), webhook_url? }
    Provide a webhook_url to make the function actually callable at run time."""
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    spec = ToolSpec(
        name=body["name"], type=ToolType.function,
        description=body.get("description", ""),
        spec={"signature": body.get("parameters") or body.get("signature", {}),
              "webhook_url": body.get("webhook_url", "")},
    )
    _lint(spec)
    return tools_repo.upsert(spec.model_dump())


@router.post("/tools/builtin")
def register_builtin(body: dict):
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    spec = ToolSpec(name=body["name"], type=ToolType.builtin,
                    description=body.get("description", ""))
    return tools_repo.upsert(spec.model_dump())


@router.post("/tools/openapi")
def register_openapi(body: dict):
    """Ingest an OpenAPI spec (JSON or YAML string, or an object) and auto-extract
    operations the agent can be granted access to (spec §11).

    body: { "name": str, "spec": <json-string|yaml-string|object>,
            "auth_token"?: str }
    """
    raw = body.get("spec")
    doc = _parse_spec(raw)
    if not isinstance(doc, dict) or "paths" not in doc:
        raise HTTPException(400, "not a valid OpenAPI document (missing 'paths')")

    operations = _extract_operations(doc)
    info = doc.get("info", {})
    spec = ToolSpec(
        name=body.get("name") or info.get("title", "API"),
        type=ToolType.openapi,
        description=info.get("description", "") or f"{len(operations)} operations",
        spec={"openapi": doc.get("openapi") or doc.get("swagger"),
              "title": info.get("title"), "servers": doc.get("servers", []),
              "operation_details": operations,               # full method/path/summary
              "auth_token": body.get("auth_token", "")},     # optional bearer for calls
        operations=[op["operationId"] for op in operations],
        auth_ref=body.get("auth_ref"),
    )
    saved = tools_repo.upsert(spec.model_dump())
    return {"tool": saved, "operations": operations}


# ------------------------------- helpers -------------------------------
def _parse_spec(raw):
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise HTTPException(400, "spec must be a string or object")
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        try:
            import yaml
            return yaml.safe_load(raw)
        except Exception as e:
            raise HTTPException(400, f"could not parse spec as JSON or YAML: {e}")


def _resolve_ref(doc: dict, node):
    """Resolve a local $ref (#/components/...) one level; return node unchanged otherwise."""
    if isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/"):
            cur = doc
            for part in ref[2:].split("/"):
                cur = (cur or {}).get(part, {})
            return cur or {}
    return node or {}


def _extract_operations(doc: dict) -> list[dict]:
    """Extract operations WITH their real parameters, so the model gets a flat, named,
    typed schema per operation (ADK principle: simple signatures call reliably)."""
    ops = []
    for path, methods in (doc.get("paths") or {}).items():
        shared = (methods or {}).get("parameters", []) or []
        for method, meta in (methods or {}).items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            meta = meta or {}
            params = []
            # path + query + header params (OpenAPI 3 + Swagger 2)
            for p in list(shared) + (meta.get("parameters", []) or []):
                p = _resolve_ref(doc, p)
                if not isinstance(p, dict) or "name" not in p:
                    continue
                loc = p.get("in", "query")
                if loc not in ("path", "query"):
                    continue  # skip header/cookie for auto-calling simplicity
                sch = _resolve_ref(doc, p.get("schema", {})) or {}
                params.append({
                    "name": p["name"], "in": loc,
                    "type": sch.get("type", "string"),
                    "description": p.get("description", "") or sch.get("description", ""),
                    "required": bool(p.get("required", loc == "path")),
                    "enum": sch.get("enum"),
                })
            # request body: flatten top-level properties (JSON)
            body_props = []
            rb = _resolve_ref(doc, meta.get("requestBody", {})) or {}
            content = (rb.get("content") or {}).get("application/json", {})
            bsch = _resolve_ref(doc, content.get("schema", {})) or {}
            required_body = set(bsch.get("required", []) or [])
            for pname, pdef in (bsch.get("properties", {}) or {}).items():
                pdef = _resolve_ref(doc, pdef)
                body_props.append({
                    "name": pname, "in": "body",
                    "type": pdef.get("type", "string"),
                    "description": pdef.get("description", ""),
                    "required": pname in required_body,
                    "enum": pdef.get("enum"),
                })
            ops.append({
                "operationId": meta.get("operationId") or f"{method}_{path}",
                "method": method.upper(),
                "path": path,
                "summary": meta.get("summary") or meta.get("description", ""),
                "parameters": params + body_props,   # flat, named, typed
            })
    return ops


def _lint(spec: ToolSpec) -> None:
    """Tool-design linting (spec §19): flag weak descriptions / likely overlap."""
    spec.lint = {
        "weak_description": len(spec.description) < 12,
        "no_operations": spec.type == ToolType.openapi and not spec.operations,
    }
