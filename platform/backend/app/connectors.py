"""ADK Connectors (out-of-box connectivity) — spec addition.

Google ADK ships a wide set of connectivity options. This module exposes a curated
catalog so agents can leverage them. Each connector has a category, a short "how to
enable" config schema (with dummy values), and a `cloud_free` flag indicating whether
it needs Google Cloud Application Integration or works with just an API/endpoint.

Enabling a connector persists its config; enabled connectors are offered to agents in
the Create-Agent tools step (type = "connector").
"""
from __future__ import annotations

import json

from .store import DATA_DIR

_STATE = DATA_DIR / "connectors.json"

# category: builtin | mcp | toolkit | openapi | integration
CATALOG = [
    # --- ADK built-in tools (no external platform) ---
    {"id": "google_search", "name": "Google Search", "category": "builtin", "cloud_free": True,
     "description": "ADK built-in web search grounding tool.",
     "config_fields": [], "adk": "google.adk.tools.google_search"},
    {"id": "code_exec", "name": "Code Execution", "category": "builtin", "cloud_free": True,
     "description": "Run sandboxed code (data analysis, math, transforms).",
     "config_fields": [], "adk": "google.adk.tools.built_in_code_execution"},
    {"id": "vertex_rag", "name": "Vertex AI Search / RAG", "category": "builtin", "cloud_free": False,
     "description": "Retrieval over a managed corpus (grounded answers with citations).",
     "config_fields": [{"key": "rag_corpus", "example": "projects/demo/locations/us/ragCorpora/123"}],
     "adk": "google.adk.tools.retrieval.VertexAiRagRetrieval"},

    # --- MCP toolsets (open-source protocol; run a local/remote MCP server) ---
    {"id": "mcp_filesystem", "name": "MCP · Filesystem", "category": "mcp", "cloud_free": True,
     "description": "Read/write files via an MCP filesystem server.",
     "config_fields": [{"key": "command", "example": "npx -y @modelcontextprotocol/server-filesystem /data"}],
     "adk": "google.adk.tools.mcp_tool.MCPToolset"},
    {"id": "mcp_postgres", "name": "MCP · Postgres / Databases", "category": "mcp", "cloud_free": True,
     "description": "Query databases through the MCP Toolbox for Databases.",
     "config_fields": [{"key": "url", "example": "postgresql://user:DUMMY@localhost:5432/app"}],
     "adk": "google.adk.tools.mcp_tool.MCPToolset"},

    # --- third-party toolkits ---
    {"id": "langchain", "name": "LangChain Tools", "category": "toolkit", "cloud_free": True,
     "description": "Wrap any LangChain tool for use inside an ADK agent.",
     "config_fields": [{"key": "tool", "example": "TavilySearchResults(max_results=3)"}],
     "adk": "google.adk.tools.langchain_tool.LangchainTool"},
    {"id": "crewai", "name": "CrewAI Tools", "category": "toolkit", "cloud_free": True,
     "description": "Use CrewAI's tool library from ADK.",
     "config_fields": [{"key": "tool", "example": "SerperDevTool()"}],
     "adk": "google.adk.tools.crewai_tool.CrewaiTool"},

    # --- OpenAPI (already supported in Tool Registry, surfaced here too) ---
    {"id": "openapi", "name": "OpenAPI REST APIs", "category": "openapi", "cloud_free": True,
     "description": "Auto-generate tools from any OpenAPI spec (see Tool Registry).",
     "config_fields": [{"key": "spec_url", "example": "https://api.example.com/openapi.json"}],
     "adk": "google.adk.tools.openapi_tool.OpenAPIToolset"},

    # --- enterprise Application Integration connectors (100+ via GCP) ---
    {"id": "salesforce", "name": "Salesforce", "category": "integration", "cloud_free": False,
     "description": "CRM records via Application Integration connector.",
     "config_fields": [{"key": "connection", "example": "projects/demo/locations/us/connections/salesforce"},
                       {"key": "token", "example": "sf-DUMMY-token"}],
     "adk": "ApplicationIntegrationToolset"},
    {"id": "servicenow", "name": "ServiceNow", "category": "integration", "cloud_free": False,
     "description": "ITSM tickets/incidents via Integration Connector.",
     "config_fields": [{"key": "connection", "example": "projects/demo/locations/us/connections/servicenow"}],
     "adk": "ApplicationIntegrationToolset"},
    {"id": "slack", "name": "Slack", "category": "integration", "cloud_free": False,
     "description": "Post/read messages via Integration Connector.",
     "config_fields": [{"key": "bot_token", "example": "xoxb-DUMMY-000"}],
     "adk": "ApplicationIntegrationToolset"},
    {"id": "jira", "name": "Jira", "category": "integration", "cloud_free": False,
     "description": "Issues/projects via Integration Connector.",
     "config_fields": [{"key": "connection", "example": "projects/demo/locations/us/connections/jira"}],
     "adk": "ApplicationIntegrationToolset"},
    {"id": "bigquery", "name": "BigQuery", "category": "integration", "cloud_free": False,
     "description": "Query warehouse tables via ADK BigQuery tools.",
     "config_fields": [{"key": "project", "example": "my-gcp-project"}],
     "adk": "google.adk.tools.bigquery"},
]


def _state() -> dict:
    return json.loads(_STATE.read_text()) if _STATE.exists() else {}


def list_connectors() -> list[dict]:
    st = _state()
    out = []
    for c in CATALOG:
        s = st.get(c["id"], {})
        out.append({**c, "enabled": s.get("enabled", False), "config": s.get("config", {})})
    return out


def set_connector(cid: str, enabled: bool, config: dict | None = None) -> dict:
    st = _state()
    st[cid] = {"enabled": enabled, "config": config or st.get(cid, {}).get("config", {})}
    _STATE.write_text(json.dumps(st, indent=2))
    c = next((x for x in CATALOG if x["id"] == cid), None)
    return {**(c or {"id": cid}), **st[cid]}


def enabled_connectors() -> list[dict]:
    return [c for c in list_connectors() if c["enabled"]]


# ------------------------------- connectors as callable tools -------------------------------
# Per-connector flat, named, typed schema (ADK principle: simple signatures call reliably).
_TOOL_SCHEMAS = {
    "google_search": ("Search the web and return relevant results for a query.",
                      {"query": {"type": "string", "description": "the search query"}}, ["query"]),
    "code_exec": ("Execute a computation / evaluate an expression and return the result.",
                  {"code": {"type": "string", "description": "code or arithmetic expression to evaluate"}}, ["code"]),
    "vertex_rag": ("Retrieve grounded passages from the configured RAG corpus for a query.",
                   {"query": {"type": "string", "description": "what to retrieve"}}, ["query"]),
    "mcp_filesystem": ("Read or list files via the MCP filesystem server.",
                       {"operation": {"type": "string", "enum": ["list", "read"], "description": "list or read"},
                        "path": {"type": "string", "description": "path to list/read"}}, ["operation", "path"]),
    "mcp_postgres": ("Run a read-only SQL query against the configured database via MCP.",
                     {"sql": {"type": "string", "description": "the SQL query"}}, ["sql"]),
    "langchain": ("Invoke the wrapped LangChain tool with an input string.",
                  {"input": {"type": "string", "description": "tool input"}}, ["input"]),
    "crewai": ("Invoke the wrapped CrewAI tool with an input string.",
               {"input": {"type": "string", "description": "tool input"}}, ["input"]),
    "salesforce": ("Query Salesforce (accounts, contacts, opportunities).",
                   {"query": {"type": "string", "description": "what to look up, or a SOQL query"}}, ["query"]),
    "servicenow": ("Look up or create ServiceNow ITSM tickets/incidents.",
                   {"query": {"type": "string", "description": "ticket search or description"}}, ["query"]),
    "slack": ("Post a message to Slack or search messages.",
              {"action": {"type": "string", "enum": ["post", "search"]},
               "text": {"type": "string", "description": "message or search text"},
               "channel": {"type": "string", "description": "channel (for post)"}}, ["action", "text"]),
    "jira": ("Search or create Jira issues.",
             {"query": {"type": "string", "description": "issue search (JQL/text) or new-issue summary"}}, ["query"]),
    "bigquery": ("Run a read-only SQL query against BigQuery.",
                 {"sql": {"type": "string", "description": "the SQL query"}}, ["sql"]),
}


def connector_tool_def(cid: str):
    """Return (description, properties, required) for a connector, or None if unknown."""
    return _TOOL_SCHEMAS.get(cid)


def _http_call(url: str, payload: dict) -> dict:
    import urllib.request
    from .security_net import check_url, BlockedURLError
    try:
        check_url(url)
    except BlockedURLError as e:
        return {"error": str(e)}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return {"result": r.read().decode()[:4000]}
    except Exception as e:
        return {"error": f"call failed: {e}"}


def execute_connector(cid: str, config: dict, args: dict) -> dict:
    """Execute an enabled connector. Runs live where it genuinely can; otherwise returns an
    HONEST guarded result (never silently fabricated) so the model relays the truth.

    - code_exec: real safe arithmetic evaluation (no external service needed).
    - any connector with a configured `endpoint`/`webhook` URL: real HTTP POST (SSRF-guarded).
    - ADK/GCP-backed connectors without an endpoint (search, Salesforce, Slack, MCP, …):
      honest 'needs its ADK runtime / credentials' result echoing the request.
    """
    cfg = config or {}
    # 1) code execution — genuinely runnable (safe arithmetic)
    if cid == "code_exec":
        from .tool_exec import _safe_eval
        expr = str(args.get("code") or args.get("input") or "").strip()
        try:
            return {"result": _safe_eval(expr)}
        except Exception:
            return {"status": "limited",
                    "note": "Only safe arithmetic runs in-process. For full code execution, "
                            "run this connector through the ADK sandboxed code executor.",
                    "requested": expr[:200]}
    # 2) a configured HTTP endpoint (self-hosted bridge / webhook) — real call
    url = cfg.get("endpoint") or cfg.get("webhook") or cfg.get("url_http")
    if url:
        return _http_call(url, {"connector": cid, "args": args})
    # 3) OpenAPI connector — real APIs live in the Tool Registry
    if cid == "openapi":
        return {"status": "use_tool_registry",
                "note": "Register the OpenAPI spec in Tool Registry and attach its operations to the "
                        "agent — those are executed live."}
    # 4) everything else needs the ADK runtime + service credentials
    return {"status": "not_executed",
            "connector": cid,
            "note": f"The '{cid}' connector is enabled but executes through its Google ADK runtime and "
                    f"the service's credentials, which must be configured on the server for live calls. "
                    f"No data was fabricated.",
            "requested": args}
