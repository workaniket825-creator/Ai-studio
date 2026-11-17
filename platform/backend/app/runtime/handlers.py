"""Platform step handlers — one shared seam for both runtimes (live + ADK).

An agent card may name a `handler` (AgentCard.handler). When a workflow step reaches such an
agent, the runtime hands the step to the registered handler instead of making a plain model
call. Handlers are ordinary async functions; they may still call a model themselves (e.g. the
fine-tuning planner), but they own the step: they record progress on the run, publish activity
events and return the step's output. Like ontology/runtime_context.py, keeping this in one place
means the two runtimes cannot drift apart.

A handler receives a StepContext and returns a StepResult. It never raises for expected
failures: it returns status "failed"/"cancelled" with an honest error message.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..schemas import ActivityKind, Run, RunStatus, WorkflowGraph
from ..store import agents as agents_repo
from ..store import runs as runs_repo

_log = logging.getLogger("tcs.handlers")

Emit = Callable[..., Awaitable[Any]]          # emit(kind, label, **kw)


@dataclass
class StepContext:
    run: Run
    workflow: WorkflowGraph
    node_id: str
    agent: str
    card: dict
    prior: str
    emit: Emit

    def save(self) -> None:
        """Persist the run (progress etc.) so Chat/Monitoring see it immediately."""
        runs_repo.upsert(self.run.model_dump(by_alias=True))


@dataclass
class StepResult:
    status: str = "ok"                      # ok | failed | cancelled
    output: str = ""
    error: str = ""
    steps: list[str] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    in_tokens: int = 0
    out_tokens: int = 0
    extra: dict = field(default_factory=dict)   # merged into node_outputs[] entry


Handler = Callable[[StepContext], Awaitable[StepResult]]


def _registry() -> dict[str, Handler]:
    # imported lazily so the fine-tuning package is only loaded when a handler is used
    from ..finetune import steps as ft
    return {
        "finetune_planner": ft.planner_step,
        "finetune_executor": ft.executor_step,
        "finetune_reporter": ft.reporter_step,
    }


def card_for(agent_name: str) -> dict:
    matches = agents_repo.list(lambda a: a.get("agent_name") == agent_name)
    return matches[0] if matches else {}


def handler_of(agent_name: str) -> Optional[str]:
    return (card_for(agent_name) or {}).get("handler") or None


async def run_handler_node(*, run: Run, workflow: WorkflowGraph, node_id: str, agent: str,
                           handler: str, prior: str, emit: Emit) -> bool:
    """Execute one workflow node through its handler. Appends the node output and persists.
    Returns True when the workflow should continue, False when the run reached a terminal
    state (failed / cancelled) and the runtime must stop."""
    fn = _registry().get(handler)
    await emit(ActivityKind.agent_enter, f"{agent} is working…", node_id=node_id, agent=agent)
    if not fn:
        run.status = RunStatus.failed
        run.error = f"Agent '{agent}' names an unknown handler '{handler}'."
        runs_repo.upsert(run.model_dump(by_alias=True))
        await emit(ActivityKind.error, run.error, level="error", node_id=node_id, agent=agent)
        return False

    ctx = StepContext(run=run, workflow=workflow, node_id=node_id, agent=agent,
                      card=card_for(agent), prior=prior, emit=emit)
    import time
    t0 = time.time()
    try:
        res = await fn(ctx)
    except Exception as e:   # a handler bug must still end the run honestly
        _log.exception("handler %s failed", handler)
        res = StepResult(status="failed", error=f"{agent} failed: {type(e).__name__}: {e}")

    node_out = {"node_id": node_id, "agent": agent,
                "output": res.output or (res.error if res.status != "ok" else "") or "(no output)",
                "steps": res.steps, "in_tokens": res.in_tokens, "out_tokens": res.out_tokens,
                "handler": handler, **(res.extra or {})}
    run.node_outputs.append(node_out)
    run.input_tokens += res.in_tokens
    run.output_tokens += res.out_tokens
    run.tokens = run.input_tokens + run.output_tokens
    for a in res.artifacts:
        if not any(x.get("name") == a.get("name") for x in run.artifacts):
            run.artifacts.append(a)

    if res.status == "ok":
        runs_repo.upsert(run.model_dump(by_alias=True))
        await emit(ActivityKind.agent_exit, f"{agent} finished.", node_id=node_id, agent=agent,
                   latency_ms=int((time.time() - t0) * 1000))
        return True

    run.status = RunStatus.cancelled if res.status == "cancelled" else RunStatus.failed
    run.error = res.error or ("Interrupted by user." if res.status == "cancelled" else f"{agent} failed.")
    # the step's own summary is still the most useful answer to show
    run.final_output = res.output or run.final_output
    runs_repo.upsert(run.model_dump(by_alias=True))
    await emit(ActivityKind.error, run.error, level="warn" if res.status == "cancelled" else "error",
               node_id=node_id, agent=agent)
    return False
