# DSLab ↔ Agent access fix (v1.0 build 33)

## Problems fixed
1. **Jupyter MCP never linked to DSLab from the UI.** `/mcp/jupyter/link/{rid}` existed but no screen called it.
2. **Jupyter rejected agent traffic.** Lab Jupyter listened on 127.0.0.1 without a token: requests from the
   jupyter-mcp container (Host `backend:<port>`) failed Jupyter's Host check (403) and token-less POSTs fail XSRF (403).
3. **Unstable link target.** The link used the ephemeral SSH-tunnel port, invalid after every lab reopen/restart.
4. **Re-opening a lab failed.** The launch script backgrounded `cd && nohup …` as a subshell (held the SSH channel
   open, PID file pointed at the subshell); a still-running lab was always reported as `wrong_existing_process`.
5. **MCP SDK 2.x incompatibility** in `mcp_client.py` (`streamablehttp_client` and `Tool.inputSchema` renamed).
6. **Possible event-loop deadlock**: tools ran synchronously on the backend's event loop.
7. Jupyter refused to start when the SSH user is `root`.

## What changed
| Area | File | Change |
|---|---|---|
| DSLab | `modules/data_science_lab/store.py` | per-runtime `jupyter_token` (generated, never returned to UI), `public_view`, `set_internal` |
| DSLab | `modules/data_science_lab/session.py` | token-protected launch (token via env), auto-replace stale token-less lab, fixed backgrounding, `allow_root`, authenticated probe, `get_lab_token` |
| DSLab | `routers/dsl.py` | lab proxy injects `Authorization: token …` (HTTP + WebSocket); `POST/DELETE /runtimes/{rid}/agent-access`; secrets masked |
| DSLab | `modules/data_science_lab/jupyter_remote.py` (new) | Jupyter REST + kernel-websocket client |
| DSLab | `modules/data_science_lab/agent_access.py` (new) | registers per-runtime MCP server, creates "DSLab Code Runner" agent + workflow |
| MCP | `mcp_servers/dslab_runtime.py` (new) | stdio MCP server: run_python, run_shell, runtime_info, list/read/write files, run_notebook, add_cell, restart_kernel |
| MCP | `mcp_client.py` | SDK 1.x + 2.x support; DSLab pre-flight note |
| MCP | `seed.py`, `routers/mcp.py` | external jupyter-mcp link uses the stable proxy URL `http://backend:8099/api/v1/dsl/runtimes/<rid>/lab/` |
| Runtime | `runtime/live.py`, `runtime/adk.py` | tool calls run in a worker thread |
| Core | `main.py` | lab proxy exempt from the JSON request-size cap |
| Core | `tool_exec.py` | MCP tool names keep the tool part when labels are long |
| UI | `DataScienceLab.tsx`, `McpServers.tsx`, `api/client.ts` | "Enable agent access" button; "Link to DSLab runtime" for the external server |

## Verified
End-to-end against a real Jupyter Server (SSH hop simulated locally): stale token-less lab replaced; direct
token-less and `Host: backend` requests → 403 while proxy → 200/201; all 9 MCP tools; state persists;
timeout interrupts; closed lab auto-reopens; in-backend tool call (live-runtime path) completes; `tsc` clean.
