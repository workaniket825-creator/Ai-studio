"""PlainProvider — today's behavior behind the stable contract (spec §2, §13).

Thin, behavior-preserving wrapper over the platform's current context path:
the runtime builds context from the query + upstream results. This provider
returns that as `snippets` only, with all structured fields empty — so with the
ontology OFF, output is identical to before the seam existed.
"""
from __future__ import annotations

from typing import Optional

from .contract import (ActionDef, AuthContext, ContextBundle, Edge, Entity,
                       QueryInput, Snippet, SourceRef)


class PlainProvider:
    name = "plain"

    async def get_context(self, query: QueryInput, authz: AuthContext) -> ContextBundle:
        # Reproduce today's plain context: the upstream/query text as a snippet.
        snippets: list[Snippet] = []
        prov: list[SourceRef] = []
        if query.upstream:
            snippets.append(Snippet(text=query.upstream, source="upstream"))
            prov.append(SourceRef(kind="document", ref="upstream", label="upstream results"))
        return ContextBundle(entities=[], relations=[], snippets=snippets,
                             provenance=prov, ontology_used=False, supplemental=True)

    async def get_available_actions(self, authz: AuthContext) -> list[ActionDef]:
        return []  # generic tools only — advertised by the existing tool registry

    async def get_entity(self, entity_id: str, authz: AuthContext) -> Optional[Entity]:
        return None

    async def get_neighbors(self, entity_id: str, relation: Optional[str],
                            authz: AuthContext) -> list[Edge]:
        return []

