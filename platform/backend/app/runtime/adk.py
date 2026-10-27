"""AdkRuntime — production executor on the open-source Google ADK framework.

Models are reached via ADK's `LiteLlm` wrapper over **APIs** (Mistral, Gemini) —
there is NO Google Cloud / Vertex *platform* dependency. Sessions and memory use
ADK's in-memory services, so nothing external is required beyond a model API key.

Activate:
  pip install google-adk litellm
  export RUNTIME=adk MODEL_PROVIDER=mistral MISTRAL_API_KEY=...
    (or MODEL_PROVIDER=gemini GEMINI_API_KEY=...)

The event loop maps ADK Events -> ActivityEvents on the same bus the mock uses,
so the frontend is identical whether running mock or real.
"""
from __future__ import annotations
import json

from ..tool_exec import build_tool_defs, execute_tool
from ..activity import bus, narrate
from ..factory import compile_workflow
from ..models import DEFAULTS, PROVIDER, to_litellm_model
from ..schemas import ActivityEvent, ActivityKind, Run, RunStatus, WorkflowGraph
from ..store import agents as agents_repo
from ..store import runs as runs_repo


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

    def _build_agent(self, agent_name: str):
        from google.adk.agents import LlmAgent
        from google.adk.models.lite_llm import LiteLlm

        matches = agents_repo.list(lambda a: a["agent_name"] == agent_name)
        card = matches[0] if matches else None
        mc = (card or {}).get("model_config", {})
        instruction = (card or {}).get("prompts", {}).get("system_prompt") or f"You are {agent_name}."
                # Load the tools attached to this agent from JSON
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

        # Tell the model which tools it can request
        if tool_registry:
            instruction += (
                "\n\nYou have access to these tools: "
                + ", ".join(tool_registry.keys())
                + ". Use run_attached_tool when a tool is needed. "
                + "Pass the exact tool name in tool_name and its input in arguments."
            )
        # 1) UI-configured model endpoint (Azure/OpenAI/Mistral/Gemini) takes priority
        eid = mc.get("endpoint_id")
        if eid:
            from ..endpoints import get_full, litellm_call_args
            ep = get_full(eid)
            if ep:
                args = litellm_call_args(ep)
                model = LiteLlm(model=args["model"], **args["params"])
                return LlmAgent(
                    name=agent_name.replace(" ", "_").replace("/", "_"),
                    model=model,
                    instruction=instruction,
                    tools=adk_tools,
                )

        # 2) fall back to env-based provider (MODEL_PROVIDER + *_API_KEY)
        prov = mc.get("provider") or PROVIDER
        model_name = mc.get("model") or DEFAULTS.get(prov)
        lit = to_litellm_model(model_name, prov)
        model = lit if prov == "gemini" else LiteLlm(model=lit)
        return LlmAgent(
            name=agent_name.replace(" ", "_").replace("/", "_"),
            model=model,
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

        rid = run.run_id
        plan = compile_workflow(workflow)
        run.status = RunStatus.running
        runs_repo.upsert(run.model_dump(by_alias=True))
        await self._emit(rid, ActivityKind.phase, phase="plan",
                         label=f"Planning '{workflow.name}' ({len(plan)} steps)...")

        session_service = InMemorySessionService()
        prior = ""
        total_in = 0
        total_out = 0

        for step in plan:
            agent_name = step["agent"]
            node_id = step["node_id"]
            await self._emit(rid, ActivityKind.agent_enter, node_id=node_id,
                             agent=agent_name, detail={"agent": agent_name})

            agent = self._build_agent(agent_name)
            runner = Runner(agent=agent, app_name="platform", session_service=session_service)
            await session_service.create_session(app_name="platform", user_id="u",
                                                 session_id=f"{rid}:{node_id}")
            prompt_text = f"Goal: {workflow.goal_prompt}\nInput: {run.input}\nUpstream: {prior}"
            msg = types.Content(role="user", parts=[types.Part(text=prompt_text)])

            out = ""
            usage_in = usage_out = 0
            from .. import tracing
            with tracing.span(f"agent:{agent_name}",
                              inputs={"prompt": prompt_text},
                              attributes={"agent": agent_name, "run_id": rid}) as sp:
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

            in_tok = usage_in or len(prompt_text.split())
            out_tok = usage_out or len(out.split())
            total_in += in_tok
            total_out += out_tok
            run.node_outputs.append({"node_id": node_id, "agent": agent_name, "output": out,
                                     "steps": [], "in_tokens": in_tok, "out_tokens": out_tok})
            run.input_tokens, run.output_tokens = total_in, total_out
            run.tokens = total_in + total_out
            runs_repo.upsert(run.model_dump(by_alias=True))
            prior = out
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
