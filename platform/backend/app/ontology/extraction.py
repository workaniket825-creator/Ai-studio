"""Auto-build / bottom-up extraction (spec §9.2).

Turns sources into candidate entities, relationship types, and edges, each carrying
confidence + provenance. Two extractors:

- structured  — schema inference from tabular/relational input (rows + foreign-key-like
  columns) → entity types, entities, and edges from *_id references.
- text        — entity/relationship extraction from documents. Uses an LLM when a model
  endpoint is configured (via the existing LiteLLM path); otherwise a deterministic
  heuristic (capitalized phrases + simple SVO patterns) so it always works offline.

Everything lands as `status="auto"` and must pass expert review + publish (spec §9.4/§9.5)
before OntologyProvider can read it. Skipped entirely in manual mode.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import ontology_store as store

_STOP = {"the", "and", "for", "with", "from", "this", "that", "into", "your", "our",
         "are", "was", "were", "has", "have", "will", "shall", "can", "may"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------- structured extraction (§9.2) -------------------------------
def extract_structured(gid: str, table: str, rows: list[dict], actor: str = "auto") -> dict:
    """Infer an entity type from a table and create entities; turn `*_id` columns into
    edges to referenced rows. Confidence is high for schema-derived facts.
    Re-importing the same table reuses existing entities/edges (no duplicates), and `*_id`
    references resolve to rows imported earlier from other tables."""
    if not rows:
        return {"entities": 0, "edges": 0, "entity_types": 0}
    etype = table.rstrip("s").capitalize() or "Row"
    cols = list(rows[0].keys())
    store.add_entity_type(gid, {"name": etype, "properties": cols})   # deduplicated by name

    id_col = next((c for c in cols if c in ("id", f"{table}_id", f"{etype.lower()}_id")), cols[0])
    ref_cols = [c for c in cols if c.endswith("_id") and c != id_col]

    def _norm(n) -> str:
        return " ".join(str(n or "").lower().split())

    existing = store.list_entities(gid)
    by_type_name = {(_norm(e.get("type")), _norm(e.get("name"))): e["id"] for e in existing}

    def _lookup_ref(rel: str, key: str) -> str | None:
        """Find an entity imported from another table whose id column equals `key`."""
        want_type = rel.capitalize()
        for e in existing:
            props = e.get("properties") or {}
            if str(props.get("id", props.get(f"{rel}_id", ""))) == key and \
                    (_norm(e.get("type")) == _norm(want_type) or not want_type):
                return e["id"]
        return None

    ecount = tcount = reused = unresolved = 0
    id_map: dict[str, str] = {}
    for r in rows:
        name = str(r.get("name") or r.get("title") or r.get(id_col) or "row")
        key = (_norm(etype), _norm(name))
        if key in by_type_name:
            id_map[str(r.get(id_col))] = by_type_name[key]
            reused += 1
            continue
        ent = store.add_entity(gid, {
            "type": etype, "name": name, "properties": r,
            "confidence": 0.95,
            "provenance": f"structured:{table}#{r.get(id_col)} @ {_now()}",
        }, status="auto")
        id_map[str(r.get(id_col))] = ent["id"]
        by_type_name[key] = ent["id"]
        ecount += 1

    edge_seen = {(x.get("source"), (x.get("relation") or "").lower(), x.get("target"))
                 for x in store.list_edges(gid)}
    for r in rows:
        src = id_map.get(str(r.get(id_col)))
        for rc in ref_cols:
            tgt_key = str(r.get(rc))
            if not src or not tgt_key or tgt_key == "None":
                continue
            rel = rc[:-3]  # supplier_id -> supplier
            tgt = id_map.get(tgt_key) or _lookup_ref(rel, tgt_key)
            if not tgt:
                unresolved += 1   # referenced row not imported yet; import that table, then re-run
                continue
            if (src, rel.lower(), tgt) in edge_seen:
                continue
            edge_seen.add((src, rel.lower(), tgt))
            store.add_relation_type(gid, {"name": rel, "source_type": etype})
            store.add_edge(gid, {
                "source": src, "target": tgt, "relation": rel,
                "confidence": 0.9, "provenance": f"structured:{table}.{rc} @ {_now()}",
            }, status="auto")
            tcount += 1
    return {"entities": ecount, "edges": tcount, "entity_types": 1,
            "reused_entities": reused, "unresolved_references": unresolved}


# ------------------------------- text extraction (§9.2) -------------------------------
async def extract_text(gid: str, text: str, source: str = "document", actor: str = "auto",
                       endpoint_id: str = "", instructions: str = "", job_id: str = "",
                       prompt: str = "") -> dict:
    """Extract candidate entities + relationships from free text.
    Uses the selected LLM model endpoint (or the ontology default) with optional custom
    instructions; falls back to a heuristic only if no endpoint is available.
    If job_id is given, reports real-time progress and honors cancellation via jobs registry."""
    from . import jobs
    def _cancelled() -> bool:
        return bool(job_id) and jobs.is_cancelled(job_id)
    def _prog(**kw):
        if job_id:
            jobs.update(job_id, **kw)

    _prog(phase="calling model")
    result = await _llm_extract(text, endpoint_id=endpoint_id, instructions=instructions, prompt_override=prompt)
    if result is None:
        result = _heuristic_extract(text)
    if _cancelled():
        return {"method": result["method"], "entities": 0, "edges": 0, "cancelled": True}

    total = len(result["entities"]) + len(result["relations"])
    _prog(phase="storing entities", total=total, processed=0, method=result["method"])

    # Seed with entities already in the graph so repeat mentions (this run or earlier runs)
    # resolve to the same entity instead of spawning duplicates. This is the dedup fix.
    def _norm(n: str) -> str:
        return " ".join((n or "").lower().split())
    name_to_id: dict[str, str] = {_norm(x["name"]): x["id"] for x in store.list_entities(gid)}
    created = 0
    done = 0
    for e in result["entities"]:
        if _cancelled():
            return {"method": result["method"], "entities": created, "edges": 0, "cancelled": True}
        key = _norm(e.get("name", ""))
        done += 1
        if not key or key in name_to_id:
            _prog(processed=done, entities=created)
            continue  # already exists in the graph or earlier in this run — skip duplicate
        ent = store.add_entity(gid, {
            "type": e.get("type", "Concept"), "name": e["name"], "properties": {},
            "confidence": float(e.get("confidence", 0.6)),
            "provenance": f"text:{source} ({result['method']}) @ {_now()}",
        }, status="auto")
        name_to_id[key] = ent["id"]
        created += 1
        _prog(processed=done, entities=created)

    edges = 0
    edge_seen: set = set()
    # seed with existing edges so re-extraction doesn't duplicate relationships
    for x in store.list_edges(gid):
        edge_seen.add((x.get("source"), x.get("relation", "").lower(), x.get("target")))
    _prog(phase="storing relationships")
    for r in result["relations"]:
        if _cancelled():
            return {"method": result["method"], "entities": created, "edges": edges, "cancelled": True}
        s = name_to_id.get(_norm(str(r.get("source", ""))))
        t = name_to_id.get(_norm(str(r.get("target", ""))))
        done += 1
        _prog(processed=done)
        if not s or not t:
            continue
        sem = (s, str(r["relation"]).lower(), t)
        if sem in edge_seen:
            continue  # relationship already present — skip duplicate
        edge_seen.add(sem)
        store.add_relation_type(gid, {"name": r["relation"]})
        store.add_edge(gid, {
            "source": s, "target": t, "relation": r["relation"],
            "confidence": float(r.get("confidence", 0.55)),
            "provenance": f"text:{source} ({result['method']}) @ {_now()}",
        }, status="auto")
        edges += 1
        _prog(edges=edges)

    return {"method": result["method"], "entities": created, "edges": edges}


async def _llm_extract(text: str, endpoint_id: str = "", instructions: str = "", prompt_override: str = ""):
    """Use a selected/configured model endpoint to extract JSON {entities, relations}.
    Endpoint resolution: explicit endpoint_id -> ontology default -> first available.
    Returns None if no endpoint/model or the call fails (caller falls back to heuristic)."""
    try:
        from ..endpoints import list_endpoints, get_full, litellm_call_args
        from .ontology_config import get_config
        eps = list_endpoints()
        if not eps:
            return None
        chosen = endpoint_id or get_config().get("extraction_model") or ""
        ep = get_full(chosen) if chosen else None
        if ep is None:
            ep = get_full(eps[0]["id"])
        args = litellm_call_args(ep)
        import litellm
        extra = f"\n\nAdditional instructions from the user:\n{instructions.strip()}" if instructions.strip() else ""
        # Base prompt comes from config (editable + scientific); a per-call `prompt_override`
        # (passed via instructions starting with the full template) is respected if it contains
        # the {text} placeholder. Otherwise the config template is filled.
        template = get_config().get("extraction_prompt") or ""
        if prompt_override and "{text}" in prompt_override:
            # user-edited full prompt template from the UI
            prompt = prompt_override.replace("{instructions}", extra).replace("{text}", text[:6000])
        elif template and "{text}" in template:
            prompt = template.replace("{instructions}", extra).replace("{text}", text[:6000])
        else:
            prompt = (
                "Extract a knowledge graph (ontology + taxonomy) from the text. Return ONLY JSON of the form "
                '{"entities":[{"name","type","confidence"}],'
                '"relations":[{"source","target","relation","confidence"}]}. '
                "Use entity names exactly as they appear. Infer meaningful entity types and relationship "
                "labels to form a useful taxonomy." + extra + "\n\nTEXT:\n" + text[:6000])
        resp = await litellm.acompletion(
            model=args["model"],
            messages=[{"role": "system", "content": "You are a precise information extractor."},
                      {"role": "user", "content": prompt}],
            **args["params"])
        raw = resp.choices[0].message.content or ""
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
        return {"method": "llm", "entities": data.get("entities", []),
                "relations": data.get("relations", [])}
    except Exception:
        return None


def _heuristic_extract(text: str) -> dict:
    """Deterministic offline extractor: capitalized multi-word phrases as entities,
    simple 'X <verb> Y' patterns as relations. Lower confidence than structured/LLM."""
    phrases = re.findall(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\b", text)
    seen, entities = set(), []
    for p in phrases:
        key = p.lower()
        if key in seen or key in _STOP or len(p) < 3:
            continue
        seen.add(key)
        entities.append({"name": p, "type": "Concept", "confidence": 0.5})
    relations = []
    for m in re.finditer(
            r"\b([A-Z][a-zA-Z0-9 ]+?)\s+(supplies|owns|manages|reports to|belongs to|"
            r"depends on|uses|provides|contains|part of)\s+([A-Z][a-zA-Z0-9 ]+)", text):
        relations.append({"source": m.group(1).strip(), "target": m.group(3).strip(),
                          "relation": m.group(2).strip().replace(" ", "_"), "confidence": 0.45})
    return {"method": "heuristic", "entities": entities[:50], "relations": relations[:50]}
