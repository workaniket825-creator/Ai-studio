"""Ontology Intelligence Layer — isolated, additive module (spec A§13).

Public seam used by the runtime:
    from .ontology import get_context_provider
    provider = get_context_provider(tenant, workflow_id, query_text)
    bundle = await provider.get_context(QueryInput(...), AuthContext(...))

Everything else (store, authoring, config, graph selection) lives behind the
provider and is reached only via the admin/authoring routers — never the agent loop.
"""
from .contract import (ActionDef, AuthContext, ContextBundle, ContextProvider,
                       Edge, Entity, QueryInput, Snippet, SourceRef)
from .factory import get_context_provider, record_telemetry, telemetry

__all__ = [
    "ContextProvider",
    "ContextBundle",
    "QueryInput",
    "AuthContext",
    "Entity",
    "Edge",
    "Snippet",
    "SourceRef",
    "ActionDef",
    "get_context_provider",
    "record_telemetry",
    "telemetry",
]
