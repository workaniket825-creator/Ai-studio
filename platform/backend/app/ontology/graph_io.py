"""Graph export / import — portable JSON round-trip.

Export: turns a graph's PUBLISHED snapshot into a single, self-contained JSON
document. Edges reference entities by NAME rather than internal id, so the
document is portable across graphs/environments. Indented JSON is used
instead of a free-form doc format because it needs to round-trip losslessly
back through import — a human can still read it fine, and nothing is lost.

Import: takes that document and rebuilds a graph directly — NO LLM or
heuristic extraction runs. Everything in an export was already approved
(published snapshots only ever contain approved items), so import writes
entities/edges as status="approved" and, by default, immediately creates +
publishes a version so the graph is usable right away.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import ontology_store as store

FORMAT_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    id_to_name = {e["id"]: e["name"] for e in entities}

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
            {"name": e["name"], "type": e["type"], "properties": e.get("properties", {}),
             "confidence": e.get("confidence", 1.0), "provenance": e.get("provenance", "")}
            for e in entities
        ],
        "edges": [
            {"source_name": id_to_name[x["source"]], "target_name": id_to_name[x["target"]],
             "relation": x["relation"], "properties": x.get("properties", {}),
             "confidence": x.get("confidence", 1.0), "provenance": x.get("provenance", "")}
            for x in edges
            if x["source"] in id_to_name and x["target"] in id_to_name
        ],
    }


def import_graph(payload: dict, actor: str = "admin", publish: bool = True,
                 name_override: str = "") -> dict:
    if not isinstance(payload, dict) or "entities" not in payload:
        raise ValueError("not a valid graph export document")

    meta = payload.get("graph", {})
    g = store.create_graph({
        "name": name_override or meta.get("name", "Imported Graph"),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", {}), "tenants": meta.get("tenants", []),
        "workflows": meta.get("workflows", []),
    }, actor=actor)
    gid = g["id"]

    for t in payload.get("entity_types", []):
        store.add_entity_type(gid, t, actor=actor)
    for t in payload.get("relation_types", []):
        store.add_relation_type(gid, t, actor=actor)

    name_to_id: dict[str, str] = {}
    for e in payload.get("entities", []):
        ent = store.add_entity(gid, {
            "type": e.get("type", "Concept"), "name": e["name"],
            "properties": e.get("properties", {}),
            "confidence": e.get("confidence", 1.0),
            "provenance": e.get("provenance", ""),
        }, status="approved", actor=actor)
        name_to_id[e["name"]] = ent["id"]

    edges_created = skipped = 0
    for x in payload.get("edges", []):
        s = name_to_id.get(x.get("source_name", ""))
        t = name_to_id.get(x.get("target_name", ""))
        if not s or not t:
            skipped += 1
            continue
        store.add_relation_type(gid, {"name": x["relation"]}, actor=actor)
        store.add_edge(gid, {
            "source": s, "target": t, "relation": x["relation"],
            "properties": x.get("properties", {}),
            "confidence": x.get("confidence", 1.0),
            "provenance": x.get("provenance", ""),
        }, status="approved", actor=actor)
        edges_created += 1

    result = {
        "graph_id": gid, "name": g["name"],
        "entities_created": len(name_to_id), "edges_created": edges_created,
        "edges_skipped": skipped, "published": False,
    }
    if publish:
        v = store.create_version(gid, actor=actor)
        store.transition_version(v["id"], "published", actor=actor)
        result["published"] = True
        result["version_id"] = v["id"]
    return result
