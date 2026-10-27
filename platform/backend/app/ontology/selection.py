"""Graph selection by tags/config (spec A§10).

Selects the appropriate published graph(s) for a runtime request from the active
workflow, tenant, and/or query domain. Returns [] when nothing matches, which the
provider treats as ontology-off (plain retrieval) — the required fallback.
"""
from __future__ import annotations

from . import ontology_store as store   # lowercase — matches ontology_store.py


_STOP = {"the", "a", "an", "and", "or", "for", "with", "from", "this", "that",
         "is", "are", "was", "were", "to", "of", "in", "on", "at", "by"}


def select_graphs(tenant: str = "default", workflow_id: str = "",
                  query_text: str = "") -> list[dict]:
    published = [g for g in store.list_graphs() if g.get("published_version")]
    if not published:
        return []

    # Explicit binding wins: if this workflow is bound to a specific graph in config
    # (Enablement screen), use ONLY that graph — never mix in other unscoped graphs.
    try:
        from .ontology_config import get_config
        bound = (get_config().get("workflow_graphs") or {}).get(workflow_id or "")
    except Exception:
        bound = None
    if bound:
        only = [g for g in published if g.get("id") == bound]
        if only:
            return only

    q_tokens = [t for t in (query_text or "").lower().split()
                if t not in _STOP and len(t) > 2]

    matches: list[dict] = []
    for g in published:
        if workflow_id and workflow_id in (g.get("workflows") or []):
            matches.append(g)
            continue

        scoped_tenants = g.get("tenants") or []
        if scoped_tenants and tenant not in scoped_tenants:
            continue

        scoped_workflows = g.get("workflows") or []
        if scoped_workflows and workflow_id and workflow_id not in scoped_workflows:
            continue  # graph is restricted to other workflows

        tags = g.get("tags") or {}
        haystack = " ".join(str(v) for v in tags.values()).lower()

        if q_tokens and haystack:
            if any(tok in haystack for tok in q_tokens):
                matches.append(g)
        elif not scoped_workflows:
            matches.append(g)  # general-purpose graph, nothing to filter against

    seen: set[str] = set()
    out: list[dict] = []
    for g in matches:
        if g["id"] not in seen:
            seen.add(g["id"])
            out.append(g)
    return out
