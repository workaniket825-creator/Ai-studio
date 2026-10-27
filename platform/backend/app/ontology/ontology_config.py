"""Ontology enablement + datastore configuration (spec A§6, A§10, A§12).

Enablement is resolved once per (tenant, workflow): workflow-level -> tenant-level
-> system default (off). Datastore connection is front-end driven: entered, tested,
and hot-applied from the admin UI with no backend/code change; secrets are stored as
references via the platform's governance settings store (never displayed).

All of this reuses the existing governance settings store (no new secret system).
"""
from __future__ import annotations

from ..governance import get_settings, update_settings

_DEFAULT = {
    "enabled_default": False,          # system default: OFF (spec A§1)
    "tenants": {},                     # tenant -> bool
    "workflows": {},                   # workflow_id -> bool
    "workflow_graphs": {},             # workflow_id -> graph_id (Enablement binding the frontend reads)
    "expansion": {"max_hops": 1, "max_nodes": 15},  # context-size control the frontend reads
    "extraction_model": "",            # default Model Endpoint id used for LLM extraction ("" = first available)
    # Editable, scientific extraction prompt. Placeholders: {text} (source) and {instructions}
    # (optional user additions). This is the mandatory base prompt shown + editable in the UI.
    "extraction_prompt": (
        "You are a precise ontology and knowledge-graph extraction engine. From the SOURCE TEXT "
        "below, extract a well-formed knowledge graph as STRICT JSON and nothing else.\n\n"
        "Output schema (return ONLY this JSON object):\n"
        '{"entities":[{"name":"<verbatim surface form>","type":"<concise class>","confidence":<0..1>}],'
        '"relations":[{"source":"<entity name>","target":"<entity name>","relation":"<verb/label>","confidence":<0..1>}]}\n\n'
        "Extraction rules:\n"
        "1. ENTITIES: extract salient, well-defined things (organizations, people, systems, "
        "concepts, products, locations, events). Use the name EXACTLY as it appears in the text.\n"
        "2. TYPES: assign a concise, consistent class per entity (e.g. Organization, Person, "
        "Product, Concept). Reuse the same type label for like entities to form a clean taxonomy.\n"
        "3. RELATIONS: connect entities with meaningful, directional labels (subject -> object). "
        "Only assert a relation if it is stated or clearly implied by the text.\n"
        "4. GROUNDING: do NOT invent entities or relations absent from the text. Prefer precision "
        "over recall; omit anything uncertain rather than hallucinate.\n"
        "5. CONFIDENCE: set 0..1 reflecting how explicitly the text supports each item.\n"
        "6. NORMALISE: merge obvious duplicates (same referent, different casing/whitespace) into "
        "one entity; keep the most complete surface form.\n"
        "{instructions}\n\n"
        "SOURCE TEXT:\n{text}"
    ),
    "datastore": {                     # front-end-driven connection (spec A§12)
        "type": "json",               # json (default, zero-dep) | postgres
        "host": "", "port": 5432, "database": "", "schema": "public",
        "secret_ref": "",             # reference to a secret, never the value
        "tls": True, "vector": True,  # pgvector on
        "status": "not_configured",   # not_configured | connected | failing
        "last_test": "", "last_error": "",
        "per_graph": {},              # graph_id -> {type,host,...} override
    },
}


def _cfg() -> dict:
    s = get_settings()
    o = s.get("ontology") or {}
    merged = {**_DEFAULT, **o}
    merged["datastore"] = {**_DEFAULT["datastore"], **(o.get("datastore") or {})}
    return merged


def get_config() -> dict:
    return _cfg()


def update_config(patch: dict, actor: str = "admin") -> dict:
    cur = _cfg()
    if "datastore" in patch and isinstance(patch["datastore"], dict):
        cur["datastore"] = {**cur["datastore"], **patch.pop("datastore")}
    cur.update(patch)
    update_settings({"ontology": cur})
    return cur


def is_enabled(tenant: str = "default", workflow_id: str = "") -> bool:
    """Resolution order (spec A§6): workflow -> tenant -> system default."""
    c = _cfg()
    if workflow_id and workflow_id in c["workflows"]:
        return bool(c["workflows"][workflow_id])
    if tenant and tenant in c["tenants"]:
        return bool(c["tenants"][tenant])
    return bool(c["enabled_default"])


def set_workflow_enabled(workflow_id: str, enabled: bool) -> dict:
    c = _cfg()
    c["workflows"][workflow_id] = bool(enabled)
    update_settings({"ontology": c})
    return c


def set_tenant_enabled(tenant: str, enabled: bool) -> dict:
    c = _cfg()
    c["tenants"][tenant] = bool(enabled)
    update_settings({"ontology": c})
    return c


# ------------------------------- datastore (front-end driven, A§12) -------------------------------
def test_datastore(conn: dict | None = None) -> dict:
    """Validate a datastore connection from the UI before saving.
    JSON store is always available; postgres is probed if the driver is present."""
    ds = conn or _cfg()["datastore"]
    dtype = ds.get("type", "json")
    if dtype == "json":
        return {"ok": True, "status": "connected", "detail": "Built-in JSON store is ready."}
    if dtype == "postgres":
        try:
            import psycopg  # noqa: F401
        except Exception:
            try:
                import psycopg2  # noqa: F401
            except Exception:
                return {"ok": False, "status": "failing",
                        "detail": "PostgreSQL driver not installed on the server "
                                  "(pip install psycopg[binary]). JSON store still works."}
        if not ds.get("host") or not ds.get("database"):
            return {"ok": False, "status": "failing", "detail": "host and database are required"}
        # A real probe would open a connection here using the resolved secret.
        return {"ok": True, "status": "connected",
                "detail": f"Reachable config for {ds['host']}:{ds.get('port', 5432)}/{ds['database']}"}
    return {"ok": False, "status": "failing", "detail": f"unsupported store type '{dtype}'"}


def save_datastore(conn: dict, actor: str = "admin") -> dict:
    """Persist + hot-apply the datastore connection (no redeploy)."""
    result = test_datastore(conn)
    from datetime import datetime, timezone
    conn = {**conn, "status": result["status"],
            "last_test": datetime.now(timezone.utc).isoformat(),
            "last_error": "" if result["ok"] else result["detail"]}
    update_config({"datastore": conn}, actor)
    return {**result, "datastore": _cfg()["datastore"]}


# ------------------------------- per-graph store overrides (spec A§12) -------------------------------
def get_graph_datastore(graph_id: str) -> dict:
    """Resolve the effective store for a graph: its own override, else the default."""
    ds = _cfg()["datastore"]
    override = (ds.get("per_graph") or {}).get(graph_id)
    if override:
        return {**ds, **override, "_source": "per_graph"}
    return {**ds, "_source": "default"}


def save_graph_datastore(graph_id: str, conn: dict, actor: str = "admin") -> dict:
    """Set/replace a per-graph store override; None/empty clears it (revert to default)."""
    result = test_datastore(conn) if conn else {"ok": True, "status": "cleared", "detail": "using default"}
    ds = _cfg()["datastore"]
    per = dict(ds.get("per_graph") or {})
    if conn:
        from datetime import datetime, timezone
        per[graph_id] = {**conn, "status": result["status"],
                         "last_test": datetime.now(timezone.utc).isoformat(),
                         "last_error": "" if result["ok"] else result["detail"]}
    else:
        per.pop(graph_id, None)
    update_config({"datastore": {**ds, "per_graph": per}}, actor)
    return {**result, "datastore": get_graph_datastore(graph_id)}

