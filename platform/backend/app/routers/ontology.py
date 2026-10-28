from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException, Response, UploadFile, File

from ..ontology import ontology_store as store
from ..ontology import ontology_config as cfg
from ..ontology import selection, factory
from ..ontology import jobs as _jobs
from ..schemas import _id as _new_id
import asyncio as _asyncio

router = APIRouter(prefix="/api/v1/ontology", tags=["ontology"])


# ------------------------------- enablement / config (§6, §12) -------------------------------
@router.get("/config")
def get_config():
    return cfg.get_config()


@router.put("/config")
def update_config(patch: dict):
    return cfg.update_config(patch)


@router.get("/models")
def available_models():
    """List configured Model Endpoints so the user can pick which LLM drives extraction,
    plus the current default. Makes the triggered model explicit (no hidden selection)."""
    from ..endpoints import list_endpoints
    eps = list_endpoints()
    return {"models": [{"id": e["id"], "name": e.get("label") or e.get("name", ""),
                        "provider": e.get("provider", ""), "model": e.get("model", "")} for e in eps],
            "default": cfg.get_config().get("extraction_model", ""),
            "has_models": bool(eps)}


@router.get("/enabled")
def enabled(tenant: str = "default", workflow_id: str = ""):
    return {"enabled": cfg.is_enabled(tenant, workflow_id),
            "tenant": tenant, "workflow_id": workflow_id}


@router.post("/enable/workflow/{workflow_id}")
def enable_workflow(workflow_id: str, body: dict):
    return cfg.set_workflow_enabled(workflow_id, bool(body.get("enabled", False)))


@router.post("/enable/tenant/{tenant}")
def enable_tenant(tenant: str, body: dict):
    return cfg.set_tenant_enabled(tenant, bool(body.get("enabled", False)))


# ------------------------------- datastore (front-end driven, §12) -------------------------------
@router.get("/datastore")
def get_datastore():
    return cfg.get_config()["datastore"]


@router.post("/datastore/test")
def test_datastore(conn: dict | None = None):
    return cfg.test_datastore(conn)


@router.put("/datastore")
def save_datastore(conn: dict):
    return cfg.save_datastore(conn)


# ------------------------------- graphs (§10) -------------------------------
@router.get("/graphs")
def list_graphs():
    return store.list_graphs()


@router.post("/graphs")
def create_graph(body: dict):
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    return store.create_graph(body)


# IMPORTANT: static /graphs/... routes MUST be declared before the dynamic /graphs/{gid},
# or FastAPI matches "/graphs/published" against {gid} (gid="published") and shadows it.
@router.get("/graphs/published")
def list_published_graphs():
    """Published graphs only — for the Enablement graph dropdown."""
    return [g for g in store.list_graphs() if g.get("published_version")]


@router.get("/graphs/{gid}")
def get_graph(gid: str):
    g = store.get_graph(gid)
    if not g:
        raise HTTPException(404, "graph not found")
    return g


@router.put("/graphs/{gid}")
def update_graph(gid: str, patch: dict):
    g = store.update_graph(gid, patch)
    if not g:
        raise HTTPException(404, "graph not found")
    return g


@router.delete("/graphs/{gid}")
def delete_graph(gid: str):
    if not store.delete_graph(gid):
        raise HTTPException(404, "graph not found")
    return {"deleted": gid}


# ------------------------------- schema + instances (§9.3) -------------------------------
@router.post("/graphs/{gid}/entity-types")
def add_entity_type(gid: str, body: dict):
    return store.add_entity_type(gid, body)


@router.post("/graphs/{gid}/relation-types")
def add_relation_type(gid: str, body: dict):
    return store.add_relation_type(gid, body)


@router.get("/graphs/{gid}/entities")
def list_entities(gid: str, status: str | None = None):
    return store.list_entities(gid, status)


@router.post("/graphs/{gid}/entities")
def add_entity(gid: str, body: dict):
    g = store.get_graph(gid)
    if not g:
        raise HTTPException(404, "graph not found")
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    status = "approved" if g.get("authoring_mode") == "manual" else "auto"
    return store.add_entity(gid, body, status=status)

@router.get("/graphs/{gid}/edges")
def list_edges(gid: str, status: str | None = None):
    return store.list_edges(gid, status)


@router.post("/graphs/{gid}/edges")
def add_edge(gid: str, body: dict):
    g = store.get_graph(gid)
    if not g:
        raise HTTPException(404, "graph not found")
    if not body.get("source") or not body.get("target") or not body.get("relation"):
        raise HTTPException(400, "source, target, and relation are required")
    status = "approved" if g.get("authoring_mode") == "manual" else "auto"
    return store.add_edge(gid, body, status=status)

# ------------------------------- review (§9.4, §11) -------------------------------
@router.get("/graphs/{gid}/review-queue")
def review_queue(gid: str):
    return store.review_queue(gid)


@router.get("/review-queue")
def all_review_queue():
    return store.review_queue(None)


@router.post("/items/{kind}/{item_id}/status")
def set_item_status(kind: str, item_id: str, body: dict):
    if kind not in ("entity", "edge", "taxonomy"):
        raise HTTPException(400, "kind must be entity|edge|taxonomy")
    try:
        item = store.set_item_status(kind, item_id, body.get("status", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not item:
        raise HTTPException(404, "item not found")
    return item


@router.post("/graphs/{gid}/bulk-approve")
def bulk_approve(gid: str, body: dict):
    n = store.bulk_approve(gid, float(body.get("min_confidence", 0.8)))
    return {"approved": n}


# ------------------------------- versions & publish (§9.5, §9.6) -------------------------------
@router.get("/graphs/{gid}/versions")
def list_versions(gid: str):
    return store.list_versions(gid)


@router.post("/graphs/{gid}/versions")
def create_version(gid: str):
    return store.create_version(gid)


@router.post("/versions/{vid}/transition")
def transition_version(vid: str, body: dict):
    try:
        return store.transition_version(vid, body.get("state", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/graphs/{gid}/rollback")
def rollback(gid: str, body: dict):
    try:
        return store.rollback(gid, body.get("version_id", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------- graph view + telemetry (§11, §7) -------------------------------
@router.get("/graphs/{gid}/view")
def graph_view(gid: str, q: str = "", limit: int = 100, status: str = ""):
    """Search-first graph view (spec §11).
    - `status=approved` shows ONLY approved entities/edges (spec §7 fix).
    - unreviewed 'auto' items are surfaced as 'pending_review' for display (spec §7 fix)."""
    def _disp(item: dict) -> dict:
        it = dict(item)
        if it.get("status") == "auto":
            it["status"] = "pending_review"
        return it

    ents = [_disp(e) for e in store.list_entities(gid)]
    if status:
        ents = [e for e in ents if e["status"] == status]
    if q:
        ql = q.lower()
        ents = [e for e in ents if ql in (e.get("name", "").lower())]
    total = len(store.list_entities(gid))
    ents = ents[:limit]
    ids = {e["id"] for e in ents}
    edges = [_disp(x) for x in store.list_edges(gid)
             if (x["source"] in ids or x["target"] in ids)
             and (not status or (x.get("status") if x.get("status") != "auto" else "pending_review") == status)]
    return {"entities": ents, "edges": edges, "truncated": total > limit, "total": total}


@router.get("/graphs/{gid}/neighbors/{entity_id}")
def graph_neighbors(gid: str, entity_id: str):
    """Expand-on-demand: neighbors of one entity for click-to-expand (spec §11)."""
    edges = [x for x in store.list_edges(gid)
             if x["source"] == entity_id or x["target"] == entity_id]
    nb_ids = {e["source"] for e in edges} | {e["target"] for e in edges}
    nb_ids.discard(entity_id)
    ent_by_id = {e["id"]: e for e in store.list_entities(gid)}
    neighbors = [ent_by_id[i] for i in nb_ids if i in ent_by_id]
    return {"center": ent_by_id.get(entity_id), "neighbors": neighbors, "edges": edges}


@router.get("/graphs/{gid}/entity/{entity_id}")
def entity_detail(gid: str, entity_id: str):
    """Entity detail panel: properties, relationships, provenance, confidence (spec §11)."""
    ent = next((e for e in store.list_entities(gid) if e["id"] == entity_id), None)
    if not ent:
        raise HTTPException(404, "entity not found")
    edges = [x for x in store.list_edges(gid)
             if x["source"] == entity_id or x["target"] == entity_id]
    return {"entity": ent, "relationships": edges}


# ------------------------------- inline edit / delete (spec §7) -------------------------------
@router.put("/entities/{eid}")
def update_entity(eid: str, patch: dict):
    e = store.update_entity(eid, patch)
    if not e:
        raise HTTPException(404, "entity not found")
    return e


@router.delete("/entities/{eid}")
def delete_entity(eid: str):
    if not store.delete_entity(eid):
        raise HTTPException(404, "entity not found")
    return {"deleted": eid}


@router.put("/edges/{edid}")
def update_edge(edid: str, patch: dict):
    e = store.update_edge(edid, patch)
    if not e:
        raise HTTPException(404, "edge not found")
    return e


@router.delete("/edges/{edid}")
def delete_edge(edid: str):
    if not store.delete_edge(edid):
        raise HTTPException(404, "edge not found")
    return {"deleted": edid}


@router.delete("/taxonomy/{nid}")
def delete_taxonomy(nid: str):
    if not store.delete_taxonomy_node(nid):
        raise HTTPException(404, "taxonomy node not found")
    return {"deleted": nid}


@router.get("/graphs/{gid}/analytics")
def graph_analytics(gid: str):
    """Data-science summary of the graph (spec §11 flagship): density, centrality, distributions."""
    if not store.get_graph(gid):
        raise HTTPException(404, "graph not found")
    return store.analytics(gid)

@router.post("/graphs/{gid}/attach/{workflow_id}")
def attach_to_workflow(gid: str, workflow_id: str):
    """Attaching an ontology to a workflow must also enable it for that workflow —
    these were previously two separate calls, which is the #1 cause of
    'ontology_used: false, entity: 0' with no error."""
    g = store.get_graph(gid)
    if not g:
        raise HTTPException(404, "graph not found")
    store.update_graph(gid, {"workflows": list(set((g.get("workflows") or []) + [workflow_id]))})
    cfg.set_workflow_enabled(workflow_id, True)
    return {"graph_id": gid, "workflow_id": workflow_id, "attached": True, "enabled": True}


@router.get("/graphs/{gid}/publish-status")
def publish_status(gid: str):
    if not store.get_graph(gid):
        raise HTTPException(404, "graph not found")
    return store.snapshot_status(gid)


# ------------------------------- export / import (portable JSON) -------------------------------
@router.get("/graphs/{gid}/export")
def export_graph(gid: str, source: str = "published"):
    from ..ontology import graph_io
    try:
        doc = graph_io.export_graph(gid, source=source)
    except ValueError as e:
        raise HTTPException(400, str(e))
    body = json.dumps(doc, indent=2, ensure_ascii=False)
    filename = f"{doc['graph']['name'].replace(' ', '_')}_export.json"
    return Response(content=body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _run_import(payload, publish: bool = True, name: str = "", keep_scoping: bool = False) -> dict:
    """Shared by both import routes: invalid documents -> 400 with a readable reason,
    anything unexpected -> 500 with a message (never a bare 'Internal Server Error')."""
    from ..ontology import graph_io
    try:
        return graph_io.import_graph(payload, publish=publish, name_override=name,
                                     keep_scoping=keep_scoping)
    except ValueError as e:
        raise HTTPException(400, f"Import failed: {e}")
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(500, f"Import failed unexpectedly: {type(e).__name__}: {e}")


@router.post("/graphs/import")
async def import_graph(file: UploadFile = File(...), publish: bool = True, name: str = "",
                       keep_scoping: bool = False):
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Import failed: uploaded file is not valid JSON ({e})")
    return _run_import(payload, publish=publish, name=name, keep_scoping=keep_scoping)


# ------------------------------- auto-extraction (§9.2) -------------------------------

# ------------------------------- auto-extraction (§9.2) -------------------------------
@router.post("/graphs/{gid}/extract/structured")
def extract_structured(gid: str, body: dict):
    """body: { table: str, rows: [ {..} ] } — schema inference + edges from *_id columns."""
    from ..ontology.extraction import extract_structured as _ex
    if (store.get_graph(gid) or {}).get("authoring_mode") == "manual":
        raise HTTPException(400, "auto-extraction is disabled in manual mode")
    return _ex(gid, body.get("table", "rows"), body.get("rows", []))


@router.post("/graphs/{gid}/extract/text")
async def extract_text(gid: str, body: dict):
    """body: { text, source?, endpoint_id?, instructions?, async_job? } — LLM-driven extraction.
    With async_job=true, starts a background job and returns { job_id } for progress polling."""
    from ..ontology.extraction import extract_text as _ex
    if (store.get_graph(gid) or {}).get("authoring_mode") == "manual":
        raise HTTPException(400, "auto-extraction is disabled in manual mode")
    if body.get("async_job"):
        job_id = _new_id("extract")
        _jobs.create(job_id, source=f"extract:{gid}")
        async def _run():
            try:
                res = await _ex(gid, body.get("text", ""), body.get("source", "document"),
                          endpoint_id=body.get("endpoint_id", ""),
                          instructions=body.get("instructions", ""), job_id=job_id, prompt=body.get("prompt", ""))
                status = "cancelled" if (_jobs.is_cancelled(job_id) or (res or {}).get("cancelled")) else "done"
                _jobs.update(job_id, entities=(res or {}).get("entities", 0),
                             edges=(res or {}).get("edges", 0),
                             method=(res or {}).get("method", ""))
                _jobs.finish(job_id, status, result=res or {})
            except Exception as e:  # pragma: no cover
                _jobs.finish(job_id, "error", error=str(e))
        _asyncio.create_task(_run())
        return {"job_id": job_id, "status": "running"}
    return await _ex(gid, body.get("text", ""), body.get("source", "document"),
                     endpoint_id=body.get("endpoint_id", ""), instructions=body.get("instructions", ""), prompt=body.get("prompt", ""))


@router.post("/graphs/{gid}/extract/file")
async def extract_file(gid: str, body: dict):
    """Extract from a file already in File Storage (spec §7 — file upload capability).
    body: { path: str } — a path in the shared storage (e.g. shared/docs/spec.txt or .docx)."""
    from ..ontology.extraction import extract_text as _ex
    from .. import filestore
    if (store.get_graph(gid) or {}).get("authoring_mode") == "manual":
        raise HTTPException(400, "auto-extraction is disabled in manual mode")
    path = body.get("path", "")
    if not path:
        raise HTTPException(400, "path is required")
    try:
        if path.lower().endswith((".docx", ".doc")):
            import io, subprocess, tempfile, os
            data = filestore.read_bytes(path)
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
                tf.write(data); tmp = tf.name
            try:
                text = subprocess.run(["pandoc", "-t", "plain", tmp], capture_output=True,
                                      text=True, timeout=30).stdout
            finally:
                os.unlink(tmp)
        else:
            text = filestore.read_text(path)
    except filestore.StorageError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"could not read file: {e}")
    if body.get("async_job"):
        job_id = _new_id("extract")
        _jobs.create(job_id, source=f"extract:{gid}:{path}")
        async def _run():
            try:
                res = await _ex(gid, text, source=path, endpoint_id=body.get("endpoint_id", ""),
                          instructions=body.get("instructions", ""), job_id=job_id, prompt=body.get("prompt", ""))
                status = "cancelled" if (_jobs.is_cancelled(job_id) or (res or {}).get("cancelled")) else "done"
                _jobs.update(job_id, entities=(res or {}).get("entities", 0),
                             edges=(res or {}).get("edges", 0),
                             method=(res or {}).get("method", ""))
                _jobs.finish(job_id, status, result=res or {})
            except Exception as e:  # pragma: no cover
                _jobs.finish(job_id, "error", error=str(e))
        _asyncio.create_task(_run())
        return {"job_id": job_id, "status": "running"}
    return await _ex(gid, text, source=path, endpoint_id=body.get("endpoint_id", ""),
                     instructions=body.get("instructions", ""), prompt=body.get("prompt", ""))


# ------------------------------- per-graph datastore (§12) -------------------------------
@router.get("/graphs/{gid}/datastore")
def get_graph_datastore(gid: str):
    return cfg.get_graph_datastore(gid)


@router.put("/graphs/{gid}/datastore")
def save_graph_datastore(gid: str, conn: dict | None = None):
    return cfg.save_graph_datastore(gid, conn or {})


@router.get("/selection")
def preview_selection(tenant: str = "default", workflow_id: str = "", q: str = ""):
    return [{"id": g["id"], "name": g["name"], "tags": g.get("tags", {})}
            for g in selection.select_graphs(tenant, workflow_id, q)]


@router.get("/telemetry")
def telemetry(limit: int = 200):
    return factory.telemetry(limit)


@router.get("/audit")
def audit(limit: int = 200):
    return store.audit_log(limit)




# ============================================================================
# UI-compatibility endpoints (bridge the existing frontend to this router)
# ============================================================================


@router.post("/import")
def import_graph_compat(body: dict):
    """UI alias for graph import. The frontend posts {snapshot: <export document>}; the raw
    export document and the legacy {graph: <document>} wrapper are accepted too (graph_io.unwrap).
    Optional body fields: name, publish (default true), keep_scoping (default false)."""
    return _run_import(body, publish=bool(body.get("publish", True)),
                       name=str(body.get("name") or ""),
                       keep_scoping=bool(body.get("keep_scoping", False)))


@router.put("/workflow-graph")
def set_workflow_graph_compat(body: dict):
    """Atomic bind+enable for the Enablement screen:
    { workflow_id, graph_id }. Binding a graph enables the workflow for it and
    records the mapping on both config and the graph (the field-reported fix).
    graph_id='' clears the binding."""
    wfid = body.get("workflow_id", "")
    gid = body.get("graph_id", "")
    if not wfid:
        raise HTTPException(400, "workflow_id required")
    wg = dict(cfg.get_config().get("workflow_graphs") or {})
    if gid:
        g = store.get_graph(gid)
        if not g:
            raise HTTPException(404, "graph not found")
        wg[wfid] = gid
        cfg.update_config({"workflow_graphs": wg})
        cfg.set_workflow_enabled(wfid, True)
        store.update_graph(gid, {"workflows": sorted(set((g.get("workflows") or []) + [wfid]))})
        return {"workflow_id": wfid, "graph_id": gid, "enabled": True}
    wg.pop(wfid, None)
    cfg.update_config({"workflow_graphs": wg})
    return {"workflow_id": wfid, "graph_id": "", "enabled": cfg.is_enabled(workflow_id=wfid)}


# ---- async extraction jobs (real-time progress + cancel, preserved from prior UI) ----
@router.get("/extract/jobs/{job_id}")
def extract_job_status(job_id: str):
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/extract/jobs/{job_id}/cancel")
def extract_job_cancel(job_id: str):
    return {"cancelled": _jobs.cancel(job_id), "job_id": job_id}
