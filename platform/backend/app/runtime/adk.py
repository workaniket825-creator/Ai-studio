"""AdkRuntime — production executor on the open-source Google ADK framework.

Models are reached via ADK's `LiteLlm` wrapper over **APIs** (Mistral, Gemini, Azure/OpenAI
via Model Endpoints) — there is NO Google Cloud / Vertex *platform* dependency. Sessions and
memory use ADK's in-memory services, so nothing external is required beyond a model API key.

Activate:
  pip install google-adk litellm
  export RUNTIME=adk MODEL_PROVIDER=mistral MISTRAL_API_KEY=...
    (or MODEL_PROVIDER=gemini GEMINI_API_KEY=...)

The event loop maps ADK Events -> ActivityEvents on the same bus the live runtime uses,
so the frontend is identical whichever runtime executes the run.

Ontology (spec A§2/A§13): every agent step goes through the single ontology seam via
`ontology.build_step_context` — grounded entities/relationships are injected into the ADK
message, the governed `ontology_get_neighbors` action is exposed as an ADK tool, and the full
ontology result is persisted under node_outputs[].ontology (the UI's source of truth).
With the ontology off (or nothing matched) the step runs on plain context.
"""
from __future__ import annotations
import json
import re

from ..tool_exec import build_tool_defs, execute_tool
from ..activity import bus, narrate
from ..factory import compile_workflow
from ..models import DEFAULTS, PROVIDER, to_litellm_model
from ..schemas import ActivityEvent, ActivityKind, Run, RunStatus, WorkflowGraph
from ..store import agents as agents_repo
from ..store import runs as runs_repo

# keys the platform adds to run.input that are not part of the user's request
_NON_REQUEST_KEYS = {"message", "input", "history", "ontology_hops", "tenant"}


def _adk_name(agent_name: str) -> str:
    """ADK agent names must be identifiers (e.g. 'DSLab Code Runner · VM2' is not)."""
    n = re.sub(r"\W+", "_", agent_name or "agent").strip("_") or "agent"
    return n if not n[0].isdigit() else f"a_{n}"


def _user_request(run_input) -> str:
    """The user's request as text: message/input plus any extra structured fields."""
    inp = run_input if isinstance(run_input, dict) else {"input": run_input}
    message = str(inp.get("message") or inp.get("input") or "").strip()
    extras = {k: v for k, v in inp.items() if k not in _NON_REQUEST_KEYS}
    if extras:
        message += ("\n" if message else "") + json.dumps(extras, default=str)
    return message


class AdkRuntime:
    name = "adk"

    def __init__(self):
        try:
            import google.adk  # noqa: F401
            import litellm      # noqa: F401
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Install the open-source runtime: `pip install google-adk litellm`, "
                "then set RUNTIME=adk and a model key (MISTRAL_API_KEY or GEMINI_API_KEY)."
            ) from e

    def _model_for(self, mc: dict):
        """ADK model for an agent's model_config: UI Model Endpoint first, else env provider."""
        from google.adk.models.lite_llm import LiteLlm
        eid = mc.get("endpoint_id")
        if eid:
            from ..endpoints import get_full, litellm_call_args
            ep = get_full(eid)
            if ep:
                args = litellm_call_args(ep)
                return LiteLlm(model=args["model"], **args["params"])
        prov = mc.get("provider") or PROVIDER
        model_name = mc.get("model") or DEFAULTS.get(prov)
        lit = to_litellm_model(model_name, prov)
        return lit if prov == "gemini" else LiteLlm(model=lit)

    def _build_agent(self, agent_name: str, extra_tools: list | None = None,
                     extra_instruction: str = ""):
        from google.adk.agents import LlmAgent

        matches = agents_repo.list(lambda a: a["agent_name"] == agent_name)
        card = matches[0] if matches else None
        mc = (card or {}).get("model_config", {}) or {}
        instruction = (card or {}).get("prompts", {}).get("system_prompt") or f"You are {agent_name}."
        # Load the tools attached to this agent from its card
        agent_tools = (card or {}).get("tools", [])
        workspace = (card or {}).get("workspace", "shared")

        # Build the tool execution registry
        _, tool_registry = build_tool_defs(
            agent_tools,
            workspace=workspace,
        )

        # This function allows ADK to execute tools from the registry
        async def run_attached_tool(tool_name: str, arguments: dict) -> dict:
            """Execute a tool attached to this agent.

            Args:
                tool_name: Exact name of the tool to run.
                arguments: Input values required by the tool.

            Returns:
                Result returned by the tool.
            """
            import asyncio as _asyncio
            result = await _asyncio.to_thread(
                execute_tool,
                tool_registry,
                tool_name,
                arguments or {},
            )

            try:
                return json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return {"result": str(result)}

        # Give the dispatcher to ADK only when tools are available
        adk_tools = [run_attached_tool] if tool_registry else []

        # Native ADK MCP integration (official pattern): for any MCP server bound to this agent,
        # add a real McpToolset to the agent's tools so the ADK agent discovers and calls those
        # tools directly. Additive — no-op if the agent has no MCP servers or google-adk[mcp]
        # isn't installed (the generic seam above still serves MCP tools in that case).
        try:
            from .adk_mcp import build_mcp_toolsets
            adk_tools.extend(build_mcp_toolsets(agent_tools))
        except Exception:
            pass

        # Step-scoped tools (e.g. the governed ontology traversal action)
        adk_tools.extend(extra_tools or [])

        # Tell the model which tools it can request
        if tool_registry:
            instruction += (
                "\n\nYou have access to these tools: "
                + ", ".join(tool_registry.keys())
                + ". Use run_attached_tool when a tool is needed. "
                + "Pass the exact tool name in tool_name and its input in arguments."
            )
        instruction += extra_instruction

        return LlmAgent(
            name=_adk_name(agent_name),
            model=self._model_for(mc),
            instruction=instruction,
            tools=adk_tools,
        )

    async def _emit(self, rid, kind, **kw):
        ev = ActivityEvent(run_id=rid, seq=bus.next_seq(rid), kind=kind,
                           label=kw.pop("label", "") or narrate(kind, kw.get("detail", {})), **kw)
        await bus.publish(ev)

    async def execute(self, run: Run, workflow: WorkflowGraph) -> None:  # pragma: no cover
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types
        from ..ontology.runtime_context import build_step_context

        rid = run.run_id
        plan = compile_workflow(workflow)
        run.status = RunStatus.running
        runs_repo.upsert(run.model_dump(by_alias=True))
        await self._emit(rid, ActivityKind.phase, phase="plan",
                         label=f"Planning '{workflow.name}' ({len(plan)} steps)...")

        session_service = InMemorySessionService()
        goal = workflow.goal_prompt or ""
        user_request = _user_request(run.input)
        query_text = f"{goal} {user_request}".strip()     # what the ontology resolves against
        prior = ""                                        # ALL upstream results, like live
        total_in = 0
        total_out = 0

        for step in plan:
            agent_name = step["agent"]
            node_id = step["node_id"]
            await self._emit(rid, ActivityKind.agent_enter, node_id=node_id,
                             agent=agent_name, detail={"agent": agent_name})

            # --- single ontology seam (spec A§2/A§13) -------------------------------------
            async def _onto_emit(label: str, level: str = "info", _n=node_id, _a=agent_name):
                await self._emit(rid, ActivityKind.phase, phase="ontology", label=label,
                                 level=level, node_id=_n, agent=_a)

            octx = await build_step_context(
                run=run, workflow_id=run.workflow_id or "", agent=agent_name, node_id=node_id,
                query_text=query_text, upstream=prior, emit=_onto_emit, runtime="adk")
            extra_tools = [octx.neighbors_tool] if octx.neighbors_tool else []
            extra_instruction = (
                "\n\nThe user message contains authoritative knowledge-graph context. To explore "
                "more relationships of an entity named there, call ontology_get_neighbors with the "
                "entity name (and optionally a relation type)."
            ) if extra_tools else ""

            agent = self._build_agent(agent_name, extra_tools, extra_instruction)
            runner = Runner(agent=agent, app_name="platform", session_service=session_service)
            await session_service.create_session(app_name="platform", user_id="u",
                                                 session_id=f"{rid}:{node_id}")
            prompt_text = (f"Task: {goal}\n"
                           f"User input: {user_request}\n"
                           + (f"\n{octx.prompt_block}" if octx.prompt_block else "")
                           + (f"\nUpstream results:\n{prior}\n" if prior else "")
                           + f"\nProduce the output for your role as {agent_name}. "
                             f"Be concise and finish.")
            msg = types.Content(role="user", parts=[types.Part(text=prompt_text)])

            out = ""
            usage_in = usage_out = 0
            from .. import tracing
            with tracing.span(f"agent:{agent_name}",
                              inputs={"prompt": prompt_text},
                              attributes={"agent": agent_name, "run_id": rid,
                                          "ontology_used": octx.used,
                                          "ontology_provider": octx.provider,
                                          "ontology_hops": octx.hops}) as sp:
                async for event in runner.run_async(user_id="u", session_id=f"{rid}:{node_id}",
                                                    new_message=msg):
                    um = getattr(event, "usage_metadata", None)
                    if um:
                        usage_in = getattr(um, "prompt_token_count", 0) or usage_in
                        usage_out = getattr(um, "candidates_token_count", 0) or usage_out
                    for part in (event.content.parts if event.content else []):
                        if getattr(part, "text", None):
                            out += part.text
                            await self._emit(rid, ActivityKind.token, node_id=node_id,
                                             agent=agent_name, label=part.text,
                                             token_delta=len(part.text.split()))
                        if getattr(part, "function_call", None):
                            await self._emit(rid, ActivityKind.tool_call, node_id=node_id,
                                             agent=agent_name, detail={"tool": part.function_call.name})
                tracing.set_outputs(sp, {"output": out, "in_tokens": usage_in, "out_tokens": usage_out})

            if not out.strip():
                out = "(the model returned no content for this step)"
            in_tok = usage_in or len(prompt_text.split())
            out_tok = usage_out or len(out.split())
            total_in += in_tok
            total_out += out_tok
            node_out = {"node_id": node_id, "agent": agent_name, "output": out,
                        "steps": [], "in_tokens": in_tok, "out_tokens": out_tok}
            if octx.record:                      # complete ontology result: UI source of truth
                node_out["ontology"] = octx.record
            run.node_outputs.append(node_out)
            run.input_tokens, run.output_tokens = total_in, total_out
            run.tokens = total_in + total_out
            runs_repo.upsert(run.model_dump(by_alias=True))
            prior += f"\n[{agent_name}]: {out}"
            await self._emit(rid, ActivityKind.agent_exit, node_id=node_id, agent=agent_name,
                             label=f"{agent_name} finished.")

            if node_id in workflow.approval_gates:
                run.status = RunStatus.awaiting_approval
                runs_repo.upsert(run.model_dump(by_alias=True))
                await self._emit(rid, ActivityKind.approval_pending, node_id=node_id,
                                 level="warn", phase="verify",
                                 label="Waiting for your approval before continuing...")
                return

        run.status = RunStatus.succeeded
        run.input_tokens = total_in
        run.output_tokens = total_out
        run.tokens = total_in + total_out
        outs = [n["output"] for n in run.node_outputs if n.get("output", "").strip()]
        run.final_output = outs[-1] if outs else ""
        runs_repo.upsert(run.model_dump(by_alias=True))
        await self._emit(rid, ActivityKind.complete, phase="done",
                         label="Workflow complete. Deliverable ready for review.")
