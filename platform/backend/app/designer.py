"""Workflow Designer (spec §6.2), Phase 3.

A deterministic, reuse-first designer that works with **no model key**: it maps a
natural-language goal to required capabilities, matches each against the Garden by
keyword score, reuses the best fit above threshold, and marks genuine gaps as
`to_be_created`. Swappable for an LLM-driven designer later (set MODEL_PROVIDER and
point `design()` at the model gateway) with no API change.
"""
from __future__ import annotations

import re

from .schemas import (NodeStatus, WorkflowEdge, WorkflowGraph, WorkflowNode)
from .store import agents as agents_repo

# capability -> (trigger keywords, fallback agent name, output_key)
CAPABILITIES = [
    ("extract", ["extract", "csv", "spreadsheet", "parse", "file", "data from"],
     "Data Extractor", "raw_data"),
    ("research", ["research", "search", "web", "find out", "look up", "sources"],
     "Web Researcher", "research_findings"),
    ("document_qa", ["document", "pdf", "contract", "policy", "answer questions", "read"],
     "Document Q&A (RAG)", "answer"),
    ("analyze", ["analyze", "analysis", "anomal", "metric", "trend", "calculate", "compare"],
     "Analyst", "analysis_result"),
    ("summarize", ["summar", "brief", "digest", "condense", "overview"],
     "Summarizer", "summary"),
    ("email", ["email", "draft", "message", "notify", "send"],
     "Email/Comms Drafter", "email_draft"),
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _best_agent(keywords: list[str], fallback_name: str):
    """Return (agent_name, status). Prefer an existing Garden agent by keyword score."""
    goal_kw = set(keywords)
    best, best_score = None, 0
    for a in agents_repo.list(lambda x: x.get("status") == "published"):
        hay = _tokens(f"{a['agent_name']} {a.get('role','')} {a.get('description','')} {' '.join(a.get('tags',[]))}")
        score = len(goal_kw & hay)
        if score > best_score:
            best, best_score = a, score
    if best and best_score > 0:
        return best["agent_name"], NodeStatus.reused
    # fall back to the canonical foundation agent if present, else provisional
    fb = agents_repo.list(lambda x: x["agent_name"] == fallback_name)
    if fb:
        return fallback_name, NodeStatus.reused
    return fallback_name, NodeStatus.to_be_created


def design(goal: str) -> WorkflowGraph:
    g = goal.lower()
    chosen = []
    for cap, triggers, fallback, out_key in CAPABILITIES:
        if any(t in g for t in triggers):
            name, status = _best_agent(triggers, fallback)
            chosen.append((name, status, out_key))

    if not chosen:  # generic default: research -> summarize
        chosen = [("Web Researcher", NodeStatus.reused, "research_findings"),
                  ("Summarizer", NodeStatus.reused, "summary")]

    # always append a verification step (learning from spec §19)
    crit = agents_repo.list(lambda x: x["agent_name"] == "Critic / Reviewer")
    if crit:
        chosen.append(("Critic / Reviewer", NodeStatus.reused, "verdict"))

    nodes, edges, prev = [], [], None
    for i, (name, status, out_key) in enumerate(chosen, 1):
        nid = f"n{i}"
        bindings = {}
        if prev:
            bindings[prev[2]] = f"{prev[0]}.{prev[2]}"
        else:
            bindings["input"] = "workflow.input"
        nodes.append(WorkflowNode(
            node_id=nid, agent_ref=f"agent_cards/{name}", status=status,
            output_key=out_key, input_bindings=bindings,
            provisional_card=None if status == NodeStatus.reused else {"agent_name": name},
        ))
        if prev:
            edges.append(WorkflowEdge(**{"from": f"n{i-1}", "to": nid, "type": "sequential"}))
        prev = (nid, name, out_key)

    approval = ["n" + str(len(chosen))] if any(c[0] == "Email/Comms Drafter" for c in chosen) else []
    return WorkflowGraph(
        name=f"Designed: {goal[:40]}", goal_prompt=goal, designed_by="workflow_designer(deterministic)",
        nodes=nodes, edges=edges, approval_gates=approval,
    )


def plan_steps(workflow: WorkflowGraph) -> list[dict]:
    """Plan Mode (spec §7): a human-readable, ordered plan to approve before running."""
    from .factory import compile_workflow
    steps = []
    for i, s in enumerate(compile_workflow(workflow), 1):
        gate = " (needs your approval)" if s["node_id"] in workflow.approval_gates else ""
        steps.append({"step": i, "node_id": s["node_id"], "agent": s["agent"],
                      "action": f"Run {s['agent']}{gate}"})
    return steps
