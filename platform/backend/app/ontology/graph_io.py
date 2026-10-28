"""Graph export / import — portable JSON round-trip.

Export: turns a graph's PUBLISHED snapshot (or, with source=live, its current approved state)
into a single, self-contained JSON document. Edges reference entities by NAME (plus the
entity TYPE since format 1.1) rather than internal id, so the document is portable across
graphs/environments and same-named entities of different types stay distinct.

Import: rebuilds a graph from that document directly — NO LLM or heuristic extraction runs.
Everything in an export was already approved, so import writes entities/edges as
status="approved" and, by default, immediately creates + publishes a version so the graph is
usable right away.

Accepted inputs (all normalised by `unwrap`):
  * the export document itself (format 1.0 or 1.1)
  * the UI request body  {"snapshot": <export document>}
  * a legacy wrapper     {"graph": <export document>}
  * a raw published snapshot {"entities": [{id,name,type..}], "edges": [{source,target,relation..}]}

Robustness: bad items are skipped and reported in `warnings` (never a 500); a document with no
valid entity is rejected with ValueError (-> HTTP 400 in the router). The whole import is
written with ONE store save under the store's write lock (fast for large graphs, one audit
entry, no partial graph if something fails before the save).

Scoping: the source graph's workflow/tenant scoping is NOT copied by default (those ids belong
to the source environment, and copying them would ground the same workflows twice); it is kept
under `import_meta` for reference. Pass keep_scoping=True to copy it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import ontology_store as store

FORMAT_VERSION = "1.1"
SUPPORTED_FORMATS = {"1.0", "1.1"}
_MAX_WARNINGS = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split()).lower()


# ------------------------------------------------------------------------------- export
def export_graph(gid: str, source: str = "published") -> dict:
    g = store.get_graph(gid)
    if not g:
        raise ValueError(f"graph '{gid}' not found")

    if source == "published":
        snap = store.published_snapshot(gid)
        if not snap:
            raise ValueError(
                "this graph has never been published — nothing to export. "
                "Use source=live to export the current approved draft state instead."
            )
        entities, edges = snap["entities"], snap["edges"]
        etypes, rtypes = snap["entity_types"], snap["relation_types"]
    else:
        entities = store.list_entities(gid, status="approved")
        edges = store.list_edges(gid, status="approved")
        etypes = store.list_entity_types(gid)
        rtypes = store.list_relation_types(gid)

    by_id = {e["id"]: e for e in entities}

    return {
        "format_version": FORMAT_VERSION,
        "exported_at": _now(),
        "source": source,
        "graph": {
            "name": g["name"], "description": g.get("description", ""),
            "tags": g.get("tags", {}), "tenants": g.get("tenants", []),
            "workflows": g.get("workflows", []),
        },
        "entity_types": [
            {"name": t["name"], "description": t.get("description", ""),
             "properties": t.get("properties", [])}
            for t in etypes
        ],
        "relation_types": [
            {"name": t["name"], "source_type": t.get("source_type", ""),
             "target_type": t.get("target_type", ""), "description": t.get("description", "")}
            for t in rtypes
        ],
        "entities": [
            {"name": e["name"], "type": e.get("type", ""), "properties": e.get("properties", {}),
             "confidence": e.get("confidence", 1.0), "provenance": e.get("provenance", "")}
            for e in entities
        ],
        "edges": [
            {"source_name": by_id[x["source"]]["name"], "source_type": by_id[x["source"]].get("type", ""),
             "target_name": by_id[x["target"]]["name"], "target_type": by_id[x["target"]].get("type", ""),
             "relation": x["relation"], "properties": x.get("properties", {}),
             "confidence": x.get("confidence", 1.0), "provenance": x.get("provenance", "")}
            for x in edges
            if x["source"] in by_id and x["target"] in by_id
        ],
    }


# ------------------------------------------------------------------------------- import
def unwrap(body: Any) -> Any:
    """Return the export document from any accepted request shape (see module doc)."""
    if not isinstance(body, dict):
        return body
    snap = body.get("snapshot")
    if isinstance(snap, dict):
        return snap
    g = body.get("graph")
    if "entities" not in body and isinstance(g, dict) and "entities" in g:
        return g                       # legacy {"graph": <document>}
    return body                        # the document itself ("graph" there = metadata)


def _confidence(v: Any) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return 1.0


def _props(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _str(v: Any) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) else ""


def _unique_name(name: str, existing: set[str]) -> str:
    if _norm(name) not in existing:
        return name
    n = 1
    while True:
        cand = f"{name} (imported)" if n == 1 else f"{name} (imported {n})"
        if _norm(cand) not in existing:
            return cand
        n += 1


def import_graph(payload: Any, actor: str = "admin", publish: bool = True,
                 name_override: str = "", keep_scoping: bool = False) -> dict:
    doc = unwrap(payload)
    if not isinstance(doc, dict):
        raise ValueError("not a valid graph export document: expected a JSON object")
    fmt = str(doc.get("format_version") or "")
    if fmt and fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported export format_version '{fmt}' "
                         f"(supported: {', '.join(sorted(SUPPORTED_FORMATS))})")
    raw_entities = doc.get("entities")
    if not isinstance(raw_entities, list):
        raise ValueError("not a valid graph export document: 'entities' list is missing — "
                         "choose a file produced by Export")
    raw_edges = doc.get("edges") if isinstance(doc.get("edges"), list) else []
    meta = doc.get("graph") if isinstance(doc.get("graph"), dict) else {}

    warnings: list[str] = []

    def warn(msg: str) -> None:
        if len(warnings) < _MAX_WARNINGS:
            warnings.append(msg)

    # ---- entities: validate, dedupe by (name, type) ------------------------------------
    ents: list[dict] = []
    by_key: dict[tuple, int] = {}              # (name_norm, type_norm) -> index in ents
    by_name: dict[str, list[int]] = {}         # name_norm -> indexes (detect ambiguity)
    by_src_id: dict[str, int] = {}             # raw-snapshot id -> index
    skipped_entities = 0
    for i, e in enumerate(raw_entities):
        if not isinstance(e, dict):
            skipped_entities += 1
            warn(f"entity #{i}: not an object — skipped")
            continue
        name = _str(e.get("name"))
        if not name:
            skipped_entities += 1
            warn(f"entity #{i}: missing name — skipped")
            continue
        etype = _str(e.get("type")) or "Concept"
        key = (_norm(name), _norm(etype))
        if key in by_key:
            if e.get("id"):
                by_src_id[str(e["id"])] = by_key[key]
            warn(f"entity '{name}' ({etype}) appears more than once — kept the first")
            continue
        by_key[key] = len(ents)
        by_name.setdefault(_norm(name), []).append(len(ents))
        if e.get("id"):
            by_src_id[str(e["id"])] = len(ents)
        ents.append({"name": name, "type": etype, "properties": _props(e.get("properties")),
                     "confidence": _confidence(e.get("confidence", 1.0)),
                     "provenance": _str(e.get("provenance"))})
    if not ents:
        raise ValueError("the document contains no valid entities (each needs a non-empty "
                         "'name') — nothing to import")

    def resolve(name: Any, etype: Any, raw_id: Any) -> tuple[int | None, str]:
        if raw_id is not None and str(raw_id) in by_src_id and not name:
            return by_src_id[str(raw_id)], ""
        n = _norm(name)
        if not n:
            return None, (f"unknown entity id '{raw_id}'" if raw_id is not None else "missing endpoint")
        if etype:
            idx = by_key.get((n, _norm(etype)))
            if idx is not None:
                return idx, ""
        cands = by_name.get(n) or []
        if len(cands) == 1:
            return cands[0], ""
        if not cands:
            return None, f"unknown entity '{name}'"
        return None, f"ambiguous entity '{name}' ({len(cands)} types) — add source/target type"

    # ---- edges: validate, resolve, dedupe ------------------------------------------------
    edges: list[dict] = []
    seen_edges: set[tuple] = set()
    skipped_edges = 0
    for i, x in enumerate(raw_edges):
        if not isinstance(x, dict):
            skipped_edges += 1
            warn(f"edge #{i}: not an object — skipped")
            continue
        relation = _str(x.get("relation"))
        if not relation:
            skipped_edges += 1
            warn(f"edge #{i}: missing relation — skipped")
            continue
        # export format uses *_name/*_type; a raw snapshot uses source/target ids
        s_name = x.get("source_name")
        t_name = x.get("target_name")
        s_idx, s_err = resolve(s_name, x.get("source_type"), None if s_name else x.get("source"))
        t_idx, t_err = resolve(t_name, x.get("target_type"), None if t_name else x.get("target"))
        if s_idx is None or t_idx is None:
            skipped_edges += 1
            warn(f"edge #{i} ({s_name or x.get('source')} -{relation}-> "
                 f"{t_name or x.get('target')}): {s_err or t_err} — skipped")
            continue
        key = (s_idx, _norm(relation), t_idx)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append({"s": s_idx, "t": t_idx, "relation": relation,
                      "properties": _props(x.get("properties")),
                      "confidence": _confidence(x.get("confidence", 1.0)),
                      "provenance": _str(x.get("provenance"))})

    # ---- types: from the document, plus any type actually used ---------------------------
    etypes: dict[str, dict] = {}
    for t in doc.get("entity_types") or []:
        if isinstance(t, dict) and _str(t.get("name")):
            props = t.get("properties") if isinstance(t.get("properties"), list) else []
            etypes.setdefault(_norm(t["name"]), {"name": _str(t["name"]),
                                                 "description": _str(t.get("description")),
                                                 "properties": props})
    for e in ents:
        etypes.setdefault(_norm(e["type"]), {"name": e["type"], "description": "", "properties": []})
    rtypes: dict[str, dict] = {}
    for t in doc.get("relation_types") or []:
        if isinstance(t, dict) and _str(t.get("name")):
            rtypes.setdefault(_norm(t["name"]), {"name": _str(t["name"]),
                                                 "source_type": _str(t.get("source_type")),
                                                 "target_type": _str(t.get("target_type")),
                                                 "description": _str(t.get("description"))})
    for x in edges:
        rtypes.setdefault(_norm(x["relation"]), {
            "name": x["relation"], "source_type": ents[x["s"]]["type"],
            "target_type": ents[x["t"]]["type"], "description": ""})

    # ---- single write under the store lock -----------------------------------------------
    now = _now()
    with store._WRITE_LOCK:
        db = store._load()
        existing_names = {_norm(g.get("name")) for g in db["graphs"].values()}
        requested = _str(name_override) or _str(meta.get("name")) or "Imported Graph"
        name = _unique_name(requested, existing_names)
        gid = store._id("graph")
        tags = meta.get("tags") if isinstance(meta.get("tags"), (dict, list)) else {}
        src_tenants = meta.get("tenants") if isinstance(meta.get("tenants"), list) else []
        src_workflows = meta.get("workflows") if isinstance(meta.get("workflows"), list) else []
        db["graphs"][gid] = {
            "id": gid, "name": name, "description": _str(meta.get("description")),
            "status": "draft", "published_version": None, "tags": tags,
            "tenants": src_tenants if keep_scoping else [],
            "workflows": src_workflows if keep_scoping else [],
            "created_by": actor, "created_at": now, "updated_at": now,
            "import_meta": {"source_name": _str(meta.get("name")), "format_version": fmt or "1.0",
                            "exported_at": _str(doc.get("exported_at")), "imported_at": now,
                            "source_tenants": src_tenants, "source_workflows": src_workflows,
                            "scoping_copied": bool(keep_scoping)},
        }
        for t in etypes.values():
            tid = store._id("etype")
            db["entity_types"][tid] = {"id": tid, "graph_id": gid, "name": t["name"],
                                       "description": t["description"],
                                       "properties": t["properties"], "created_at": now}
        for t in rtypes.values():
            tid = store._id("rtype")
            db["relation_types"][tid] = {"id": tid, "graph_id": gid, "name": t["name"],
                                         "source_type": t["source_type"],
                                         "target_type": t["target_type"],
                                         "description": t["description"], "created_at": now}
        ids: list[str] = []
        for e in ents:
            eid = store._id("ent")
            ids.append(eid)
            db["entities"][eid] = {"id": eid, "graph_id": gid, "type": e["type"], "name": e["name"],
                                   "properties": e["properties"], "confidence": e["confidence"],
                                   "provenance": e["provenance"] or f"import:{fmt or '1.0'} @ {now}",
                                   "status": "approved", "created_by": actor,
                                   "created_at": now, "updated_at": now}
        for x in edges:
            edid = store._id("edge")
            db["edges"][edid] = {"id": edid, "graph_id": gid, "source": ids[x["s"]],
                                 "target": ids[x["t"]], "relation": x["relation"],
                                 "properties": x["properties"], "confidence": x["confidence"],
                                 "provenance": x["provenance"] or f"import:{fmt or '1.0'} @ {now}",
                                 "status": "approved", "created_by": actor, "created_at": now}
        store._audit(db, actor, "import_graph", gid,
                     f"{name}: {len(ents)} entities, {len(edges)} edges "
                     f"({skipped_entities + skipped_edges} skipped)")
        store._save(db)

    result = {
        "graph_id": gid, "id": gid, "name": name,
        "entities_created": len(ents), "edges_created": len(edges),
        "entity_types": len(etypes), "relation_types": len(rtypes),
        "entities_skipped": skipped_entities, "edges_skipped": skipped_edges,
        "warnings": warnings, "scoping_copied": bool(keep_scoping),
        "renamed": name != requested, "published": False,
    }
    if publish:
        try:
            v = store.create_version(gid, actor=actor)
            store.transition_version(v["id"], "published", actor=actor)
            result["published"] = True
            result["version_id"] = v["id"]
        except Exception as e:   # graph is imported; report why it is not live yet
            result["publish_error"] = str(e)
    return result
