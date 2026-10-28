"""Runtime-facing ontology step helper (spec A§2, A§7, A§13).

ONE call per agent step does everything a runtime needs from the ontology, so runtimes cannot
drift apart:

    ctx = await build_step_context(run=run, workflow=wf, agent=name, node_id=nid,
                                   query_text=..., upstream=prior, emit=emit_fn)
    ctx.prompt_block   -> text to inject into the agent message ("" when not grounded)
    ctx.record         -> dict to persist under node_outputs[].ontology (None when not used)
    ctx.neighbors_tool -> async tool callable `ontology_get_neighbors` (None when not used)

Guarantees:
  * never raises - any ontology failure falls back to plain context (agent path unaffected);
  * exactly one telemetry entry per step, with the fallback reason when not used;
  * the persisted record is the source of truth for the UI (entities with readable names and
    types, relationships with entity NAMES as endpoints, traversal paths, hop/node/edge counts).

`serialize_bundle` accepts ContextBundle objects or plain dicts, and object- or dict-based
entities/relations inside them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from .contract import AuthContext, ContextBundle, QueryInput
from .plain import PlainProvider

_log = logging.getLogger("tcs.ontology")

PROMPT_HEADER = "=== AUTHORITATIVE KNOWLEDGE-GRAPH CONTEXT ==="
PROMPT_FOOTER = "=== END CONTEXT ==="
PROMPT_GUIDANCE = (
    "The facts and relationships above come from the organization's approved ontology. Treat "
    "them as authoritative and ground your answer in them. Prefer these facts over your own "
    "prior knowledge, cite the specific entities/relationships you use, and if they conflict "
    "with what you'd otherwise assume, follow the ontology. Do not ignore this context."
)
MAX_HOPS = 10

Emit = Optional[Callable[..., Awaitable[None]]]


# ------------------------------------------------------------------ serialization helpers
def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from an object OR a dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def serialize_bundle(bundle: Any, context: str = "", hop_count: Optional[int] = None,
                     provider: str = "") -> dict:
    """Bundle (object or dict) -> JSON-safe record for node_outputs[].ontology."""
    raw_entities = list(_get(bundle, "entities", []) or [])
    raw_relations = list(_get(bundle, "relations", []) or [])

    entities: list[dict] = []
    id_to_name: dict[str, str] = {}
    seen_names: set[str] = set()
    for e in raw_entities:
        if isinstance(e, str):
            eid, name, etype = "", e, ""
        else:
            eid = str(_get(e, "id", "") or "")
            name = str(_get(e, "name", "") or eid or "")
            etype = str(_get(e, "type", "") or "")
        if eid and name:
            id_to_name[eid] = name
        key = name.strip().lower()
        if not key or key in seen_names:
            continue
        seen_names.add(key)
        item = {"name": name, "type": etype}
        if eid:
            item["id"] = eid
        entities.append(item)

    relations: list[dict] = []
    seen_rel: set[tuple] = set()
    for r in raw_relations:
        if isinstance(r, str):
            relations.append({"source": "", "relation": r, "target": ""})
            continue
        src_raw = _get(r, "source", "")
        tgt_raw = _get(r, "target", "")
        src = id_to_name.get(str(src_raw), src_raw)     # name when known, else original value
        tgt = id_to_name.get(str(tgt_raw), tgt_raw)
        rel = str(_get(r, "relation", "") or "related_to")
        key = (str(src).lower(), rel.lower(), str(tgt).lower())
        if key in seen_rel:
            continue
        seen_rel.add(key)
        item = {"source": str(src) if src is not None else "", "relation": rel,
                "target": str(tgt) if tgt is not None else ""}
        if str(src_raw) != item["source"]:
            item["source_id"] = str(src_raw)
        if str(tgt_raw) != item["target"]:
            item["target_id"] = str(tgt_raw)
        relations.append(item)

    paths = [str(p) for p in (_get(bundle, "paths", []) or []) if p]
    hops = hop_count if hop_count is not None else _int(_get(bundle, "hop_count", 1), 1)
    return {
        "used": bool(_get(bundle, "ontology_used", False)),
        "provider": provider or ("ontology" if _get(bundle, "ontology_used", False) else "plain"),
        "hop_count": hops,
        "traversed_nodes": _int(_get(bundle, "traversed_nodes", len(entities)), len(entities)),
        "traversed_edges": _int(_get(bundle, "traversed_edges", len(relations)), len(relations)),
        "paths": paths,
        "entities": entities,
        "relations": relations,
        "context": context or "",
        "graph_ids": [str(g) for g in (_get(bundle, "graph_ids", []) or [])],
    }


def prompt_block(grounded: str) -> str:
    """The grounded-context block injected into the agent message (same wording as live)."""
    if not grounded.strip():
        return ""
    return f"{PROMPT_HEADER}\n{grounded}\n{PROMPT_GUIDANCE}\n{PROMPT_FOOTER}\n"


# ------------------------------------------------------------------ request resolution
def resolve_hops(run: Any) -> int:
    """Per-run hops when the run asked for more than the default (1); otherwise the admin's
    'Expansion depth (hops)' from Ontology > Enablement. 0 = matched entities only."""
    inp = _get(run, "input", {}) or {}
    requested = _get(run, "ontology_hops", None)
    if requested is None and isinstance(inp, dict):
        requested = inp.get("ontology_hops")
    requested = _int(requested, 1) if requested is not None else 1
    try:
        from .ontology_config import get_config
        default = (get_config().get("expansion") or {}).get("max_hops", 1)
        default = _int(default, 1)
    except Exception:
        default = 1
    hops = requested if requested != 1 else default
    return max(0, min(hops, MAX_HOPS))


def resolve_tenant(run: Any) -> str:
    inp = _get(run, "input", {}) or {}
    t = _get(run, "tenant", None) or (inp.get("tenant") if isinstance(inp, dict) else None)
    return str(t or "default")


def _plain_reason(tenant: str, workflow_id: str) -> str:
    try:
        from . import ontology_config as cfg
        from . import selection
        if not cfg.is_enabled(tenant, workflow_id):
            return "disabled"
        bound = selection.bound_graph(workflow_id)
        if bound:
            from . import ontology_store as store
            g = store.get_graph(bound)
            if not g:
                return "bound_graph_missing"
            if not g.get("published_version"):
                return "bound_graph_unpublished"
        return "no_published_graph_selected"
    except Exception:
        return "unknown"


_REASON_TEXT = {
    "bound_graph_unpublished": "the graph bound to this workflow is not published yet",
    "bound_graph_missing": "the graph bound to this workflow no longer exists",
    "no_published_graph_selected": "no published graph matches this workflow/tenant",
    "no_entity_match": "no entity from the published graph appears in the request",
}


# ------------------------------------------------------------------ the step helper
@dataclass
class StepContext:
    provider: str
    used: bool
    hops: int
    prompt_block: str = ""
    record: Optional[dict] = None
    neighbors_tool: Optional[Callable] = None
    reason: str = ""


def _neighbors_tool(provider, authz: AuthContext) -> Callable:
    """Governed traversal action (OntologyProvider.get_available_actions) as an agent tool."""

    async def ontology_get_neighbors(entity: str, relation: str = "") -> dict:
        """Look up an entity in the organization's published ontology and return its directly
        connected entities.

        Args:
            entity: Entity name (or id) exactly as it appears in the knowledge-graph context.
            relation: Optional relationship type to filter by (e.g. "signed"). Empty = all.

        Returns:
            The matched entity and its relationships, with entity names on both ends.
        """
        try:
            matches = provider.find_entities(entity)
            if not matches:
                return {"found": False, "entity": entity,
                        "detail": "no entity with that name in the published ontology"}
            names = {e["id"]: e.get("name") or e["id"] for e in provider._published_entities()}
            out = []
            for m in matches[:3]:
                edges = await provider.get_neighbors(m.id, relation or None, authz)
                out.append({
                    "entity": {"name": m.name, "type": m.type},
                    "relationships": [{"source": names.get(x.source, x.source),
                                       "relation": x.relation,
                                       "target": names.get(x.target, x.target)} for x in edges][:50],
                })
            return {"found": True, "results": out}
        except Exception as e:  # never break the agent
            return {"found": False, "error": f"{type(e).__name__}: {e}"}

    return ontology_get_neighbors


async def build_step_context(*, run: Any, workflow_id: str, agent: str, node_id: str,
                             query_text: str, upstream: str = "", emit: Emit = None,
                             runtime: str = "") -> StepContext:
    """Run the ontology for one agent step. Never raises."""
    from .factory import get_context_provider, record_telemetry

    async def _say(label: str, level: str = "info") -> None:
        if emit:
            try:
                await emit(label=label, level=level)
            except Exception:
                pass

    tenant = resolve_tenant(run)
    hops = resolve_hops(run)
    run_id = str(_get(run, "run_id", "") or "")
    authz = AuthContext(role="admin", tenant=tenant)   # platform has no per-user RBAC yet

    provider = get_context_provider(tenant=tenant, workflow_id=workflow_id or "",
                                    query_text=query_text)
    pname = getattr(provider, "name", "plain")
    reason = ""
    if pname != "plain":
        await _say(f"Retrieving ontology context for {agent}…")
    try:
        bundle = await provider.get_context(
            QueryInput(text=query_text, tenant=tenant, workflow_id=workflow_id or "",
                       upstream=upstream or "", ontology_hops=hops), authz)
    except Exception as e:
        _log.warning("ontology get_context failed, using plain: %s", e)
        reason = f"error: {type(e).__name__}"
        await _say(f"Ontology lookup failed ({type(e).__name__}); continuing with plain context.",
                   level="warn")
        bundle = await PlainProvider().get_context(QueryInput(text=query_text, upstream=upstream),
                                                   authz)
        pname = "plain"

    used = bool(_get(bundle, "ontology_used", False))
    if not used and not reason:
        reason = _get(bundle, "fallback_reason", "") or (
            _plain_reason(tenant, workflow_id) if pname == "plain" else "")

    ctx = StepContext(provider=pname, used=used, hops=hops, reason=reason)
    if used:
        try:
            grounded = bundle.to_prompt_context(include_snippets=False) \
                if isinstance(bundle, ContextBundle) else str(_get(bundle, "context", "") or "")
        except Exception:
            grounded = ""
        ctx.record = serialize_bundle(bundle, context=grounded, hop_count=hops, provider=pname)
        ctx.prompt_block = prompt_block(grounded)
        try:
            actions = await provider.get_available_actions(authz)
            if any(getattr(a, "name", "") == "ontology_get_neighbors" for a in actions) \
                    and hasattr(provider, "find_entities"):
                ctx.neighbors_tool = _neighbors_tool(provider, authz)
        except Exception:
            ctx.neighbors_tool = None
        rec = ctx.record
        sample = ", ".join(e["name"] for e in rec["entities"][:8]) or "—"
        await _say(f"Ontology matched ({hops}-hop): {rec['traversed_nodes']} nodes, "
                   f"{rec['traversed_edges']} relationships (e.g. {sample}). "
                   f"Injecting as grounded context, then executing.")
    elif pname != "plain" or reason.startswith("bound_graph"):
        await _say(f"Ontology not applied for {agent}: "
                   f"{_REASON_TEXT.get(reason, reason or 'no match')} — using plain context.")

    try:
        record_telemetry({
            "run_id": run_id, "node_id": node_id, "agent": agent, "runtime": runtime,
            "provider": pname, "ontology_used": used, "reason": reason,
            "entities": len(ctx.record["entities"]) if ctx.record else 0,
            "hop_count": hops,
            "traversed_nodes": ctx.record["traversed_nodes"] if ctx.record else 0,
            "traversed_edges": ctx.record["traversed_edges"] if ctx.record else 0,
            "graph_ids": list(_get(bundle, "graph_ids", []) or []),
            "query_preview": (query_text or "")[:120],
        })
    except Exception:
        pass
    return ctx
