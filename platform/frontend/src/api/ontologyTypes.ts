// Ontology data persisted per agent step under run.node_outputs[].ontology.
// This record (written by the runtime from the published graph) is the single source of truth
// for the "Ontology data used" panel; nothing is derived from the LLM answer.
// Every field is optional so older run records and plain-provider steps never break the UI.

export interface OntologyEntityRef {
  id?: string;
  name?: string;
  type?: string;
}

export interface OntologyRelationRef {
  source?: string;      // entity NAME (falls back to the original id when unmapped)
  relation?: string;
  target?: string;
  source_id?: string;   // original id, present only when it was mapped to a name
  target_id?: string;
}

export interface NodeOntology {
  used?: boolean;
  provider?: string;
  hop_count?: number;
  traversed_nodes?: number;
  traversed_edges?: number;
  paths?: string[];
  entities?: (OntologyEntityRef | string)[];
  relations?: (OntologyRelationRef | string)[];
  context?: string;
  graph_ids?: string[];
  // added by the UI from the surrounding node output
  agent?: string;
  node_id?: string;
}

/** node_outputs -> ontology records (with the agent attached), skipping steps without one. */
export function ontologyFromNodeOutputs(nodeOutputs: any[] | undefined): NodeOntology[] {
  return (nodeOutputs || [])
    .filter((n: any) => n && n.ontology && typeof n.ontology === "object")
    .map((n: any) => ({ ...(n.ontology as NodeOntology), agent: n.agent, node_id: n.node_id }));
}

export function entityLabel(e: OntologyEntityRef | string): { name: string; type: string } {
  if (typeof e === "string") return { name: e, type: "" };
  return { name: e?.name || e?.id || "(unnamed)", type: e?.type || "" };
}

export function relationLabel(r: OntologyRelationRef | string): { source: string; relation: string; target: string } {
  if (typeof r === "string") return { source: "", relation: r, target: "" };
  return { source: r?.source || r?.source_id || "?", relation: r?.relation || "related_to",
           target: r?.target || r?.target_id || "?" };
}
