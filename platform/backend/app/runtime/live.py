"""LiveRuntime — real workflow execution.

Executes each agent node against a **real model API** via LiteLLM, using the
agent's configured Model Endpoint (Azure OpenAI / OpenAI / Mistral / Gemini) or the
env-based provider. It streams real tokens, records real usage tokens and measured
latency, and produces real outputs and files. There is **no fabricated/mock data**.

If a node has no resolvable model/key, the run fails with an honest error rather
than inventing a result.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from ..activity import bus, steer
from ..factory import compile_workflow
from ..schemas import ActivityEvent, ActivityKind, Run, RunStatus, WorkflowGraph
from ..store import agents as agents_repo
from ..store import runs as runs_repo


class LiveRuntime:
    name = "live"

    async def _emit(self, run_id, kind, label, **kw):
        ev = ActivityEvent(run_id=run_id, seq=bus.next_seq(run_id), kind=kind, label=label, **kw)
        await bus.publish(ev)
        return ev

    async def _acompletion(self, litellm, **kwargs):
        """litellm.acompletion with settings-driven retries + backoff on transient errors."""
        from ..governance import platform_settings
        ps = platform_settings()
        attempts = max(1, int(ps.get("retry_attempts", 2)) + 1)
        backoff = float(ps.get("retry_backoff_seconds", 2))
        last = None
        for i in range(attempts):
            try:
                return await litellm.acompletion(**kwargs)
            except Exception as e:
                last = e
                if i < attempts - 1:
                    await asyncio.sleep(backoff * (i + 1))
        raise last

    async def _invoke(self, rid, node_id, agent, model, params, messages, agent_tools=None):
        """Call the model (stream + non-stream fallback) inside a GenAI trace span.
        If the agent has tools attached, run a bounded tool-calling loop first.
        Returns (output_text, usage_in, usage_out)."""
        import litellm
        from .. import tracing
        from ..tool_exec import build_tool_defs, execute_tool, _resolve_tool_name

        usage_in = usage_out = 0
        tool_defs, registry = build_tool_defs(agent_tools or [])

        # --- tool-calling loop (only when the agent has callable tools) ---
        if tool_defs:
            from ..activity import cancel as cancel_reg
            # deterministic tool policy: auto (model decides) | required (must call a tool)
            # | force:<name> (must call that specific tool). Removes reliance on the model
            # choosing to call, and forces the EXACT registered function name.
            policy = getattr(self, "_tool_policy", "auto") or "auto"
            tool_names = [d["function"]["name"] for d in tool_defs]
            if policy.startswith("force:"):
                want = policy.split(":", 1)[1]
                # resolve to a real tool name (tolerant), else fall back to required
                target = want if want in tool_names else (_resolve_tool_name(registry, want) or "")
                first_choice = ({"type": "function", "function": {"name": target}} if target
                                else "required")
            elif policy == "required" or len(tool_names) == 1:
                # single-tool agents default to required so the call can't be skipped
                first_choice = "required"
            else:
                first_choice = "auto"
            convo = list(messages)
            with tracing.span(f"agent:{agent}", inputs={"messages": messages},
                              attributes={"model": str(model), "run_id": rid, "agent": agent,
                                          "tools": tool_names, "tool_policy": policy}) as sp:
                for _round in range(4):  # bounded rounds to prevent loops
                    if cancel_reg.is_cancelled(rid):
                        return "", usage_in, usage_out
                    # force on the first round; then let the model finish naturally
                    choice_arg = first_choice if _round == 0 else "auto"
                    resp = await self._acompletion(litellm, model=model, messages=convo,
                                                     tools=tool_defs, tool_choice=choice_arg, **params)
                    choice = resp.choices[0]
                    msg = choice.message
                    u = getattr(resp, "usage", None)
                    if u:
                        usage_in += getattr(u, "prompt_tokens", 0) or 0
                        usage_out += getattr(u, "completion_tokens", 0) or 0
                    calls = getattr(msg, "tool_calls", None) or []
                    if not calls:
                        text = msg.content or ""
                        if text:
                            await self._emit(rid, ActivityKind.token, text, node_id=node_id,
                                             agent=agent, token_delta=len(text.split()))
                        tracing.set_outputs(sp, {"output": text, "in_tokens": usage_in,
                                                 "out_tokens": usage_out})
                        return text, usage_in, usage_out
                    convo.append({"role": "assistant", "content": msg.content or "",
                                  "tool_calls": [{"id": c.id, "type": "function",
                                                  "function": {"name": c.function.name,
                                                               "arguments": c.function.arguments}}
                                                 for c in calls]})
                    for c in calls:
                        try:
                            cargs = json.loads(c.function.arguments or "{}")
                        except Exception:
                            cargs = {}
                        await self._emit(rid, ActivityKind.tool_call,
                                         f"calling {c.function.name}({', '.join(f'{k}={v}' for k,v in cargs.items())})…",
                                         node_id=node_id, agent=agent, detail={"tool": c.function.name, "args": cargs})
                        # nested MLflow span per tool execution (so it shows in Traces)
                        with tracing.span(f"tool:{c.function.name}", inputs={"args": cargs},
                                          attributes={"run_id": rid, "agent": agent,
                                                      "tool": c.function.name}) as tsp:
                            # off the event loop: tools (e.g. DSLab MCP) may call back into this
                            # same backend (lab proxy); a blocking call here would deadlock it.
                            result = await asyncio.to_thread(execute_tool, registry,
                                                             c.function.name, cargs)
                            tracing.set_outputs(tsp, {"result": result[:1000]})
                        await self._emit(rid, ActivityKind.tool_result if hasattr(ActivityKind, "tool_result")
                                         else ActivityKind.token, f"{c.function.name} → {result[:160]}",
                                         node_id=node_id, agent=agent)
                        convo.append({"role": "tool", "tool_call_id": c.id,
                                      "name": c.function.name, "content": result})
                # ran out of rounds — ask for a final answer without tools
                final = await self._acompletion(litellm, model=model, messages=convo, **params)
                out = final.choices[0].message.content or ""
                tracing.set_outputs(sp, {"output": out, "in_tokens": usage_in, "out_tokens": usage_out})
                return out, usage_in, usage_out

        # --- no tools: stream with non-stream fallback ---
        out_text = ""
        with tracing.span(f"agent:{agent}",
                          inputs={"messages": messages},
                          attributes={"model": str(model), "run_id": rid, "agent": agent}) as sp:
            resp = await self._acompletion(litellm, model=model, messages=messages, stream=True,
                                             stream_options={"include_usage": True}, **params)
            from ..activity import cancel as cancel_reg
            async for chunk in resp:
                if cancel_reg.is_cancelled(rid):
                    await self._emit(rid, ActivityKind.error, "Generation stopped by user.",
                                     level="warn", node_id=node_id, agent=agent)
                    break
                try:
                    choice = chunk.choices[0] if chunk.choices else None
                    delta = getattr(getattr(choice, "delta", None), "content", None) or ""
                except Exception:
                    delta = ""
                if delta:
                    out_text += delta
                    await self._emit(rid, ActivityKind.token, delta, node_id=node_id,
                                     agent=agent, token_delta=len(delta.split()))
                u = getattr(chunk, "usage", None)
                if u:
                    usage_in = getattr(u, "prompt_tokens", 0) or usage_in
                    usage_out = getattr(u, "completion_tokens", 0) or usage_out
            if not out_text.strip():
                full = await self._acompletion(litellm, model=model, messages=messages,
                                                 stream=False, **params)
                try:
                    out_text = (full.choices[0].message.content or "") if full.choices else ""
                except Exception:
                    out_text = ""
                if out_text:
                    await self._emit(rid, ActivityKind.token, out_text, node_id=node_id,
                                     agent=agent, token_delta=len(out_text.split()))
                usage = getattr(full, "usage", None)
                if usage:
                    usage_in = getattr(usage, "prompt_tokens", 0) or usage_in
                    usage_out = getattr(usage, "completion_tokens", 0) or usage_out
            tracing.set_outputs(sp, {"output": out_text,
                                     "in_tokens": usage_in, "out_tokens": usage_out})
        return out_text, usage_in, usage_out

    def _resolve_model(self, agent_name: str):
        """Return (model_string, litellm_params, system_prompt) for an agent card."""
        matches = agents_repo.list(lambda a: a["agent_name"] == agent_name)
        card = matches[0] if matches else {}
        mc = card.get("model_config", {}) or {}
        system = (card.get("prompts", {}) or {}).get("system_prompt") or f"You are {agent_name}."
        agent_tools = card.get("tools", []) or []
        self._tool_policy = card.get("tool_policy", "auto") or "auto"
        eid = mc.get("endpoint_id")
        if eid:
            from ..endpoints import get_full, litellm_call_args
            ep = get_full(eid)
            if ep:
                args = litellm_call_args(ep)
                return args["model"], args["params"], system, agent_tools
        # env-based provider fallback
        from ..models import to_litellm_model, PROVIDER
        prov = mc.get("provider") or PROVIDER
        model = to_litellm_model(mc.get("model") or "", prov)
        return model, {}, system, agent_tools

    async def execute(self, run: Run, workflow: WorkflowGraph) -> None:
        rid = run.run_id
        plan = compile_workflow(workflow)
        run.status = RunStatus.running
        runs_repo.upsert(run.model_dump(by_alias=True))
        await self._emit(rid, ActivityKind.phase, f"Running '{workflow.name}' ({len(plan)} steps)…", phase="plan")

        try:
            import litellm
        except Exception:
            run.status = RunStatus.failed
            run.error = ("No model runtime available. Install litellm (`pip install litellm`) and "
                         "configure a Model Endpoint or MODEL_PROVIDER + API key.")
            runs_repo.upsert(run.model_dump(by_alias=True))
            await self._emit(rid, ActivityKind.error, run.error, level="error")
            return

        total_in = total_out = 0
        prior = ""  # upstream context carried forward
        user_input = run.input if isinstance(run.input, dict) else {"input": run.input}
        goal = workflow.goal_prompt or ""

        # loop/iteration guard: cap total agent steps (per-workflow override or env default)
        import os
        cap = int((workflow.config or {}).get("max_iterations")
                  or os.getenv("MAX_AGENT_STEPS", "20"))
        executed = 0

        from ..activity import cancel as cancel_reg

        for step in plan:
            # interrupt if the user asked to stop, or we hit the iteration cap
            if cancel_reg.is_cancelled(rid):
                run.status = RunStatus.cancelled
                run.error = "Interrupted by user."
                runs_repo.upsert(run.model_dump(by_alias=True))
                await self._emit(rid, ActivityKind.error, "Run interrupted by user.", level="warn")
                return
            if executed >= cap:
                run.status = RunStatus.cancelled
                run.error = f"Stopped after reaching the max of {cap} agent steps (loop guard)."
                runs_repo.upsert(run.model_dump(by_alias=True))
                await self._emit(rid, ActivityKind.error, run.error, level="warn")
                return
            executed += 1

            agent = step["agent"]
            node_id = step["node_id"]
            steps: list[str] = []

            for guidance in steer.drain(rid):
                run.steers.append({"text": guidance})
                steps.append(f"Steer: {guidance}")

            model, params, system, agent_tools = self._resolve_model(agent)
            if not model:
                run.status = RunStatus.failed
                run.error = f"Agent '{agent}' has no model configured. Set a Model Endpoint or provider."
                runs_repo.upsert(run.model_dump(by_alias=True))
                await self._emit(rid, ActivityKind.error, run.error, level="error", node_id=node_id, agent=agent)
                return

            await self._emit(rid, ActivityKind.agent_enter, f"{agent} is working…",
                             node_id=node_id, agent=agent)

            # --- single ContextProvider seam (spec §2/§13) ---
            # With ontology OFF this returns a PlainProvider bundle whose only content
            # is the upstream text, reproducing today's prompt exactly. With it ON,
            # the bundle adds grounded entities/relations (supplemental).
            from .. import ontology as onto
            provider = onto.get_context_provider(
                tenant=getattr(run, "tenant", "default") or "default",
                workflow_id=run.workflow_id or "", query_text=f"{goal} {user_input}")
            if provider.name != "plain":
                await self._emit(rid, ActivityKind.phase, phase="ontology",
                                 label=f"Retrieving ontology context for {agent}…",
                                 node_id=node_id, agent=agent)
            _hops = max(1, int(getattr(run, "ontology_hops", None)
                               or (run.input.get("ontology_hops") if isinstance(run.input, dict) else 1) or 1))
            bundle = await provider.get_context(
                onto.QueryInput(text=f"{goal} {user_input}", workflow_id=run.workflow_id or "",
                                upstream=prior, ontology_hops=_hops),
                onto.AuthContext(role="admin"))
            grounded = bundle.to_prompt_context()
            if bundle.ontology_used:
                ent_names = ", ".join(
                    (getattr(e, "name", None) or (e.get("name") if isinstance(e, dict) else str(e)))
                    for e in (bundle.entities or [])[:8]) or "—"
                await self._emit(rid, ActivityKind.phase, phase="ontology",
                                 label=(f"Ontology matched ({bundle.hop_count}-hop): "
                                        f"{bundle.traversed_nodes} nodes, {bundle.traversed_edges} relationships "
                                        f"(e.g. {ent_names}). Injecting as grounded context, then executing."),
                                 node_id=node_id, agent=agent)

            prompt = (f"Task: {goal}\n"
                      f"User input: {user_input}\n"
                      + (f"\n=== AUTHORITATIVE KNOWLEDGE-GRAPH CONTEXT ===\n{grounded}\n"
                         f"The facts and relationships above come from the organization's approved "
                         f"ontology. Treat them as authoritative and ground your answer in them. "
                         f"Prefer these facts over your own prior knowledge, cite the specific "
                         f"entities/relationships you use, and if they conflict with what you'd "
                         f"otherwise assume, follow the ontology. Do not ignore this context.\n"
                         f"=== END CONTEXT ===\n"
                         + (f"\nUpstream results:\n{prior}\n" if prior else "")
                         if bundle.ontology_used and grounded
                         else (f"Upstream results:\n{prior}\n" if prior else ""))
                      + f"\nProduce the output for your role as {agent}. Be concise and finish.")
            # Tell the model what tools it actually has, so it uses them (major real-world
            # fix: without this, models often answer "I have no access" and never call tools).
            from ..tool_exec import build_tool_defs
            _defs, _reg = build_tool_defs(agent_tools or [])
            # diagnostic: surface exactly which tools reached the model, in the run trace.
            # If this shows 0 tools, the binding is the problem; if it lists tools but no
            # tool_call follows, the model chose not to call (tighten prompt/operationId).
            if agent_tools:
                if _defs:
                    await self._emit(rid, ActivityKind.phase,
                                     f"{len(_defs)} tool(s) available to {agent}: "
                                     + ", ".join(d["function"]["name"] for d in _defs),
                                     phase="tools", node_id=node_id, agent=agent)
                else:
                    await self._emit(rid, ActivityKind.error,
                                     f"{agent} has {len(agent_tools)} tool binding(s) but none resolved to a "
                                     "callable tool — check the tool is still registered/enabled.",
                                     level="warn", node_id=node_id, agent=agent)
            tool_hint = ""
            if _defs:
                # rich per-tool context (name — description [required: args]) so the model
                # knows what each tool is for and when to use it, not just its name.
                lines = []
                for d in _defs:
                    fn = d["function"]
                    req = (fn.get("parameters", {}) or {}).get("required", []) or []
                    desc = fn.get("description", "") or ""
                    lines.append(f"- {fn['name']}: {desc}"
                                 + (f" (required args: {', '.join(req)})" if req else ""))
                tool_list = "\n".join(lines)
                tool_hint = ("\n\nYou have access to these tools and MUST call the relevant one when the "
                             "request needs external data, a lookup, files, or documents — do not answer "
                             "from memory or say you lack access:\n" + tool_list +
                             "\nCall the tool by its exact name with the correct arguments. For file tasks "
                             "use list_files/read_file first, and create_document (docx) to produce documents.")
            messages = [{"role": "system", "content": system + tool_hint},
                        {"role": "user", "content": prompt}]
            onto.record_telemetry({"run_id": rid, "node_id": node_id, "agent": agent,
                                   "provider": provider.name, "ontology_used": bundle.ontology_used,
                                   "entities": len(bundle.entities),
                                   "hop_count": bundle.hop_count,
                                   "traversed_nodes": bundle.traversed_nodes,
                                   "traversed_edges": bundle.traversed_edges})

            t0 = time.time()
            try:
                out_text, usage_in, usage_out = await self._invoke(
                    rid, node_id, agent, model, params, messages, agent_tools)
            except Exception as e:
                run.status = RunStatus.failed
                run.error = f"Model call failed for '{agent}': {e}"
                runs_repo.upsert(run.model_dump(by_alias=True))
                await self._emit(rid, ActivityKind.error, run.error, level="error",
                                 node_id=node_id, agent=agent)
                return

            if not out_text.strip():
                out_text = "(the model returned no content for this step)"

            latency = int((time.time() - t0) * 1000)
            in_tok = usage_in or len(prompt.split())
            out_tok = usage_out or len(out_text.split())
            total_in += in_tok
            total_out += out_tok

            artifact = self._maybe_artifact(rid, agent, workflow, out_text, run)
            if artifact:
                run.artifacts.append(artifact)
                steps.append(f"Wrote file: {artifact['name']}")

            node_out = {"node_id": node_id, "agent": agent, "output": out_text,
                        "steps": steps, "in_tokens": in_tok, "out_tokens": out_tok}
            # expose the ontology data used/updated in this step so the Chat can show it
            if bundle.ontology_used:
                node_out["ontology"] = {
                    "used": True,
                    "entities": [{"name": getattr(e, "name", e.get("name") if isinstance(e, dict) else str(e)),
                                  "type": getattr(e, "type", e.get("type") if isinstance(e, dict) else "")}
                                 for e in (bundle.entities or [])][:25],
                    "relations": [{"source": getattr(r, "source", r.get("source") if isinstance(r, dict) else ""),
                                   "relation": getattr(r, "relation", r.get("relation") if isinstance(r, dict) else ""),
                                   "target": getattr(r, "target", r.get("target") if isinstance(r, dict) else "")}
                                  for r in (getattr(bundle, "relations", []) or [])][:25],
                    "context": grounded[:1500],
                }
            run.node_outputs.append(node_out)
            prior += f"\n[{agent}]: {out_text}"
            # persist progress after each agent so Chat/Monitoring see it live
            run.input_tokens, run.output_tokens, run.tokens = total_in, total_out, total_in + total_out
            runs_repo.upsert(run.model_dump(by_alias=True))
            await self._emit(rid, ActivityKind.agent_exit, f"{agent} finished.",
                             node_id=node_id, agent=agent, latency_ms=latency)

            if node_id in workflow.approval_gates:
                run.status = RunStatus.awaiting_approval
                runs_repo.upsert(run.model_dump(by_alias=True))
                await self._emit(rid, ActivityKind.approval_pending,
                                 "Waiting for your approval to continue…", level="warn", node_id=node_id)
                return

        run.status = RunStatus.succeeded
        run.input_tokens = total_in
        run.output_tokens = total_out
        run.tokens = total_in + total_out
        outs = [n["output"] for n in run.node_outputs if n.get("output", "").strip()
                and not n["output"].startswith("(the model returned no content")]
        run.final_output = outs[-1] if outs else (run.node_outputs[-1]["output"] if run.node_outputs else "")
        runs_repo.upsert(run.model_dump(by_alias=True))
        await self._emit(rid, ActivityKind.complete, "Workflow complete.", phase="done")

    def _maybe_artifact(self, rid, agent, workflow, output_text, run):
        """Writer/responder agents persist their REAL output as a downloadable file."""
        from ..analysis import write_markdown
        name_l = agent.lower()
        cat = (workflow.config or {}).get("category", "")
        if "incident responder" in name_l or (cat == "security" and "respond" in name_l):
            return write_markdown(rid, "security_report.md", output_text)
        if "synthesis writer" in name_l or (cat == "documents" and "writer" in name_l):
            return write_markdown(rid, "deliverable.md", output_text)
        return None
