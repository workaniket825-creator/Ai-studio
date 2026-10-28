"""Ontology knowledge-graph store — JSON-backed (spec A§9).

Single source of truth for all graph authoring state:
  graphs, entity types, relation types, entities, edges,
  taxonomy nodes, versions, and audit log.

Persisted to a single JSON file (zero dependencies). A real deployment
would swap _load/_save for a database transaction; everything else stays.

Naming: ontology_store (lowercase) — matches all internal imports.
"""
from __future__ import annotations

import json
import threading
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ------------------------------ storage path -----------------------------------
_DB_DIR = Path(os.environ.get("ONTOLOGY_DB_DIR", Path(__file__).parent / "_data"))
_DB_PATH = _DB_DIR / "ontology_db.json"

# ------------------------------ valid state sets ----------------------------
GRAPH_STATES = {"draft", "active", "archived", "published"}
VERSION_STATES = {"draft", "review", "published", "archived"}
ITEM_STATES = {"auto", "pending_review", "approved", "rejected"}


# ------------------------------ persistence helpers --------------------------
def _empty_db() -> dict:
    return {
        "graphs": {},          # graph_id -> graph metadata dict
        "entity_types": {},    # etype_id -> {graph_id, name, properties:[str]}
        "relation_types": {},  # rtype_id -> {graph_id, name, source_type, target_type}
        "entities": {},        # entity_id -> entity dict
        "edges": {},           # edge_id -> edge dict
        "taxonomy_nodes": {},  # node_id -> taxonomy node dict
        "versions": {},        # version_id -> version dict (with snapshot)
        "audit": [],           # list of audit event dicts
    }


def _load() -> dict:
    """Load the ontology DB via the configured backend (json | postgres), as one doc."""
    from ..store import make_repo
    repo = make_repo("ontology_db", "id")
    doc = repo.get("_db")
    if not doc:
        db = _empty_db()
        _save(db)
        return db
    db = doc.get("value", _empty_db())
    for key, val in _empty_db().items():
        db.setdefault(key, val)
    return db


def _save(db: dict) -> None:
    """Persist the ontology DB via the configured backend."""
    from ..store import make_repo
    repo = make_repo("ontology_db", "id")
    repo.upsert({"id": "_db", "value": db})


def _id(prefix: str = "") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(db: dict, actor: str, action: str, target: str, detail: str = "") -> None:
    db["audit"].append({
        "ts": _now(), "actor": actor, "action": action,
        "target": target, "detail": detail,
    })
    # Keep the audit log bounded
    if len(db["audit"]) > 5000:
        db["audit"] = db["audit"][-5000:]


# ============================ GRAPHS =========================================

def create_graph(data: dict, actor: str = "admin") -> dict:
    """Create a new knowledge graph."""
    db = _load()
    gid = data.get("id") or _id("graph")
    if gid in db["graphs"]:
        raise ValueError(f"graph '{gid}' already exists")
    g = {
        "id": gid,
        "name": data.get("name", "Untitled Graph"),
        "description": data.get("description", ""),
        "status": "draft",
        "published_version": None,
        "tags": data.get("tags") or {},
        "tenants": data.get("tenants") or [],
        "workflows": data.get("workflows") or [],
        "created_by": actor,
        "created_at": _now(),
        "updated_at": _now(),
    }
    db["graphs"][gid] = g
    _audit(db, actor, "create_graph", gid, g["name"])
    _save(db)
    return g


def list_graphs() -> list[dict]:
    """Return all graph metadata dicts (lightweight, no snapshots)."""
    return list(_load()["graphs"].values())


def get_graph(gid: str) -> dict | None:
    return _load()["graphs"].get(gid)


def update_graph(gid: str, patch: dict, actor: str = "admin") -> dict:
    db = _load()
    g = db["graphs"].get(gid)
    if not g:
        raise ValueError(f"graph '{gid}' not found")
    for k in ("name", "description", "tags", "tenants", "workflows", "status"):
        if k in patch:
            g[k] = patch[k]
    g["updated_at"] = _now()
    _audit(db, actor, "update_graph", gid, "graph metadata updated")
    _save(db)
    return g


def delete_graph(gid: str, actor: str = "admin") -> bool:
    db = _load()
    if gid not in db["graphs"]:
        return False
    del db["graphs"][gid]
    # Cascade-delete all dependent data
    for coll in ("entity_types", "relation_types", "entities", "edges", "taxonomy_nodes"):
        db[coll] = {k: v for k, v in db[coll].items() if v.get("graph_id") != gid}
    db["versions"] = {k: v for k, v in db["versions"].items() if v.get("graph_id") != gid}
    _audit(db, actor, "delete_graph", gid, "graph and all data deleted")
    _save(db)
    return True


# ============================ ENTITY TYPES ====================================

def add_entity_type(gid: str, data: dict, actor: str = "admin") -> dict:
    db = _load()
    # Deduplicate by name within graph (repeat structured imports reuse the type)
    name = data.get("name", "Unknown")
    existing = next((t for t in db["entity_types"].values()
                     if t["graph_id"] == gid and t["name"] == name), None)
    if existing:
        props = list(existing.get("properties") or [])
        for p in data.get("properties") or []:
            if p not in props:
                props.append(p)
        if props != (existing.get("properties") or []):
            existing["properties"] = props
            _save(db)
        return existing
    tid = _id("etype")
    t = {
        "id": tid, "graph_id": gid,
        "name": data.get("name", "Unknown"),
        "description": data.get("description", ""),
        "properties": data.get("properties") or [],
        "created_at": _now(),
    }
    db["entity_types"][tid] = t
    _audit(db, actor, "add_entity_type", tid, t["name"])
    _save(db)
    return t


def list_entity_types(gid: str) -> list[dict]:
    return [t for t in _load()["entity_types"].values() if t["graph_id"] == gid]


def update_entity_type(tid: str, patch: dict, actor: str = "admin") -> dict | None:
    db = _load()
    t = db["entity_types"].get(tid)
    if not t:
        return None
    for k in ("name", "description", "properties"):
        if k in patch:
            t[k] = patch[k]
    _audit(db, actor, "update_entity_type", tid, "entity type edited")
    _save(db)
    return t


def delete_entity_type(tid: str, actor: str = "admin") -> bool:
    db = _load()
    if tid not in db["entity_types"]:
        return False
    del db["entity_types"][tid]
    _audit(db, actor, "delete_entity_type", tid, "entity type removed")
    _save(db)
    return True


# ============================ RELATION TYPES ==================================

def add_relation_type(gid: str, data: dict, actor: str = "admin") -> dict:
    db = _load()
    # Deduplicate by name within graph
    name = data.get("name", "related_to")
    existing = next(
        (r for r in db["relation_types"].values()
         if r["graph_id"] == gid and r["name"] == name), None
    )
    if existing:
        return existing
    tid = _id("rtype")
    t = {
        "id": tid, "graph_id": gid,
        "name": name,
        "source_type": data.get("source_type", ""),
        "target_type": data.get("target_type", ""),
        "description": data.get("description", ""),
        "created_at": _now(),
    }
    db["relation_types"][tid] = t
    _audit(db, actor, "add_relation_type", tid, name)
    _save(db)
    return t


def list_relation_types(gid: str) -> list[dict]:
    return [t for t in _load()["relation_types"].values() if t["graph_id"] == gid]


def update_relation_type(tid: str, patch: dict, actor: str = "admin") -> dict | None:
    db = _load()
    t = db["relation_types"].get(tid)
    if not t:
        return None
    for k in ("name", "source_type", "target_type", "description"):
        if k in patch:
            t[k] = patch[k]
    _audit(db, actor, "update_relation_type", tid, "relation type edited")
    _save(db)
    return t


def delete_relation_type(tid: str, actor: str = "admin") -> bool:
    db = _load()
    if tid not in db["relation_types"]:
        return False
    del db["relation_types"][tid]
    _audit(db, actor, "delete_relation_type", tid, "relation type removed")
    _save(db)
    return True


# ============================ ENTITIES ========================================

def add_entity(gid: str, data: dict, status: str = "auto",
               actor: str = "admin") -> dict:
    db = _load()
    eid = _id("ent")
    e: dict[str, Any] = {
        "id": eid, "graph_id": gid,
        "type": data.get("type", "Concept"),
        "name": data.get("name", ""),
        "properties": data.get("properties") or {},
        "confidence": float(data.get("confidence", 1.0)),
        "provenance": data.get("provenance", ""),
        "status": status,
        "created_by": actor,
        "created_at": _now(),
        "updated_at": _now(),
    }
    db["entities"][eid] = e
    _audit(db, actor, "add_entity", eid, e["name"])
    _save(db)
    return e


def list_entities(gid: str, status: str | None = None) -> list[dict]:
    ents = [e for e in _load()["entities"].values() if e["graph_id"] == gid]
    if status:
        ents = [e for e in ents if e.get("status") == status]
    return ents


def get_entity(eid: str) -> dict | None:
    return _load()["entities"].get(eid)


def update_entity(eid: str, patch: dict, actor: str = "expert") -> dict | None:
    db = _load()
    e = db["entities"].get(eid)
    if not e:
        return None
    for k in ("name", "type", "properties", "confidence", "provenance", "status"):
        if k in patch:
            e[k] = patch[k]
    e["updated_at"] = _now()
    _audit(db, actor, "update_entity", eid, "entity edited")
    _save(db)
    return e


def delete_entity(eid: str, actor: str = "expert") -> bool:
    db = _load()
    if eid not in db["entities"]:
        return False
    del db["entities"][eid]
    _audit(db, actor, "delete_entity", eid, "entity removed")
    _save(db)
    return True


# ============================ EDGES ===========================================

def add_edge(gid: str, data: dict, status: str = "auto",
             actor: str = "admin") -> dict:
    db = _load()
    edid = _id("edge")
    ed: dict[str, Any] = {
        "id": edid, "graph_id": gid,
        "source": data.get("source", ""),
        "target": data.get("target", ""),
        "relation": data.get("relation", "related_to"),
        "properties": data.get("properties") or {},
        "confidence": float(data.get("confidence", 1.0)),
        "provenance": data.get("provenance", ""),
        "status": status,
        "created_by": actor,
        "created_at": _now(),
    }
    db["edges"][edid] = ed
    _audit(db, actor, "add_edge", edid, f"{ed['source']} -{ed['relation']}-> {ed['target']}")
    _save(db)
    return ed


def list_edges(gid: str, status: str | None = None) -> list[dict]:
    edges = [e for e in _load()["edges"].values() if e["graph_id"] == gid]
    if status:
        edges = [e for e in edges if e.get("status") == status]
    return edges


def get_edge(edid: str) -> dict | None:
    return _load()["edges"].get(edid)


def update_edge(edid: str, patch: dict, actor: str = "expert") -> dict | None:
    db = _load()
    e = db["edges"].get(edid)
    if not e:
        return None
    for k in ("relation", "source", "target", "properties", "confidence", "status"):
        if k in patch:
            e[k] = patch[k]
    _audit(db, actor, "update_edge", edid, "edge edited")
    _save(db)
    return e


def delete_edge(edid: str, actor: str = "expert") -> bool:
    db = _load()
    if edid not in db["edges"]:
        return False
    del db["edges"][edid]
    _audit(db, actor, "delete_edge", edid, "edge removed")
    _save(db)
    return True


# ============================ TAXONOMY ========================================

def add_taxonomy_node(gid: str, data: dict, actor: str = "admin") -> dict:
    db = _load()
    nid = _id("tax")
    n = {
        "id": nid, "graph_id": gid,
        "label": data.get("label", ""),
        "parent_id": data.get("parent_id"),
        "description": data.get("description", ""),
        "status": data.get("status", "approved"),
        "created_at": _now(),
    }
    db["taxonomy_nodes"][nid] = n
    _audit(db, actor, "add_taxonomy", nid, n["label"])
    _save(db)
    return n


def list_taxonomy_nodes(gid: str) -> list[dict]:
    return [n for n in _load()["taxonomy_nodes"].values() if n["graph_id"] == gid]


def delete_taxonomy_node(nid: str, actor: str = "expert") -> bool:
    db = _load()
    if nid not in db["taxonomy_nodes"]:
        return False
    del db["taxonomy_nodes"][nid]
    _audit(db, actor, "delete_taxonomy", nid, "taxonomy node removed")
    _save(db)
    return True


# ============================ ANALYTICS =======================================

def analytics(gid: str) -> dict:
    """Graph data-science summary: sizes, density, degree centrality (top hubs),
    type distribution, status breakdown, connected components. Computed on the fly."""
    ents = list_entities(gid)
    edges = list_edges(gid)
    n, m = len(ents), len(edges)
    deg: dict[str, int] = {e["id"]: 0 for e in ents}
    adj: dict[str, set] = {e["id"]: set() for e in ents}
    for ed in edges:
        s, t = ed.get("source"), ed.get("target")
        if s in deg:
            deg[s] += 1
        if t in deg:
            deg[t] += 1
        if s in adj and t in adj:
            adj[s].add(t)
            adj[t].add(s)
    name_by = {e["id"]: e for e in ents}
    top = sorted(deg.items(), key=lambda kv: kv[1], reverse=True)[:8]
    hubs = [{"id": i, "name": name_by[i]["name"], "type": name_by[i]["type"],
             "degree": d} for i, d in top if i in name_by and d > 0]
    # density for undirected simple graph
    density = (2 * m) / (n * (n - 1)) if n > 1 else 0.0
    # connected components (BFS)
    seen, comps = set(), 0
    for node in adj:
        if node in seen:
            continue
        comps += 1
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj[cur] - seen)
    # distributions
    type_dist: dict[str, int] = {}
    status_dist: dict[str, int] = {}
    for e in ents:
        type_dist[e["type"]] = type_dist.get(e["type"], 0) + 1
        st = "pending_review" if e["status"] == "auto" else e["status"]
        status_dist[st] = status_dist.get(st, 0) + 1
    rel_dist: dict[str, int] = {}
    for ed in edges:
        rel_dist[ed["relation"]] = rel_dist.get(ed["relation"], 0) + 1
    avg_deg = (sum(deg.values()) / n) if n else 0.0
    return {
        "entities": n, "edges": m, "density": round(density, 4),
        "avg_degree": round(avg_deg, 2), "components": comps,
        "top_hubs": hubs, "type_distribution": type_dist,
        "status_distribution": status_dist, "relation_distribution": rel_dist,
    }


# ============================ ITEM REVIEW (A§9.4) =============================

def set_item_status(kind: str, item_id: str, status: str,
                    actor: str = "expert") -> dict | None:
    if status not in ITEM_STATES:
        raise ValueError(f"invalid item status '{status}'")
    coll = {"entity": "entities", "edge": "edges",
            "taxonomy": "taxonomy_nodes"}[kind]
    db = _load()
    item = db[coll].get(item_id)
    if not item:
        return None
    item["status"] = status
    _audit(db, actor, "item_status", item_id, f"{kind} -> {status}")
    _save(db)
    return item


def bulk_approve(gid: str, min_confidence: float,
                 actor: str = "expert") -> int:
    db = _load()
    n = 0
    for coll in ("entities", "edges"):
        for it in db[coll].values():
            if (it["graph_id"] == gid
                    and it["status"] in ("auto", "pending_review")
                    and it.get("confidence", 0) >= min_confidence):
                it["status"] = "approved"
                n += 1
    _audit(db, actor, "bulk_approve", gid, f"approved {n} items >= {min_confidence}")
    _save(db)
    return n


def review_queue(gid: str | None = None) -> list[dict]:
    db = _load()
    out = []
    for kind, coll in (("entity", "entities"), ("edge", "edges")):
        for it in db[coll].values():
            if (it["status"] in ("auto", "pending_review")
                    and (gid is None or it["graph_id"] == gid)):
                out.append({**it, "_kind": kind})
    return sorted(out, key=lambda x: x.get("confidence", 0))


# ============================ VERSIONS & PUBLISH (A§9.5, A§9.6) ==============

def create_version(gid: str, actor: str = "expert") -> dict:
    db = _load()
    v = {
        "id": _id("ver"), "graph_id": gid, "state": "draft",
        "created_by": actor, "created_at": _now(),
        "snapshot": _snapshot(db, gid),
    }
    db["versions"][v["id"]] = v
    _audit(db, actor, "version_create", v["id"], "draft version")
    _save(db)
    return v


def _snapshot(db: dict, gid: str) -> dict:
    ents = [e for e in db["entities"].values()
            if e["graph_id"] == gid and e.get("status") == "approved"]
    ids = {e["id"] for e in ents}
    return {
        "entities": ents,
        # only edges whose BOTH endpoints are published entities (no dangling ids at runtime)
        "edges": [x for x in db["edges"].values()
                  if x["graph_id"] == gid and x.get("status") == "approved"
                  and x.get("source") in ids and x.get("target") in ids],
        "entity_types": [t for t in db["entity_types"].values() if t["graph_id"] == gid],
        "relation_types": [t for t in db["relation_types"].values() if t["graph_id"] == gid],
    }


def list_versions(gid: str) -> list[dict]:
    return [
        {"id": v["id"], "state": v["state"],
         "created_by": v["created_by"], "created_at": v["created_at"]}
        for v in _load()["versions"].values() if v["graph_id"] == gid
    ]


def transition_version(vid: str, state: str, actor: str = "expert") -> dict:
    if state not in VERSION_STATES:
        raise ValueError(f"invalid version state '{state}'")
    db = _load()
    v = db["versions"].get(vid)
    if not v:
        raise ValueError("version not found")
    gid = v["graph_id"]

    if state == "published":
        # publish gate: everything must be explicitly approved before publish.
        # 'auto' (never reviewed) and 'pending_review' both block; 'rejected'
        # items are simply excluded from the snapshot, not blockers.
        unresolved = [e for e in db["entities"].values()
                      if e["graph_id"] == gid and e["status"] in ("auto", "pending_review")]
        unresolved += [e for e in db["edges"].values()
                       if e["graph_id"] == gid and e["status"] in ("auto", "pending_review")]
        if unresolved:
            raise ValueError(
                f"cannot publish: {len(unresolved)} item(s) not yet approved "
                f"(run bulk-approve or review them individually first)"
            )
        # Refresh snapshot to the approved state and mark graph published
        v["snapshot"] = _snapshot(db, gid)
        for other in db["versions"].values():
            if other["graph_id"] == gid and other["state"] == "published":
                other["state"] = "archived"
        db["graphs"][gid]["published_version"] = vid
        db["graphs"][gid]["status"] = "published"

    v["state"] = state
    _audit(db, actor, "version_transition", vid, f"-> {state}")
    _save(db)
    return {"id": v["id"], "state": v["state"], "graph_id": gid}


def rollback(gid: str, vid: str, actor: str = "expert") -> dict:
    """One-action rollback to a prior published version (A§9.5)."""
    db = _load()
    v = db["versions"].get(vid)
    if not v or v["graph_id"] != gid:
        raise ValueError("version not found for this graph")
    for other in db["versions"].values():
        if other["graph_id"] == gid and other["state"] == "published":
            other["state"] = "archived"
    v["state"] = "published"
    db["graphs"][gid]["published_version"] = vid
    db["graphs"][gid]["status"] = "published"
    _audit(db, actor, "rollback", gid, f"rolled back to {vid}")
    _save(db)
    return {"graph_id": gid, "published_version": vid}


def published_snapshot(gid: str) -> dict | None:
    """What OntologyProvider is allowed to read at runtime — published only (A§9.5)."""
    db = _load()
    g = db["graphs"].get(gid)
    if not g or not g.get("published_version"):
        return None
    v = db["versions"].get(g["published_version"])
    return v["snapshot"] if v else None

def published_snapshots(gids: list[str]) -> list[dict]:
    """Published snapshots for several graphs with ONE store read (runtime hot path)."""
    db = _load()
    out = []
    for gid in gids or []:
        g = db["graphs"].get(gid)
        v = db["versions"].get(g["published_version"]) if g and g.get("published_version") else None
        if v and v.get("snapshot"):
            out.append(v["snapshot"])
    return out


def snapshot_status(gid: str) -> dict:
    """Compare live entity/edge counts to what's actually in the published
    snapshot, so the UI can warn 'this graph has unpublished changes'."""
    live_e, live_x = len(list_entities(gid)), len(list_edges(gid))
    snap = published_snapshot(gid)
    pub_e = len(snap["entities"]) if snap else 0
    pub_x = len(snap["edges"]) if snap else 0
    return {
        "graph_id": gid,
        "published": snap is not None,
        "live_entities": live_e, "live_edges": live_x,
        "published_entities": pub_e, "published_edges": pub_x,
        "stale": snap is None or live_e != pub_e or live_x != pub_x,
    }

def audit_log(limit: int = 200) -> list[dict]:
    return list(reversed(_load()["audit"][-limit:]))


# ============================ WRITE LOCK =====================================
# The whole ontology DB is persisted as one document, so every mutation is a
# load -> modify -> save cycle. Serialise them in-process so a background extraction job
# and UI edits cannot overwrite each other's changes (lost updates). Re-entrant: mutators
# may call each other. (Single backend process, as deployed by docker-compose.)
_WRITE_LOCK = threading.RLock()


def _locked(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        with _WRITE_LOCK:
            return fn(*a, **kw)
    return wrapper


for _name in ("create_graph", "update_graph", "delete_graph",
              "add_entity_type", "update_entity_type", "delete_entity_type",
              "add_relation_type", "update_relation_type", "delete_relation_type",
              "add_entity", "update_entity", "delete_entity",
              "add_edge", "update_edge", "delete_edge",
              "add_taxonomy_node", "delete_taxonomy_node",
              "set_item_status", "bulk_approve",
              "create_version", "transition_version", "rollback"):
    if _name in globals():
        globals()[_name] = _locked(globals()[_name])
