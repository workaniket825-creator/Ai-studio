"""Graph selection by tags/config (spec A§10).

Selects the appropriate published graph(s) for a runtime request from the active
workflow, tenant, and/or query domain. Returns [] when nothing matches, which the
provider treats as ontology-off (plain retrieval) — the required fallback.
"""
from __future__ import annotations

from . import ontology_store as store   # lowercase — matches ontology_store.py


_STOP = {"the", "a", "an", "and", "or", "for", "with", "from", "this", "that",
         "is", "are", "was", "were", "to", "of", "in", "on", "at", "by"}


def _tag_tokens(tags) -> set[str]:
    """Tags may be a dict (key -> value) or a list; match on whole words, not substrings."""
    from .ontology_provider import _tok
    vals = tags.values() if isinstance(tags, dict) else (tags or [])
    return _tok(" ".join(str(v) for v in vals))


def bound_graph(workflow_id: str = "") -> str:
    """Graph explicitly bound to this workflow on the Enablement screen ("" if none)."""
    try:
        from .ontology_config import get_config
        return (get_config().get("workflow_graphs") or {}).get(workflow_id or "") or ""
    except Exception:
        return ""


def select_graphs(tenant: str = "default", workflow_id: str = "",
                  query_text: str = "") -> list[dict]:
    published = [g for g in store.list_graphs() if g.get("published_version")]

    # Explicit binding wins and is EXCLUSIVE: the workflow uses only that graph. If the bound
    # graph is not published (yet), return [] -> plain context. Never substitute another graph.
    bound = bound_graph(workflow_id)
    if bound:
        return [g for g in published if g.get("id") == bound]
    if not published:
        return []

    from .ontology_provider import _tok
    q_tokens = {t for t in _tok(query_text, query=True) if t not in _STOP and len(t) > 2}

    matches: list[dict] = []
    for g in published:
        scoped_tenants = g.get("tenants") or []
        if scoped_tenants and tenant not in scoped_tenants:
            continue                      # tenant scoping applies to every graph

        scoped_workflows = g.get("workflows") or []
        if workflow_id and workflow_id in scoped_workflows:
            matches.append(g)             # graph explicitly scoped to this workflow
            continue
        if scoped_workflows:
            continue                      # graph is restricted to other workflows

        tag_toks = _tag_tokens(g.get("tags"))
        if q_tokens and tag_toks:
            if q_tokens & tag_toks:
                matches.append(g)
        else:
            matches.append(g)             # general-purpose graph, nothing to filter against

    seen: set[str] = set()
    out: list[dict] = []
    for g in matches:
        if g["id"] not in seen:
            seen.add(g["id"])
            out.append(g)
    return out
