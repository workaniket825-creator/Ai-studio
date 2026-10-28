"""OntologyProvider (spec A§3, A§4, A§10).

Resolves entities and traverses relationships over the SELECTED, PUBLISHED graph(s)
only, and exposes governed ontology actions. Crucially it is ontology-first, not
ontology-only (spec A§3.1): anything it cannot resolve falls back to plain retrieval,
so enabling the ontology never blinds the agent to unmodeled data.

Permission parity (spec A§3.2): the same auth check is applied here as in the plain
path; the provider reads only `published` snapshots and never writes.

Starts as a working implementation over the JSON store; because it delegates to
PlainProvider for the unmodeled parts, it is safe while the graph is still being built.
"""
from __future__ import annotations

from typing import Optional

from .contract import (ActionDef, AuthContext, ContextBundle, Edge, Entity,
                       QueryInput, Snippet, SourceRef)
from .plain import PlainProvider
from . import ontology_store as store   # lowercase — matches ontology_store.py
from . import selection
import re

_WORD = re.compile(r"[a-z0-9]+")


def _canon(w: str) -> str:
    """Light singularisation so 'customers' matches the entity 'Customer'."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _tok(s: str, query: bool = False) -> set[str]:
    """Entity names -> canonical tokens; query text -> surface AND canonical tokens, so an
    entity matches when every token of its (canonical) name appears in the query."""
    words = _WORD.findall((s or "").lower())
    if query:
        return set(words) | {_canon(w) for w in words}
    return {_canon(w) for w in words}


def _ent(e: dict) -> Entity:
    return Entity(id=e.get("id", ""), type=e.get("type") or "Entity",
                  name=e.get("name") or e.get("id", ""), properties=e.get("properties") or {},
                  graph_id=e.get("graph_id", ""), confidence=e.get("confidence", 1.0),
                  provenance=e.get("provenance", ""))


def _edge(x: dict) -> Edge:
    return Edge(id=x.get("id", ""), source=x.get("source", ""), target=x.get("target", ""),
                relation=x.get("relation") or "related_to", properties=x.get("properties") or {},
                graph_id=x.get("graph_id", ""), confidence=x.get("confidence", 1.0),
                provenance=x.get("provenance", ""))

def _authorized(authz: AuthContext) -> bool:
    # Shared permission check (parity with the rest of the platform's RBAC-lite).
    return authz.role in ("viewer", "builder", "admin")


class OntologyProvider:
    name = "ontology"

    def __init__(self, graph_ids: list[str] | None = None):
        self._graph_ids: list[str] = graph_ids or []
        self._plain = PlainProvider()
        self._snaps: list[dict] | None = None   # published snapshots, loaded ONCE per provider



    # -- helpers -------------------------------------------------------------
    def _snapshots(self) -> list[dict]:
        # one store read per provider instance (the runtime builds a provider per step) instead
        # of re-loading the whole ontology DB for every helper call
        if self._snaps is None:
            self._snaps = store.published_snapshots(self._graph_ids)
        return self._snaps

    def _published_entities(self) -> list[dict]:
        return [e for s in self._snapshots() for e in (s.get("entities") or []) if e.get("id")]

    def _published_edges(self) -> list[dict]:
        return [x for s in self._snapshots() for x in (s.get("edges") or [])
                if x.get("source") and x.get("target")]

    def find_entities(self, ref: str) -> list[Entity]:
        """Resolve an entity reference (id, exact name, or text containing the name)."""
        ref = (ref or "").strip()
        pub = self._published_entities()
        hit = [e for e in pub if e.get("id") == ref] or \
              [e for e in pub if (e.get("name") or "").strip().lower() == ref.lower()] or \
              self._resolve(ref)
        return [_ent(e) for e in hit]

    def _resolve(self, text: str) -> list[dict]:
        """Token-overlap entity resolution over published entities (a real
        deployment would use embeddings/pgvector). Matches when all of the
        entity's name-tokens appear in the query, regardless of punctuation/case."""
        qt = _tok(text, query=True)
        if not qt:
            return []
        hits = []
        for e in self._published_entities():
            nt = _tok(e.get("name") or "")
            if nt and nt <= qt:
                hits.append(e)
        return hits

    # -- contract ------------------------------------------------------------
    async def get_context(self, query: QueryInput, authz: AuthContext) -> ContextBundle:
        # Always compute the plain bundle first (fallback + supplemental snippets)
        plain = await self._plain.get_context(query, authz)
        if not _authorized(authz):
            return plain

        resolved = self._resolve(query.text) + self._resolve(query.upstream)
        # de-dupe by entity id
        seen, ents = set(), []
        for e in resolved:
            if e["id"] not in seen:
                seen.add(e["id"])
                ents.append(e)

        if not ents:
            # ontology-first fallback: nothing modeled matched -> behave as plain. The reason is
            # returned on the bundle; the CALLER records one telemetry entry (no duplicates).
            plain.fallback_reason = "no_entity_match"
            plain.graph_ids = list(self._graph_ids)
            return plain

        entities = [_ent(e) for e in ents]
        # --- multi-hop expansion: per-run hop count (query.ontology_hops) with the node cap
        #     from config (expansion.max_nodes). Bounded BFS with path + edge dedup + telemetry.
        from .ontology_config import get_config
        exp = (get_config().get("expansion") or {})
        # 0 = matched entities only (no traversal); capped at 10
        raw_hops = getattr(query, "ontology_hops", 1)
        max_hops = max(0, min(int(1 if raw_hops is None else raw_hops), 10))
        max_nodes = max(1, int(exp.get("max_nodes", 15)))

        seed_ids = {e.id for e in entities}
        visited_nodes, raw_edges, raw_paths, all_pub = self._multi_hop_expand(
            seed_ids=seed_ids, max_hops=max_hops, max_nodes=max_nodes)

        # neighbour nodes reached by traversal (beyond the directly-matched seeds)
        referenced_ids = visited_nodes - seed_ids
        neighbour_entities = [_ent(all_pub[eid]) for eid in referenced_ids if eid in all_pub]

        id_to_name = {eid: (e.get("name") or eid) for eid, e in all_pub.items()}
        # dedup edges by semantic triple (source_name, relation, target_name)
        edge_sem_seen: set = set()
        deduped_raw_edges = []
        for x in raw_edges:
            sem = (str(id_to_name.get(x["source"], x["source"])).lower(),
                   str(x.get("relation") or "").lower(),
                   str(id_to_name.get(x["target"], x["target"])).lower())
            if sem not in edge_sem_seen:
                edge_sem_seen.add(sem)
                deduped_raw_edges.append(x)

        edges = [_edge(x) for x in deduped_raw_edges]

        # dedup neighbours by lowercased name against the seeds
        nb_seen = {e.name.lower() for e in entities}
        deduped_neighbours = []
        for ne in neighbour_entities:
            k = ne.name.lower()
            if k not in nb_seen:
                nb_seen.add(k)
                deduped_neighbours.append(ne)

        all_entities = entities + deduped_neighbours
        prov = [SourceRef(kind="object", ref=e.id, label=f"{e.type}:{e.name}") for e in entities]

        # resolve traversal paths to readable name-chains, deduped
        path_seen: set = set()
        resolved_paths = []
        for path in raw_paths:
            names = [all_pub[eid].get("name") or eid for eid in path if eid in all_pub]
            if len(names) > 1:
                ps = " -> ".join(names)
                if ps not in path_seen:
                    path_seen.add(ps)
                    resolved_paths.append(ps)

        return ContextBundle(
            entities=all_entities,
            relations=edges,
            snippets=plain.snippets,                  # keep plain snippets too (A§3.1)
            provenance=prov + plain.provenance,
            ontology_used=True,
            supplemental=True,
            hop_count=max_hops,
            traversed_nodes=len(all_entities),
            traversed_edges=len(edges),
            paths=resolved_paths[:50],
            graph_ids=list(self._graph_ids),
        )

    def _multi_hop_expand(self, seed_ids: set, max_hops: int, max_nodes: int):
        """Bounded BFS from the seed entities out to max_hops, capping total nodes at max_nodes.
        Returns (visited_nodes, collected_edges, paths, all_entities_by_id). Only nodes/edges
        within the traversal are used — this is what makes the hop control authoritative."""
        from collections import deque
        all_entities = {e["id"]: e for e in self._published_entities()}
        if max_hops <= 0:
            return set(seed_ids), [], [], all_entities
        all_edges = self._published_edges()
        visited_nodes: set = set(seed_ids)
        edge_seen: set = set()
        collected_edges: list = []
        paths: list = []
        queue = deque((sid, 0, [sid]) for sid in seed_ids)
        while queue:
            node_id, depth, path = queue.popleft()
            if depth >= max_hops:
                continue
            for edge in all_edges:
                if edge["source"] == node_id:
                    nbr = edge["target"]
                elif edge["target"] == node_id:
                    nbr = edge["source"]
                else:
                    continue
                if edge["id"] not in edge_seen:
                    edge_seen.add(edge["id"])
                    collected_edges.append(edge)
                if nbr not in visited_nodes:
                    if len(visited_nodes) >= max_nodes:
                        break
                    visited_nodes.add(nbr)
                    next_path = path + [nbr]
                    queue.append((nbr, depth + 1, next_path))
                    paths.append(next_path)
        # keep only edges whose both endpoints are within the visited set
        collected_edges = [x for x in collected_edges
                           if x["source"] in visited_nodes and x["target"] in visited_nodes]
        return visited_nodes, collected_edges, paths, all_entities

    async def get_available_actions(self, authz: AuthContext) -> list[ActionDef]:
        if not _authorized(authz):
            return []
        # Governed traversal action, available only when ontology is on (spec A§3.3).
        return [ActionDef(
            name="ontology_get_neighbors",
            description="Traverse typed relationships of a resolved ontology entity.",
            parameters={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "description": "optional relation type filter",
                    },
                },
            },
            governed=True,
        )]

    async def get_entity(self, entity_id: str,
                         authz: AuthContext) -> Optional[Entity]:
        if not _authorized(authz):
            return None
        for e in self._published_entities():
            if e["id"] == entity_id:
                return _ent(e)
        return None

    async def get_neighbors(self, entity_id: str, relation: Optional[str],
                            authz: AuthContext) -> list[Edge]:
        if not _authorized(authz):
            return []
        out = []
        for x in self._published_edges():
            if x["source"] == entity_id or x["target"] == entity_id:
                if relation and (x.get("relation") or "").lower() != relation.lower():
                    continue
                out.append(_edge(x))
        return out


def build_for(tenant: str, workflow_id: str,
              query_text: str = "") -> OntologyProvider:
    graphs = selection.select_graphs(tenant, workflow_id, query_text)
    return OntologyProvider(graph_ids=[g["id"] for g in graphs])


