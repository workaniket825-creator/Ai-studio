"""Agent access to a DSLab runtime.

`enable(rid)` registers the runtime's built-in MCP server (app/mcp_servers/dslab_runtime.py,
stdio, one registry entry per runtime: mcp_dslab_<rid>) and optionally creates a ready-to-run
"DSLab Code Runner" agent + single-agent workflow bound to it. Any other agent can be given
the same access in the Agent wizard (Tools > MCP servers > "DSLab · <runtime>").
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import store as dsl_store

_RUNNER_PROMPT = (
    "You are a code-execution agent working on the DSLab runtime '{name}', a remote machine "
    "registered in the Data Science Lab. You MUST use your tools to do real work there:\n"
    "- run_python: execute Python (state persists between calls; print() what you need to see)\n"
    "- run_shell: run shell commands (nvidia-smi, pip, ls, git, python scripts)\n"
    "- runtime_info: hostname, Python, working dir, GPUs\n"
    "- list_files / read_file / write_file: the lab workspace\n"
    "- run_notebook / add_cell: execute notebooks and add cells (outputs are saved)\n"
    "Always execute code instead of guessing results, report the ACTUAL outputs, and say which "
    "files, cells or commands you used. For long jobs, write a script with write_file and run it "
    "with run_shell. If a tool returns ERROR, explain it and suggest the fix."
)


def server_id(rid: str) -> str:
    return f"mcp_dslab_{rid}"


def _server_spec(rt: dict) -> dict:
    rid = rt["id"]
    api_base = os.getenv("DSLAB_API_BASE", f"http://127.0.0.1:{os.getenv('BACKEND_PORT', '8099')}")
    pkg_root = str(Path(__file__).resolve().parents[3])   # dir that contains the `app` package
    return {
        "id": server_id(rid),
        "name": f"DSLab · {rt.get('name', rid)}",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.mcp_servers.dslab_runtime"],
        "env": {"DSLAB_RUNTIME_ID": rid, "DSLAB_RUNTIME_NAME": rt.get("name", rid),
                "DSLAB_API_BASE": api_base, "PYTHONPATH": pkg_root, "DSLAB_AUTO_OPEN": "1"},
        "enabled": True,
        "timeout": 60,
    }


def _pick_endpoint(explicit: str = "") -> str:
    if explicit:
        return explicit
    try:
        from ...endpoints import list_endpoints
        chats = [e for e in list_endpoints() if (e.get("type") or "chat") == "chat"]
        return chats[0]["id"] if chats else ""
    except Exception:
        return ""


def _bind(agent: dict, sid: str, sname: str) -> bool:
    tools = agent.get("tools") or []
    if any(t.get("type") == "mcp" and t.get("ref") == sid for t in tools):
        return False
    tools.append({"type": "mcp", "ref": sid, "name": sname})
    agent["tools"] = tools
    return True


def enable(rid: str, body: dict) -> dict:
    from ... import mcp_store, mcp_client
    from ...store import agents as agents_repo, workflows as workflows_repo
    from ...schemas import (AgentCard, AgentCategory, IOContract, ModelConfig, Prompts,
                            WorkflowGraph, WorkflowNode)

    rt = dsl_store.get_runtime(rid)
    if not rt:
        return {"ok": False, "error": "not_found"}
    dsl_store.ensure_jupyter_token(rid)
    spec = _server_spec(rt)
    sid = spec["id"]
    if mcp_store.get_server(sid):
        mcp_store.update_server(sid, {k: v for k, v in spec.items() if k != "id"})
    else:
        mcp_store.add_server(spec)
    dsl_store.set_internal(rid, {"agent_mcp_server": sid})
    out: dict = {"ok": True, "server_id": sid, "server_name": spec["name"]}

    check = mcp_client.test_connection(mcp_store.get_server(sid))
    out["tools"] = check.get("tools", [])
    if not check.get("ok"):
        out["ok"] = False
        out["detail"] = f"MCP server registered but could not start: {check.get('detail')}"
        return out
    if check.get("note"):
        out["note"] = check["note"]

    # bind to any agents the caller listed
    bound = []
    for aid in body.get("agent_ids") or []:
        a = agents_repo.get(aid)
        if a and _bind(a, sid, spec["name"]):
            agents_repo.upsert(a)
            bound.append(a.get("agent_name"))
    out["bound_agents"] = bound

    if body.get("create_agent", True):
        aname = f"DSLab Code Runner · {rt.get('name', rid)}"
        existing = agents_repo.list(lambda a: a.get("agent_name") == aname)
        endpoint_id = _pick_endpoint(body.get("endpoint_id", ""))
        if existing:
            agent = existing[0]
            _bind(agent, sid, spec["name"])
            if endpoint_id and not (agent.get("model_config") or {}).get("endpoint_id"):
                agent.setdefault("model_config", {})["endpoint_id"] = endpoint_id
            agents_repo.upsert(agent)
        else:
            card = AgentCard(
                agent_name=aname, role="DSLab Code Runner", category=AgentCategory.use_case,
                description=f"Runs Python, shell commands and notebooks on the DSLab runtime "
                            f"'{rt.get('name', rid)}' and reports the real outputs.",
                tags=["dslab", "code", "mcp"],
                model_config=ModelConfig(endpoint_id=endpoint_id or None,
                                         model="gpt-4o-mini", temperature=0.1),
                prompts=Prompts(system_prompt=_RUNNER_PROMPT.format(name=rt.get("name", rid))),
                io_contract=IOContract(output_key="execution_result"),
                tools=[{"type": "mcp", "ref": sid, "name": spec["name"]}],
                tool_policy="required",
                owner={"user_id": "system", "team": "dslab"},
            )
            agent = card.model_dump(by_alias=True)
            agents_repo.upsert(agent)
        out.update({"agent_id": agent["agent_id"], "agent_name": aname,
                    "model_endpoint_set": bool((agent.get("model_config") or {}).get("endpoint_id"))})

        wname = f"DSLab Code Execution · {rt.get('name', rid)}"
        wf = next(iter(workflows_repo.list(lambda w: w.get("name") == wname)), None)
        if not wf:
            g = WorkflowGraph(
                name=wname,
                goal_prompt=(f"Carry out the user's request by executing code on the DSLab runtime "
                             f"'{rt.get('name', rid)}' and report the real results."),
                nodes=[WorkflowNode(node_id="n1", agent_ref=f"agent_cards/{aname}",
                                    output_key="execution_result",
                                    input_bindings={"instruction": "workflow.input.message"})],
                config={"max_iterations": 5, "category": "dslab"},
            )
            wf = g.model_dump(by_alias=True)
            workflows_repo.upsert(wf)
        out.update({"workflow_id": wf["workflow_id"], "workflow_name": wname})
    return out


def revoke(rid: str) -> bool:
    from ... import mcp_store
    sid = server_id(rid)
    ok = mcp_store.delete_server(sid) if mcp_store.get_server(sid) else False
    try:
        dsl_store.set_internal(rid, {"agent_mcp_server": ""})
    except Exception:
        pass
    return ok
