"""Agent Factory + Workflow Compiler (spec §6.4, §7, §23.2).

- AgentFactory: resolves an AgentCard (or provisional card) into an executable
  spec. In mock mode it returns a plain dict; the AdkRuntime version builds real
  LlmAgent/Sequential/Parallel/Loop objects with tools + collaboration wiring.
- compile_workflow: topologically orders the graph into an execution plan and
  validates input bindings (every binding must have a producing upstream node).
"""
from __future__ import annotations

from .schemas import WorkflowGraph
from .store import agents as agents_repo


class AgentFactory:
    @staticmethod
    def resolve_name(agent_ref: str | None, provisional: dict | None) -> str:
        if provisional:
            return provisional.get("agent_name", "New Agent")
        if agent_ref:
            key = agent_ref.split("@")[0]
            if key.startswith("agent_cards/"):
                key = key[len("agent_cards/"):]   # keep names that contain '/'
            # try by id, then by name
            card = agents_repo.get(key)
            if not card:
                matches = agents_repo.list(lambda a: a["agent_name"] == key)
                card = matches[0] if matches else None
            if card:
                return card.get("agent_name") or card.get("role")
        return "Unknown Agent"


def compile_workflow(workflow: WorkflowGraph) -> list[dict]:
    """Return an ordered list of {node_id, agent} steps (topological sort)."""
    nodes = {n.node_id: n for n in workflow.nodes}
    indeg = {nid: 0 for nid in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in workflow.edges:
        adj[e.from_].append(e.to)
        indeg[e.to] += 1

    # Kahn's algorithm, stable on insertion order
    queue = [nid for nid in nodes if indeg[nid] == 0] or list(nodes)
    order, seen = [], set()
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    for nid in nodes:  # append any leftover (cycles) so we never drop a node
        if nid not in seen:
            order.append(nid)

    plan = []
    for nid in order:
        n = nodes[nid]
        plan.append({"node_id": nid,
                     "agent": AgentFactory.resolve_name(n.agent_ref, n.provisional_card)})
    return plan


def validate_workflow(workflow: WorkflowGraph) -> list[str]:
    """Return a list of validation errors (unbound inputs, unknown refs)."""
    errors: list[str] = []
    produced = {n.output_key for n in workflow.nodes}
    node_ids = {n.node_id for n in workflow.nodes}
    for n in workflow.nodes:
        for _, src in n.input_bindings.items():
            key = src.split(".")[-1]
            if not src.startswith("workflow.") and key not in produced:
                errors.append(f"Node {n.node_id}: input '{src}' has no producer")
    for e in workflow.edges:
        if e.from_ not in node_ids or e.to not in node_ids:
            errors.append(f"Edge {e.from_}->{e.to} references a missing node")
    return errors
