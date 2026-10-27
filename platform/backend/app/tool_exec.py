"""Tool execution layer — the 'call' side of the tool registry.

Turns an agent's attached ToolSpecs into OpenAI-style tool definitions the model
can call, and executes those calls for real:

- openapi  -> real HTTP request to the API's server + operation path
- function -> POST args to the tool's configured webhook URL (if provided),
              otherwise return a clear 'no server-side implementation' result
- builtin  -> a small set of safe built-ins (current_time, calculator)

All executors are defensive: any failure returns a JSON-serialisable error string
rather than raising, so a tool call never crashes a run.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

from .store import tools as tools_repo


def _safe_name(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in (name or "tool"))[:60]


def _is_connector(ref: str) -> bool:
    """True if ref names a connector in the catalog (vs a tools_repo id)."""
    try:
        from . import connectors as conn
        return any(c["id"] == ref for c in conn.CATALOG)
    except Exception:
        return False


def build_tool_defs(agent_tools: list[dict], workspace: str = "shared") -> tuple[list[dict], dict]:
    """Return (openai_tool_defs, registry) for the tools attached to an agent.
    registry maps the exposed function name -> ('kind', tool_spec, operation?).
    `workspace` scopes the built-in file tools to a folder in the storage root."""
    defs: list[dict] = []
    registry: dict = {}

    # built-in file tools — granted when the agent has file access (a workspace folder)
    for t in agent_tools or []:
        if t.get("type") == "file_access" or t.get("ref") == "file_access":
            ws = t.get("workspace") or workspace or "shared"
            _add_file_tools(defs, registry, ws)
            break

    for t in agent_tools or []:
        ref = t.get("ref")
        ttype = t.get("type")
        if ttype == "file_access":
            continue
        # MCP server as a bundle of tools — expose each discovered tool as a callable function.
        # ref = the registered MCP server id. Tool discovery is cached (mcp_client), so this
        # stays fast and never blocks run startup on a cold/broken server.
        if ttype == "mcp":
            sid = t.get("ref") or t.get("server_id")
            if sid:
                from . import mcp_store, mcp_client
                server = mcp_store.get_server(sid)
                if server:
                    label = server.get("name", "mcp")
                    for mt in mcp_client.list_tools(server):
                        # keep the tool's own name intact (names are capped at 60 chars): shorten the label
                        fname = _safe_name(f"mcp_{label[:20]}_{mt['name']}") or f"mcp_{mt['name']}"
                        defs.append(_fn_def(
                            fname,
                            f"[{label} · MCP] {mt.get('description','') or mt['name']}",
                            mt.get("schema") or {"type": "object", "properties": {}}))
                        registry[fname] = ("mcp", {"server_id": sid, "tool": mt["name"]}, None)
            continue
        # knowledge pipeline (RAG) as a tool — the agent can search a linked index
        if ttype == "knowledge" or ttype == "rag":
            pid = t.get("ref") or t.get("pipeline_id")
            pname = t.get("name") or "knowledge base"
            if pid:
                fname = _safe_name(f"search_{pname}") or "search_knowledge"
                defs.append(_fn_def(fname,
                            f"Search the '{pname}' knowledge base for relevant passages to ground "
                            f"your answer. Use this whenever the question may be answered by indexed "
                            f"company documents. Returns cited text chunks.",
                            {"type": "object", "properties": {
                                "query": {"type": "string", "description": "what to look up"}},
                             "required": ["query"]}))
                registry[fname] = ("knowledge", {"pipeline_id": pid, "name": pname}, None)
            continue
        # registered ML model as a tool (Data Science Lab registry) — additive path
        if ttype == "model" or t.get("model_name"):
            mname = t.get("model_name") or t.get("name") or ref
            if mname:
                fname = _safe_name(f"invoke_{mname}")
                defs.append(_fn_def(fname,
                            f"Call the registered ML model '{mname}' (Production) for a prediction.",
                            {"type": "object", "properties": {
                                "inputs": {"description": "model input payload"}},
                             "required": ["inputs"]}))
                registry[fname] = ("model", {"model_name": mname,
                                             "serving_url": t.get("serving_url", "")}, None)
            continue
        # connector (Google ADK connectors) as a callable tool — the fix so the model
        # actually calls the connector instead of answering directly.
        if ttype == "connector" or (ref and _is_connector(ref)):
            cid = ref or t.get("name")
            from . import connectors as conn
            schema = conn.connector_tool_def(cid)
            cats = {c["id"]: c for c in conn.list_connectors()}
            cinfo = cats.get(cid)
            if cinfo and cinfo.get("enabled") and schema:
                desc, props, required = schema
                fname = _safe_name(cid)
                sch = {"type": "object", "properties": props}
                if required:
                    sch["required"] = required
                defs.append(_fn_def(fname, f"{cinfo['name']}: {desc}", sch))
                registry[fname] = ("connector", {"cid": cid, "config": cinfo.get("config", {})}, None)
            continue

        spec = tools_repo.get(ref) if ref else None
        if ttype == "builtin" or (spec and spec.get("type") == "builtin"):
            fname = _safe_name((spec or t).get("name", t.get("name", "builtin")))
            defs.append(_fn_def(fname, (spec or t).get("description", ""), {}))
            registry[fname] = ("builtin", spec or t, None)
            continue

        if not spec:
            continue

        if spec.get("type") == "function":
            fname = _safe_name(spec["name"])
            params = spec.get("spec", {}).get("signature") or spec.get("spec", {}).get("parameters") or {}
            defs.append(_fn_def(fname, spec.get("description", ""), params))
            registry[fname] = ("function", spec, None)

        elif spec.get("type") == "openapi":
            ops = spec.get("spec", {}).get("operation_details", []) or _ops_from_ids(spec)
            # per-operation scoping: if the binding lists specific operationIds, expose ONLY
            # those to the model (least privilege). Empty list = all operations (unchanged).
            allowed = t.get("operations") or []
            if allowed:
                allow_set = set(allowed)
                ops = [o for o in ops if o.get("operationId") in allow_set]
            for op in ops:
                fname = _safe_name(op["operationId"])
                params = op.get("parameters")
                props: dict = {}
                required: list = []
                if params:
                    # flat, named, typed fields (ADK principle — reliable tool-calling)
                    for p in params:
                        js: dict = {"type": p.get("type", "string") or "string"}
                        if p.get("description"):
                            js["description"] = p["description"]
                        if p.get("enum"):
                            js["enum"] = p["enum"]
                        props[p["name"]] = js
                        if p.get("required"):
                            required.append(p["name"])
                else:
                    # legacy specs without captured params: derive path params from the URL
                    import re as _re
                    for pp in _re.findall(r"{(\w+)}", op.get("path", "")):
                        props[pp] = {"type": "string", "description": f"path parameter '{pp}'"}
                        required.append(pp)
                schema = {"type": "object", "properties": props}
                if required:
                    schema["required"] = required
                defs.append(_fn_def(fname, op.get("summary") or f"{op['method']} {op['path']}", schema))
                registry[fname] = ("openapi", spec, op)
    return defs, registry


def _ops_from_ids(spec: dict) -> list[dict]:
    # fallback when only operationIds were stored
    return [{"operationId": oid, "method": "GET", "path": "/", "summary": oid}
            for oid in spec.get("operations", [])]


def _fn_def(name: str, description: str, parameters: dict) -> dict:
    if not parameters or "type" not in parameters:
        parameters = {"type": "object", "properties": parameters or {}}
    return {"type": "function", "function": {
        "name": name, "description": description or name, "parameters": parameters}}


def _add_file_tools(defs: list, registry: dict, workspace: str) -> None:
    """Register list/read/write/delete file tools scoped to `workspace`."""
    ws = (workspace or "shared").strip("/")
    defs.append(_fn_def("list_files", f"List files in the agent's workspace folder ('{ws}').",
                        {"type": "object", "properties": {
                            "subfolder": {"type": "string", "description": "optional subfolder"}}}))
    defs.append(_fn_def("read_file", f"Read a text file from the workspace ('{ws}').",
                        {"type": "object", "properties": {"path": {"type": "string"}},
                         "required": ["path"]}))
    defs.append(_fn_def("write_file", f"Write/create a file in the workspace ('{ws}').",
                        {"type": "object", "properties": {
                            "path": {"type": "string"}, "content": {"type": "string"}},
                         "required": ["path", "content"]}))
    defs.append(_fn_def("delete_file", f"Delete a file in the workspace ('{ws}').",
                        {"type": "object", "properties": {"path": {"type": "string"}},
                         "required": ["path"]}))
    defs.append(_fn_def("create_document",
                        f"Generate a real Word (.docx) file in the workspace ('{ws}'). "
                        "Use this to produce a downloadable Word document.",
                        {"type": "object", "properties": {
                            "path": {"type": "string", "description": "file name, e.g. report.docx"},
                            "title": {"type": "string"},
                            "content": {"type": "string", "description": "body text (markdown-ish): # headings, - bullets"},
                            "sections": {"type": "array", "description": "optional [{heading,text,bullets,table}]",
                                         "items": {"type": "object"}}},
                         "required": ["path"]}))
    for n in ("list_files", "read_file", "write_file", "delete_file", "create_document"):
        registry[n] = ("file", {"workspace": ws}, None)


def _scoped(ws: str, rel: str) -> str:
    rel = (rel or "").strip().lstrip("/")
    ws = (ws or "shared").strip("/")
    # confine within the workspace folder (double-guarded; filestore also confines to root)
    if rel.startswith(ws + "/") or rel == ws:
        return rel
    return f"{ws}/{rel}" if rel else ws


def _run_file(spec: dict, name: str, args: dict) -> str:
    from . import filestore
    ws = spec.get("workspace", "shared")

    def _resolve_prefix(sub: str) -> str:
        """Resolve within the workspace; if that yields nothing and the workspace
        isn't already under shared/, also try shared/<workspace> (common mismatch)."""
        primary = _scoped(ws, sub)
        try:
            if filestore.list_dir(primary):
                return primary
        except Exception:
            pass
        if not ws.startswith("shared/") and ws != "shared":
            alt = _scoped(f"shared/{ws}", sub)
            try:
                if filestore.list_dir(alt):
                    return alt
            except Exception:
                pass
        return primary

    try:
        if name == "list_files":
            prefix = _resolve_prefix(args.get("subfolder", ""))
            return json.dumps({"folder": prefix, "files": filestore.list_dir(prefix)})
        if name == "read_file":
            rel = args.get("path", "")
            p = _scoped(ws, rel)
            try:
                return json.dumps({"content": filestore.read_text(p)})
            except filestore.StorageError:
                if not ws.startswith("shared/") and ws != "shared":
                    return json.dumps({"content": filestore.read_text(_scoped(f"shared/{ws}", rel))})
                raise
        if name == "write_file":
            rel = args.get("path", "")
            # writing plain text into a .docx/.doc produces a junk file — build a real doc instead
            if rel.lower().endswith((".docx", ".doc")):
                from . import docgen
                base = rel.rsplit(".", 1)[0]
                rec = docgen.create_document(workspace=ws, path=base, fmt="docx",
                                             title=args.get("title", ""), content=args.get("content", ""))
                return json.dumps({"written": rec, "note": "created as a real Word document"})
            rec = filestore.write_text(_scoped(ws, rel), args.get("content", ""), actor="agent")
            return json.dumps({"written": rec})
        if name == "delete_file":
            return json.dumps({"deleted": filestore.delete(_scoped(ws, args.get("path", "")))})
        if name == "create_document":
            from . import docgen
            fmt = (args.get("format", "docx") or "docx").lower().lstrip(".")
            if fmt not in ("docx", "doc"):
                return json.dumps({"error": "only .docx documents are supported"})
            rec = docgen.create_document(
                workspace=ws, path=args.get("path", "document"),
                fmt="docx", title=args.get("title", ""),
                content=args.get("content", ""), sections=args.get("sections"))
            return json.dumps({"created": rec})
    except filestore.StorageError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"error": f"unknown file tool {name}"})


def _resolve_tool_name(registry: dict, name: str) -> str | None:
    """Map a model-emitted tool name to a real registered tool, tolerating hallucinated
    aliases (findCustomer→getCustomer), case/underscore differences, and verb swaps.
    Returns the resolved key, or None if there's no confident match."""
    if name in registry:
        return name
    keys = list(registry.keys())
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    tn = norm(name)
    # exact normalized match (getCustomer == get_customer == GetCustomer)
    for k in keys:
        if norm(k) == tn:
            return k
    # verb-insensitive match: compare the "noun" part after a leading verb
    verbs = ("get", "find", "fetch", "list", "search", "lookup", "retrieve", "read", "query", "create", "update", "delete")
    def noun(s):
        n = norm(s)
        for v in verbs:
            if n.startswith(v):
                return n[len(v):]
        return n
    cand = [k for k in keys if noun(k) == noun(name) and noun(name)]
    if len(cand) == 1:
        return cand[0]
    # substring containment (customer in getCustomer)
    cand = [k for k in keys if noun(name) and (noun(name) in norm(k) or norm(k) in tn)]
    if len(cand) == 1:
        return cand[0]
    # single-tool agent: if there's exactly one tool, route to it
    if len(keys) == 1:
        return keys[0]
    return None


def execute_tool(registry: dict, name: str, args: dict) -> str:
    """Execute a tool call by exposed function name; returns a string result.
    Tolerates hallucinated/aliased tool names by resolving to the nearest real tool."""
    resolved = _resolve_tool_name(registry, name)
    entry = registry.get(resolved) if resolved else None
    if not entry:
        return json.dumps({"error": f"unknown tool '{name}'",
                           "available_tools": list(registry.keys()),
                           "hint": "call one of available_tools by its exact name"})
    kind, spec, op = entry
    try:
        if kind == "file":
            return _run_file(spec, resolved, args)
        if kind == "model":
            from .modules.data_science_lab import registry as reg
            return json.dumps(reg.invoke(spec["model_name"], args.get("inputs"),
                                         spec.get("serving_url", "")))
        if kind == "connector":
            from . import connectors as conn
            return json.dumps(conn.execute_connector(spec["cid"], spec.get("config", {}), args))
        if kind == "knowledge":
            from .rag import ingest as rag_ingest
            r = rag_ingest.retrieve(spec["pipeline_id"], args.get("query", ""))
            hits = r.get("results", [])
            return json.dumps({
                "query": args.get("query", ""),
                "passages": [{"text": h.get("text", ""), "score": h.get("score"),
                              "source": (h.get("metadata") or {}).get("source", "")}
                             for h in hits],
                "note": "cite sources when using these passages",
            })
        if kind == "builtin":
            return _run_builtin(spec, args)
        if kind == "function":
            return _run_function(spec, args)
        if kind == "openapi":
            return _run_openapi(spec, op, args)
        if kind == "mcp":
            from . import mcp_client, mcp_store
            server = mcp_store.get_server(spec["server_id"])
            if not server:
                return json.dumps({"error": f"MCP server '{spec['server_id']}' not found"})
            return mcp_client.call_tool(server, spec["tool"], args)
    except Exception as e:
        return json.dumps({"error": f"tool '{name}' failed: {e}"})
    return json.dumps({"error": "unsupported tool type"})


def _run_builtin(spec: dict, args: dict) -> str:
    name = (spec.get("name") or "").lower()
    if "time" in name or "date" in name:
        return json.dumps({"utc_now": datetime.now(timezone.utc).isoformat()})
    if "calc" in name or "math" in name:
        expr = str(args.get("expression") or args.get("input") or "")
        try:
            return json.dumps({"result": _safe_eval(expr)})
        except Exception as e:
            return json.dumps({"error": str(e)})
    return json.dumps({"note": f"builtin '{spec.get('name')}' has no server-side implementation"})


def _safe_eval(expr: str):
    """Evaluate a basic arithmetic expression without eval() (AST-based)."""
    import ast
    import operator as _op
    ops = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
           ast.Div: _op.truediv, ast.Pow: _op.pow, ast.Mod: _op.mod,
           ast.USub: _op.neg, ast.UAdd: _op.pos}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.operand))
        raise ValueError("only basic arithmetic is supported")

    return ev(ast.parse(expr, mode="eval"))


def _run_function(spec: dict, args: dict) -> str:
    webhook = spec.get("spec", {}).get("webhook_url")
    if not webhook:
        return json.dumps({"note": f"function '{spec.get('name')}' has no webhook_url configured; "
                                    "register it with a webhook to make it callable",
                           "received_args": args})
    from .security_net import check_url, BlockedURLError
    try:
        check_url(webhook)
    except BlockedURLError as e:
        return json.dumps({"error": str(e)})
    data = json.dumps(args).encode()
    req = urllib.request.Request(webhook, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode()[:4000]


# def _run_openapi(spec: dict, op: dict, args: dict) -> str:
#     servers = spec.get("spec", {}).get("servers") or []
#     base = (servers[0].get("url") if servers and isinstance(servers[0], dict) else "") or ""
#     if not base:
#         return json.dumps({"error": "no server URL in the OpenAPI spec; add servers[].url"})
#     path = op.get("path", "/")
#     params = op.get("parameters") or []
#     # classify each flat named arg by its declared location
#     by_loc = {p["name"]: p.get("in", "query") for p in params}
#     import re as _re
#     declared_path = _re.findall(r"{(\w+)}", path)
#     path_vals, query, body = {}, {}, {}
#     # legacy/back-compat containers
#     query.update(args.get("query") or {})
#     if isinstance(args.get("body"), dict):
#         body.update(args["body"])
#     for k, v in args.items():
#         if k in ("query", "body", "path_params"):
#             continue
#         loc = by_loc.get(k)
#         if loc == "path" or (loc is None and k in declared_path):
#             path_vals[k] = v
#         elif loc == "body":
#             body[k] = v
#         else:
#             query[k] = v
#     for k, v in (args.get("path_params") or {}).items():
#         path_vals[k] = v
#     for k, v in path_vals.items():
#         path = path.replace("{" + k + "}", urllib.parse.quote(str(v)))
#     url = base.rstrip("/") + path
#     if query:
#         url += "?" + urllib.parse.urlencode(query)
#     from .security_net import check_url, BlockedURLError
#     try:
#         check_url(url)
#     except BlockedURLError as e:
#         return json.dumps({"error": str(e)})
#     method = (op.get("method") or "GET").upper()
#     headers = {"Accept": "application/json"}
#     token = spec.get("spec", {}).get("auth_token")
#     if token:
#         headers["Authorization"] = f"Bearer {token}"
#     data = json.dumps(body).encode() if body else None
#     if data is not None:
#         headers["Content-Type"] = "application/json"
#     req = urllib.request.Request(url, data=data, method=method, headers=headers)
#     try:
#         with urllib.request.urlopen(req, timeout=25) as r:
#             return r.read().decode()[:4000]
#     except urllib.error.HTTPError as e:
#         return json.dumps({"error": f"API returned {e.code}", "detail": e.read().decode()[:500]})
#     except Exception as e:
#         return json.dumps({"error": f"API call failed: {e}"})



def _run_openapi(spec: dict, op: dict, args: dict) -> str:
    servers = spec.get("spec", {}).get("servers") or []
    base = (
        (servers[0].get("url") if servers and isinstance(servers[0], dict) else "")
        or ""
    )

    if not base:
        return json.dumps({
            "error": "no server URL in the OpenAPI spec; add servers[].url"
        })

    path = op.get("path", "/")
    params = op.get("parameters") or []

    by_loc = {
        p["name"]: p.get("in", "query")
        for p in params
    }

    import re as _re

    declared_path = _re.findall(r"{(\w+)}", path)

    path_vals = {}
    query = {}
    body = {}

    #
    # Explicit containers
    #
    query.update(args.get("query") or {})

    if isinstance(args.get("body"), dict):
        body.update(args["body"])

    #
    # Classify fields
    #
    for k, v in args.items():

        if k in ("query", "body", "path_params"):
            continue

        loc = by_loc.get(k)

        if loc == "path" or (loc is None and k in declared_path):
            path_vals[k] = v

        elif loc == "body":
            body[k] = v

        else:
            query[k] = v

    #
    # Path overrides
    #
    for k, v in (args.get("path_params") or {}).items():
        path_vals[k] = v

    #
    # Inject path values
    #
    for k, v in path_vals.items():
        path = path.replace(
            "{" + k + "}",
            urllib.parse.quote(str(v))
        )

    url = base.rstrip("/") + path

    if query:
        url += "?" + urllib.parse.urlencode(query)

    method = (op.get("method") or "GET").upper()

    headers = {
        "Accept": "application/json"
    }

    token = spec.get("spec", {}).get("auth_token")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    #
    # IMPORTANT FIX
    #
    # For POST / PUT / PATCH:
    # if body is still empty but user provided args,
    # treat all remaining args as request body.
    #
    if method in ("POST", "PUT", "PATCH"):

        if not body:

            body = {
                k: v
                for k, v in args.items()
                if k not in ("query", "path_params")
            }

    data = None

    if method in ("POST", "PUT", "PATCH"):

        data = json.dumps(body).encode()

        headers["Content-Type"] = "application/json"

    from .security_net import check_url, BlockedURLError

    try:
        check_url(url)
    except BlockedURLError as e:
        return json.dumps({"error": str(e)})

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )

    try:

        with urllib.request.urlopen(req, timeout=25) as r:

            return r.read().decode()[:4000]

    except urllib.error.HTTPError as e:

        try:
            detail = e.read().decode()[:1000]
        except Exception:
            detail = ""

        return json.dumps({
            "error": f"API returned {e.code}",
            "detail": detail,
            "method": method,
            "url": url,
            "body": body
        })

    except Exception as e:

        return json.dumps({
            "error": f"API call failed: {e}",
            "method": method,
            "url": url,
            "body": body
        })
 
