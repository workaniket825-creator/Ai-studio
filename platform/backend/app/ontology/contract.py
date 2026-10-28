"""The stable contract (spec §4).

One interface the agent consults for grounding. Two implementations sit behind it
(PlainProvider, OntologyProvider) and return the IDENTICAL normalized ContextBundle,
so the agent path never diverges. The plain provider leaves structured fields empty.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class Entity:
    id: str
    type: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    graph_id: str = ""
    confidence: float = 1.0
    provenance: str = ""


@dataclass
class Edge:
    id: str
    source: str          # entity id
    target: str          # entity id
    relation: str        # relation type
    properties: dict[str, Any] = field(default_factory=dict)
    graph_id: str = ""
    confidence: float = 1.0
    provenance: str = ""


@dataclass
class Snippet:
    text: str
    source: str = ""
    score: float = 0.0


@dataclass
class SourceRef:
    kind: str            # "object" | "document" | ...
    ref: str             # entity id or document id
    label: str = ""


@dataclass
class ActionDef:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    governed: bool = True


@dataclass
class ContextBundle:
    """Identical return shape for BOTH providers (spec §4.1).
    PlainProvider populates only `snippets`/`provenance`; structured fields stay []."""
    entities: list[Entity] = field(default_factory=list)
    relations: list[Edge] = field(default_factory=list)
    snippets: list[Snippet] = field(default_factory=list)
    provenance: list[SourceRef] = field(default_factory=list)
    # signals to the planner (spec §3.1 / §3.3) — supplemental, not a full world model
    ontology_used: bool = False
    supplemental: bool = True
    # multi-hop traversal telemetry (populated by OntologyProvider)
    hop_count: int = 1
    traversed_nodes: int = 0
    traversed_edges: int = 0
    paths: list[str] = field(default_factory=list)
    # why the provider fell back to plain context ("" when the ontology was used), and the
    # graphs that were consulted - lets the caller record ONE complete telemetry entry.
    fallback_reason: str = ""
    graph_ids: list[str] = field(default_factory=list)

    def to_prompt_context(self, include_snippets: bool = True) -> str:
        """Render the bundle into the plain-text context the runtime already uses.
        With empty structured fields this reproduces today's behavior exactly.
        Deduplicates entities/relations/paths at render time as a safety net.
        include_snippets=False renders only the graph facts - for callers that already put the
        upstream text in the prompt themselves (avoids sending it twice)."""
        parts: list[str] = []

        if self.entities:
            # Deduplicate by lowercased name — keeps first occurrence (highest confidence)
            seen_ent: set[str] = set()
            unique_ents = []
            for e in self.entities:
                key = (e.name or e.id or "").lower().strip()
                if key not in seen_ent:
                    seen_ent.add(key)
                    unique_ents.append(e)
            lines = [
                f"- {e.type or 'Entity'}: {e.name or e.id}"
                + (f" ({', '.join(f'{k}={v}' for k, v in e.properties.items())})" if e.properties else "")
                for e in unique_ents
            ]
            parts.append("Grounded entities:\n" + "\n".join(lines))

        if self.relations:
            # Edge endpoints rendered as human-readable names, not raw IDs.
            id_to_name: dict[str, str] = {e.id: e.name for e in self.entities}
            # Deduplicate by semantic triple (source_name, relation, target_name)
            seen_rel: set[tuple] = set()
            lines = []
            for r in self.relations:
                src = str(id_to_name.get(r.source, r.source) or "")
                tgt = str(id_to_name.get(r.target, r.target) or "")
                key = (src.lower(), (r.relation or "").lower(), tgt.lower())
                if key not in seen_rel:
                    seen_rel.add(key)
                    lines.append(f"- {src} --{r.relation}--> {tgt}")
            if lines:
                parts.append("Grounded relationships:\n" + "\n".join(lines))

        if self.paths:
            seen_p: set[str] = set()
            unique_paths = []
            for p in self.paths:
                if p not in seen_p:
                    seen_p.add(p)
                    unique_paths.append(p)
            if unique_paths:
                parts.append("Ontology traversal paths:\n" + "\n".join(f"- {p}" for p in unique_paths))

        if include_snippets and self.snippets:
            parts.append("\n".join(s.text for s in self.snippets if s.text))
        return "\n\n".join(p for p in parts if p.strip())


@dataclass
class QueryInput:
    text: str
    tenant: str = "default"
    workflow_id: str = ""
    upstream: str = ""
    ontology_hops: int = 1


@dataclass
class AuthContext:
    role: str = "admin"
    tenant: str = "default"


class ContextProvider(Protocol):
    """The single abstraction the agent consults (spec §4)."""

    name: str

    async def get_context(self, query: QueryInput, authz: AuthContext) -> ContextBundle: ...
    async def get_available_actions(self, authz: AuthContext) -> list[ActionDef]: ...
    async def get_entity(self, entity_id: str, authz: AuthContext) -> Optional[Entity]: ...
    async def get_neighbors(self, entity_id: str, relation: Optional[str],
                            authz: AuthContext) -> list[Edge]: ...
