# Enterprise Agentic AI Platform — Complete Architecture & Build Plan

> A studio to **create**, **catalog**, **compose**, **execute**, and **observe** agentic workflows.
> Backend fully on **Google ADK (Agent Development Kit)**; persistence on **NoSQL**; full execution tracing in **MLflow**.
> **UI: a dark, data-dense "operational" interface inspired by Palantir's platform design** (built on Palantir's open-source **Blueprint.js**). See Section 20.

*(Working name: "Enterprise Agentic AI Platform" — rename as needed. Suggestions at the end.)*

**Status: this is the complete, self-contained, build-ready specification — the single source of truth. Nothing required to build the platform lives outside this document.** Sections 1–13 define the system; 14–16 cover flow, roadmap, and open decisions; 17–19 confirm advanced-ADK coverage, the full API contract, and adopted design learnings; 20–23 are the finalization layer (UI design language, how each learning surfaces in the UI, seed data, and a step-by-step construction guide with acceptance criteria); **Section 24 (Module 6)** adds the Platform Insights & Recommendation meta-workflow; **Section 25** specifies the live reasoning / "thinking out loud" activity stream; **Section 26** details the signature Agent Garden and Workflow Studio screens; and **Appendix A** gives the formal data contracts for every persisted entity.

---

## 1. Vision & Scope

The platform is a self-service **Agent Studio** where a non-ML user can assemble production-grade agentic workflows without writing orchestration code. It has six first-class surfaces:

| # | Module | Purpose |
|---|--------|---------|
| 1 | **Agent Creation Studio** | Wizard to author an agent (role, prompts, LLM, tools/APIs) |
| 2 | **Agent Garden** | Catalog of foundation + use-case agents; discovery & reuse |
| 3 | **Workflow Design Studio** | Visual, editable canvas; a *Workflow Designer Agent* auto-composes flows |
| 4 | **Agent Execution Engine** | Runs single agents or full workflows on the ADK runtime |
| 5 | **Agent Monitoring & Observability** | Live + historical traces, metrics, cost, quality (MLflow) |
| 6 | **Governance & Admin** | Versioning, access control, guardrails, cost policy, audit |
| 7 | **Platform Insights** *(Module 6, §24)* | Meta-workflow that observes platform usage and generates Word recommendation reports |

Everything the platform "does" at runtime resolves down to **ADK agents, tools, sessions, and the Runner event loop**. The UI is a thin authoring/visualization layer over ADK primitives persisted in NoSQL.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION LAYER (React)                     │
│  Creation Wizard │ Agent Garden │ Workflow Canvas │ Monitor Dashboards │
└───────────────┬──────────────────────────────────────────────────────┘
                │ REST / WebSocket (SSE for streaming tokens & trace events)
┌───────────────▼──────────────────────────────────────────────────────┐
│                    APPLICATION / CONTROL PLANE (FastAPI)               │
│  Agent Registry API │ Workflow API │ Execution API │ Tool Registry API │
│  Auth/RBAC │ Versioning │ Guardrail Config │ Cost & Quota │ Audit      │
└───────┬───────────────────────┬───────────────────────┬──────────────┘
        │                       │                       │
┌───────▼─────────┐   ┌─────────▼──────────┐   ┌────────▼─────────────┐
│  NoSQL Store     │   │  ADK RUNTIME PLANE │   │  Observability Plane │
│  (Firestore/     │   │  Runner+EventLoop  │   │  MLflow Tracking Srv │
│   MongoDB)       │   │  Agents/Tools      │   │  (OTLP /v1/traces)   │
│  agent_cards     │   │  Session/Memory/   │   │  Prompt Registry     │
│  workflows       │   │  Artifact services │   │  Eval + Metrics DB    │
│  tool_specs      │   │  Callbacks/Guards  │   │                      │
│  runs/versions   │   └─────────┬──────────┘   └──────────────────────┘
└──────────────────┘             │
                    ┌────────────▼─────────────┐
                    │  MODEL & TOOL GATEWAY     │
                    │  LLM router (Gemini +     │
                    │  LiteLLM: OpenAI/Claude/  │
                    │  Llama) │ OpenAPI toolsets │
                    │  MCP servers │ Functions   │
                    └───────────────────────────┘
```

**Key principle:** the *definition* of an agent/workflow lives in NoSQL as declarative JSON ("agent card" / "workflow graph"). At execution time, an **ADK Factory** hydrates those definitions into live ADK objects (`LlmAgent`, `SequentialAgent`, `ParallelAgent`, `LoopAgent`, tools). Nothing is hard-coded per agent — the studio writes data, the factory builds code objects.

---

## 3. ADK Concept Mapping (foundation everything rests on)

| Platform concept | ADK primitive |
|---|---|
| A single agent | `LlmAgent` (a.k.a. `Agent`) with `name`, `model`, `instruction`, `tools`, `output_key` |
| Sequential steps | `SequentialAgent` |
| Parallel fan-out | `ParallelAgent` |
| Loop / retry-until | `LoopAgent` (+ escalation to stop) |
| Custom control flow | subclass of `BaseAgent` |
| Agent used *inside* another agent | `AgentTool(agent=...)` |
| Delegation / hand-off (control moves) | `sub_agents` + AutoFlow (`transfer_to_agent`) |
| Collaboration behavior mode | **Chat** (manual return) / **Task** (auto-return after `finish_task`) / single-turn |
| Restrict hand-off direction | `disallow_transfer_to_parent`, `disallow_transfer_to_peers` |
| Return control upward | `tool_context.actions.escalate` |
| Python function tool | `FunctionTool(func=...)` |
| REST API tool | `OpenAPIToolset(spec=...)` → auto-generates one tool per endpoint |
| External tool servers | `MCPToolset` (Model Context Protocol) |
| Short-term working memory | `Session.state` (scratchpad, key-value) |
| Conversation history | `Session.events` |
| Long-term cross-session memory | `MemoryService` (Vertex Memory Bank / RAG / Mem0) |
| Binary/file outputs | `ArtifactService` |
| Run orchestration | `Runner` + Event Loop |
| Pre/post hooks (guardrails, memory writes, logging) | Callbacks: `before/after_agent`, `before/after_model`, `before/after_tool` |
| Cross-cutting runtime behavior (tracing, retries, logging) | **Plugins** on the `Runner` (e.g. `AutoTracingPlugin`, retry-and-reflect) |
| Native human approval on sensitive actions | Tool `RequireConfirmation` + **resumability** |
| Declarative agent definition (no-code) | **Agent Config (YAML)** + Visual Builder |
| Graph workflows (branches, joins, arbitrary DAGs) | **ADK 2.0 graph-based workflows** |
| Real-time voice/video/multimodal | **Bidi-streaming / Live API** (`run_live`, `LiveRequestQueue`, VAD) |
| Reusable capability bundles | **Skills system** |
| Runtime-provisioned tools | `BaseToolset` **dynamic provisioning** |
| Distributed / remote agents (cross-language) | **A2A protocol** (first-class) |

State scoping via key prefixes is central and used everywhere below:
- `` (no prefix) → this-session scratchpad
- `user:` → persists per user across sessions
- `app:` → shared platform-wide constants
- `temp:` → transient, never persisted

---

## 4. Module 1 — Agent Creation Studio

A guided wizard. Every field maps to an attribute in the persisted **Agent Card** (Section 9) and is consumed by the ADK Factory.

### 4.1 Create-Agent form (fields captured from UI)

**Identity & role**
- `agent_name` (unique, slug-safe)
- `display_name`, `description`, `icon/avatar`
- `role` (e.g., "Financial Analyst", "Data Extraction Specialist") — injected into system prompt
- `category` (`foundation` | `use_case`), `tags`, `domain`
- `owner`, `team`, `visibility` (`private` | `team` | `org`)

**Prompts**
- `system_prompt` (ADK `instruction`) — the role/behavior/constraints. Template-enabled with `{state_key}` and `{user:pref}` injection.
- `user_prompt_template` — default/first user message or the input contract (what the agent expects as input). Placeholders bound at runtime from workflow context.
- `output_key` — the `Session.state` key where this agent writes its result (enables the next agent to read it → **this is how context is passed down a workflow**).
- `output_schema` (optional Pydantic/JSON schema) for structured outputs.

**Model configuration**
- `llm_provider` + `model` (e.g., `gemini-3-pro`, `gemini-3-flash` [current default family]; legacy `gemini-2.5-*` supported until its 2026-10-16 shutdown; or via LiteLLM: `claude-*`, `gpt-*`, self-hosted Llama)
- `temperature`, `top_p`, `max_output_tokens`, `safety_settings`
- `fallback_model` (used if primary is rate-limited/unavailable)
- `thinking/reasoning` toggle where supported

**Tools / API / Function mapping** *(your explicit requirement — detailed in Section 11)*
- Add one or more of: **Function tools**, **REST APIs (OpenAPI)**, **MCP tool servers**, **built-in tools** (web search, code exec, RAG retrieval), or **other agents as tools**.
- Per tool: auth binding, allowed operations, rate limits, and a per-tool description the LLM uses to decide when to call it.

**Collaboration & multi-agent** *(explicit creation-time configuration — this is where you "select a collaboration agent")*
- `collaboration_role` — how this agent participates: `standalone` | `coordinator` (delegates to others) | `specialist` (can be delegated to / called) | `peer` (A2A remote).
- **Select collaborator agents** from the Garden and, for each, choose the *collaboration type*:
  - **Delegate (sub-agent / transfer):** control hands off to the collaborator via AutoFlow. Adds it to `sub_agents`.
  - **Call as tool (agent-as-tool):** this agent invokes the collaborator, gets a result, and keeps control. Wraps it as `AgentTool`.
  - **Remote peer (A2A):** collaborator is a remote agent reached over the A2A protocol (endpoint + auth).
- Per delegated collaborator: **collaboration mode** — `chat` (manual return to parent) | `task` (auto-return after `finish_task`, isolated session branch) | `single_turn`.
- **Transfer controls:** `allow_transfer_to_parent` (on/off), `allow_transfer_to_peers` (on/off), and an **escalation policy** (when a specialist should hand control back up).
- **Delegation guidance:** collaborator descriptions drive AutoFlow routing, so the wizard requires a clear `description` on any agent used as a collaborator, plus an optional coordinator `routing_instruction`.
- **Shared-state contract:** declare which `state` keys are shared/handed between collaborators (prevents context loss on hand-off).

**Memory & context**
- `memory_enabled` (bool) + memory scope (`user` / `workflow` / `global`)
- `session_state_reads` / `session_state_writes` — declared keys (explicit context contract)
- `context_strategy` (see Section 10): full-history | summarized | rag-injected | last-N-turns

**Guardrails & controls**
- Input/output content filters, PII redaction toggle
- `human_in_the_loop` (require approval before "significant actions" — implemented via `before_tool` callback that pauses/escalates)
- Max steps / max tool calls / timeout / max cost per run

**Lifecycle**
- `version`, `status` (`draft` | `published` | `deprecated`), `changelog`

### 4.2 Creation flow
1. User fills wizard → **Test panel** runs the agent in an ephemeral session (InMemory services) with sample input and shows a live trace.
2. On **Publish**: validate → write **Agent Card** to NoSQL → register default prompt version in **MLflow Prompt Registry** → agent appears in Agent Garden.
3. Every publish creates an immutable version; edits fork a new version.

---

## 5. Module 2 — Agent Garden

The catalog/marketplace of reusable agents.

- **Foundation agents** (shipped): Web Researcher, Summarizer, Data Extractor, SQL/Analytics Agent, Document (RAG) Q&A, Code Generator, Email/Comms Drafter, Classifier/Router, Critic/Reviewer, Human-Approval agent, and the **Workflow Designer Agent** itself.
- **Use-case agents** (org-authored): domain-specific, built via Module 1.
- **Discovery UI:** searchable/filterable grid (by category, tag, domain, owner, model, tools used), each rendered as an **Agent Card** with role, capabilities, tools it can access, model, version, usage stats, and rating.
- **Machine-readable capability index:** every card stores an embedding of `{role + description + tool capabilities}`. This index is what the Workflow Designer Agent queries (semantic search) to decide reuse-vs-create.
- **Actions:** view/clone/version/deprecate, "Add to workflow", usage analytics, and a capability manifest export.
- **Bundles / Role Packs** *(inspired by Cowork "plugins")*: package a set of agents + tools + skills + prompts into one installable specialist pack (e.g., a **Legal** or **Finance** pack) so a team gets a ready-made role from day one. Foundation **vertical bundles** ship pre-built; orgs author their own. A bundle is just a manifest of Agent Configs + tool specs + skills, versioned like any other artifact.

---

## 6. Module 3 — Workflow Design Studio (the core differentiator)

### 6.1 User flow
1. User types a **goal** in natural language ("Analyze last quarter's sales CSV, find anomalies, draft an exec summary email").
2. The **Workflow Designer Agent** is triggered.
3. It returns a **workflow graph**; the canvas renders it as connected nodes.
4. User **edits** the graph (add/remove/reorder nodes, change agents, edit prompts, rewire data flow, set parallel/sequential/loop, insert approval gates).
5. User **saves** and/or **executes**.

### 6.2 The Workflow Designer Agent (design-time meta-agent)

An ADK agent (itself in the Garden) whose job is *planning*, not doing. Pipeline:

1. **Decompose** the goal into ordered/parallel capability requirements (sub-tasks).
2. **Match against the Garden** — for each sub-task, semantic-search the capability index. Score candidates by capability fit, tool coverage, and past success rate.
3. **Reuse-first policy (hard rule):** if a candidate scores above the reuse threshold, bind the existing agent. **Only genuinely missing capabilities are marked `to_be_created`.**
4. **Draft specs for missing agents** — the designer emits a *provisional Agent Card* (role, suggested prompts, suggested tools) for each gap, which the user can accept/edit → these are created dynamically and (optionally) saved back to the Garden for future reuse.
5. **Wire data flow** — set each node's `output_key` and downstream `input bindings` (which upstream `state` keys feed the next agent). Choose topology: `SequentialAgent` / `ParallelAgent` / `LoopAgent` / conditional router.
6. **Emit the Workflow Graph JSON** (Section 9.2).

Node status in the canvas:
- 🟢 **Reused** (bound to an existing Garden agent)
- 🟡 **To be created** (provisional card, pending user confirmation)
- 🔵 **Modified** (reused agent with per-workflow prompt/param overrides)

### 6.3 Canvas capabilities
- Drag/drop nodes; connect edges (data + control flow shown separately).
- Node inspector: edit prompts, model, tools, retries, timeout, approval gate.
- Topology controls: mark a group parallel, wrap a section in a loop with exit condition, add branch/router conditions.
- Live validation: unbound inputs, type mismatches on `state` keys, cycles, missing tool auth.
- **Visualize mode:** read-only animated view of the DAG with data-flow overlay; during execution the same graph animates node-by-node with live status.
- Versioned save; diff between workflow versions.

### 6.4 Compilation to ADK
On save/execute, the **Workflow Compiler** translates the graph → a composed ADK agent tree:
- Linear chain → `SequentialAgent(sub_agents=[...])`
- Fan-out group → `ParallelAgent(sub_agents=[...])`
- Iterative block → `LoopAgent(sub_agent=..., max_iterations=N)` with an escalation/stop condition
- Conditional routing → a router `LlmAgent` (or custom `BaseAgent`) that transfers control
- Agents-as-steps that need to be callable mid-reasoning → wrapped as `AgentTool`
- **Arbitrary DAGs (branches + joins) → ADK 2.0 graph-based workflows.** The canvas is a graph, so the compiler's primary target is ADK's native graph workflow rather than only nesting the three classic workflow agents; Sequential/Parallel/Loop are used for the simple sub-cases. Each node compiles from its Agent Card, which itself serializes to native **ADK Agent Config (YAML)** — so the studio emits standard ADK, not a proprietary format.

### 6.5 Collaboration in the canvas (how it's showcased)

The canvas must make multi-agent collaboration legible, because delegation and agent-as-tool behave very differently at runtime:

- **Edge types are visually distinct:**
  - **Data-flow edge** (default) — one node's `output_key` feeds another's input.
  - **Delegation edge** (dashed, arrow both ways) — a *hand-off*; control transfers to the collaborator and returns. Labeled with the **collaboration mode** badge (`chat` / `task` / `single_turn`).
  - **Call edge** (dotted, "⚙ tool") — agent-as-tool; the caller keeps control and receives a result.
  - **A2A edge** (globe icon) — remote peer over A2A.
- **Coordinator grouping:** a coordinator node renders as an expandable container showing its `sub_agents` nested inside, so hierarchy is obvious at a glance.
- **Transfer-direction indicators:** small up/down/side arrows show whether `transfer_to_parent`/`_to_peers` are allowed; blocked directions are greyed.
- **Collaboration inspector:** selecting a node exposes the same collaboration config from the creation wizard (collaborators, type, mode, transfer flags, shared-state keys) so it can be tuned per-workflow without leaving the canvas.
- **Live execution overlay:** during a run, an active hand-off animates along the delegation edge; the currently-in-control agent is highlighted, and returned control is shown flowing back — so the user literally watches collaboration happen.
- **Validation:** the canvas flags collaboration hazards (cyclic delegation with no escalation, a delegate with no `description` for AutoFlow, shared-state key referenced by a collaborator but never written).

### 6.6 Workflow-level configuration (complete catalog)

Every workflow exposes these settings so no ADK capability is left unconfigurable from the UI:

**Topology & control** — sequential / parallel / loop / graph (branches, conditional edges, joins); per-loop `max_iterations` + exit condition; conditional routing rules; sub-workflows (a saved workflow embedded as a node).

**Reliability & verification** *(agent loop = gather → act → verify → repeat)* — optional **self-verification step**: a critic/reviewer agent (or `LoopAgent` with an eval gate) checks the output against the goal before returning; cross-verification for high-stakes nodes; auto-revise-until-pass with a max-retry ceiling.

**Model routing** *(cost/difficulty tiering)* — route easy/common sub-tasks to a cheaper model (e.g., Gemini 3 Flash) and hard/unusual ones to a stronger model (Gemini 3 Pro) via a router node; **cache-aware** config keeps system prompt + tool set static across calls to preserve prompt caching.

**Collaboration defaults** — default collaboration mode for the workflow, global transfer policy, and coordinator selection (which node is root).

**Inputs & context** — workflow input schema (files, text, params); initial `state` seeding; shared-state contract across nodes; context strategy (full / summarized / last-N / RAG) and **context-window compression** for long runs.

**Models & cost** — default model + per-node overrides; `max_llm_calls`, max steps, per-node and per-run cost/token budgets; timeouts and per-node retry/backoff (via retry-and-reflect plugin).

**Memory** — workflow memory scope (`user` / `workflow` / `global`), service (Memory Bank / RAG / Mem0), and read/write-on-complete policy.

**Streaming & modality** — response modality (text / audio / video), `StreamingMode` (SSE for request-response, **BIDI** for realtime/voice workflows), VAD/interruption for Live-API nodes.

**Live narration** *(the "thinking out loud" stream, §25)* — narration on/off; narrator tier (templated / LLM-flavored); phrase style (concise-ops / conversational); show-reasoning (off / generic / summarized thoughts); throttle level; LLM-narrator cost cap.

**Human-in-the-loop** — which nodes/tools are `RequireConfirmation`; approval routing; resumability on/off; timeout-to-auto-reject.

**Tools & provisioning** — per-node tool sets, dynamic tool provisioning rules (per-tenant/permission), tool-output truncation/summarization.

**Guardrails & governance** — input/output filters, PII redaction, content-safety level, allowed-domain egress per tool, and audit tagging.

**Plugins** — toggle `AutoTracingPlugin` (→ MLflow), retry-and-reflect, custom logging/guardrail plugins for this workflow.

**Observability** — MLflow experiment binding, business tags, trace content-capture opt-in, eval dataset attachment, alert thresholds.

**Lifecycle** — version, pin-to-agent-versions (reproducibility), schedule/trigger (manual, API, cron, event), and environment (dev/stage/prod) + deploy target.

**Backend note:** all of the above are persisted on the workflow document (Section 9.2) and consumed by the Workflow Compiler + Runner builder. The compiler assembles `sub_agents`/`AgentTool`/A2A wiring and transfer flags from each node's `collaboration` block; the Runner builder attaches the selected Plugins, RunConfig (budgets/modality/streaming), and Session/Memory/Artifact services. Nothing here requires client-side ADK code.

---

## 7. Module 4 — Agent Execution Engine

- **Runner-per-run:** a `Runner` is instantiated with the compiled root agent and the configured `SessionService`, `MemoryService`, `ArtifactService`.
- **Session lifecycle:** on "Execute", create a session (`app_name`, `user_id`, `session_id=run_id`); the user's dynamic input becomes the initial `Content`.
- **Streaming:** events from the ADK event loop stream to the UI over SSE/WebSocket — token deltas, tool calls, tool results, sub-agent transitions, state mutations.
- **Persistence in prod:** `VertexAiSessionService` (managed) or `DatabaseSessionService` (Postgres) so runs survive restarts; **never** `InMemory` in production.
- **Human-in-the-loop (native):** sensitive tools are flagged `RequireConfirmation`; ADK pauses the run, emits a confirmation event, surfaces an approval card in the UI, and — with **resumability** enabled — durably resumes on the human decision (survives restarts, supports long approvals via queue).
- **Resilience:** per-node retry with backoff, `fallback_model`, timeouts, and partial-failure handling (continue / halt / compensate).
- **Outputs:** final response + all intermediate `state`/artifacts captured; artifacts (files, charts) downloadable from the run page.
- **Controls:** pause / resume / cancel; cost & step budgets enforced mid-run.
- **Plan Mode** *(transparency-first, à la Cowork)*: for autonomous runs, the agent first produces a visible **plan** on the canvas and waits for approval; the user can edit or steer it before execution begins.
- **Mid-run steering:** the user can inject guidance into a live run ("focus on Q3 only") without cancelling — delivered into the running session (via a new message / `LiveRequestQueue` for realtime agents). Steer from any surface; a run started on one device can be monitored/redirected from another.
- **Scheduled & unattended runs:** trigger a workflow manually, via API, on a **cron schedule** (daily briefing, weekly report), or on an **event** (file dropped, webhook). Resumable sessions let long-horizon runs continue across restarts and hand-offs.
- **Workspace + file-system-as-context:** each run gets a scoped workspace (ArtifactService-backed). Agents keep large data as files and pass **lightweight references** (paths, stored queries) through `state`, loading data **just-in-time** via list/read/search tools rather than dumping blobs into the context window.
- **Edit-in-place review:** on the deliverable, the user highlights a span and requests a change; a scoped agent re-runs on just that section instead of regenerating the whole output.

---

## 8. Module 5 — Monitoring & Observability (MLflow)

MLflow is the system of record for **execution tracing, metrics, cost, and quality**.

### 8.1 How ADK traces reach MLflow (verified mechanism)
- **Simplest path (recommended): the `AutoTracingPlugin`** — attach it to the `Runner` for one-line OpenTelemetry auto-instrumentation instead of manually wiring exporters per agent.
- Under the hood, ADK emits **OpenTelemetry `gen_ai.*` spans** for agent runs, tool calls, and model requests.
- MLflow **3.6.0+** exposes an **OTLP ingestion endpoint at `/v1/traces`**. Configure an `OTLPSpanExporter` + global tracer provider **before** initializing any ADK object, pointing at the MLflow server; set header `x-mlflow-experiment-id`.
- Requirement: MLflow must run on a **SQL backend** (SQLite for dev; Postgres/MySQL for prod). **File-based backends do not support OTLP ingestion.**
- Because it's OTel-native, you can **dual-export** the same traces to Datadog/Grafana Tempo/Jaeger/Cloud Trace with zero extra instrumentation.
- **Privacy note:** by default OTel captures metadata (model, token counts, latency, finish reason) but **not prompt/response content**. Content capture is an explicit opt-in per governance policy (Section 12).

### 8.2 What we capture per run
- **Trace tree:** every LLM call, tool invocation, retrieval, and sub-agent transition with inputs/outputs (subject to redaction policy).
- **Metrics:** latency (per span & end-to-end), token usage, **cost** (tokens × model price), tool error rates, retry counts, step counts.
- **Business tags:** `workflow_id`, `workflow_version`, `run_id`, `user_id`, `team`, `agent_versions[]`.
- **Quality:** attach `mlflow.genai` evaluations (correctness, groundedness, relevance) and human feedback (👍/👎 + comments) onto the trace.

### 8.3 Dashboards (in-app, backed by MLflow API)
- **Live run view:** animated DAG + streaming span tree.
- **Historical:** run list, filter/search traces, compare two runs side-by-side.
- **Ops dashboards:** success rate, p50/p95 latency, cost per workflow/team/day, top failing tools, model usage mix.
- **Alerting:** thresholds on error rate, latency, cost, and quality-score drift → notify (email/Slack/webhook).

### 8.4 MLflow beyond tracing
- **Prompt Registry:** every system/user prompt version registered; traces link back to the exact prompt version that produced them (root-cause quality regressions).
- **Evaluation harness:** golden datasets per agent/workflow; run `mlflow.genai.evaluate` in CI before publishing a new version.
- **Experiment tracking:** compare model/prompt variants (A/B) on the same eval set.

---

## 9. Data Model (NoSQL — Firestore or MongoDB)

Document store chosen for schema flexibility (agent configs evolve) and fast reads of nested cards.

### 9.1 Collection: `agent_cards`
```json
{
  "agent_id": "uuid",
  "agent_name": "financial_analyst",
  "version": 3,
  "status": "published",
  "category": "use_case",
  "role": "Senior Financial Analyst",
  "description": "...",
  "tags": ["finance", "analysis"],
  "owner": {"user_id": "...", "team": "..."},
  "visibility": "org",

  "model_config": {
    "provider": "google",
    "model": "gemini-3-pro",
    "fallback_model": "gemini-3-flash",
    "temperature": 0.2,
    "max_output_tokens": 4096,
    "safety_settings": {}
  },

  "prompts": {
    "system_prompt": "You are a {role}. ...{state:context}...",
    "user_prompt_template": "Analyze: {input_data}",
    "prompt_registry_ref": "mlflow://prompts/financial_analyst/3"
  },

  "io_contract": {
    "output_key": "analysis_result",
    "output_schema": {"type": "object", "properties": {}},
    "state_reads": ["raw_data", "user:preferences"],
    "state_writes": ["analysis_result"]
  },

  "tools": [
    {"type": "function", "ref": "tool_specs/calc_npv"},
    {"type": "openapi", "ref": "tool_specs/erp_api", "operations": ["getInvoices"]},
    {"type": "mcp", "ref": "tool_specs/warehouse_mcp"},
    {"type": "agent", "ref": "agent_cards/summarizer@2"},
    {"type": "builtin", "name": "code_execution"}
  ],

  "collaboration": {
    "role": "coordinator",
    "collaborators": [
      {"agent_ref": "agent_cards/research_agent@2", "type": "delegate", "mode": "task"},
      {"agent_ref": "agent_cards/summarizer@2",     "type": "agent_tool"},
      {"agent_ref": "a2a://partner-org/pricing_agent", "type": "a2a_peer", "auth_ref": "vault/a2a_partner"}
    ],
    "transfer": {
      "allow_transfer_to_parent": true,
      "allow_transfer_to_peers": false,
      "escalation_policy": "on_failure"
    },
    "routing_instruction": "Route pricing questions to the peer agent; research to the sub-agent.",
    "shared_state_keys": ["research_findings", "user:preferences"]
  },

  "memory_config": {
    "enabled": true,
    "scope": "user",
    "service": "vertex_memory_bank",
    "read": true, "write_on_complete": true
  },

  "context_config": {
    "strategy": "summarized",
    "max_history_turns": 10,
    "rag_source": "tool_specs/policy_kb"
  },

  "guardrails": {
    "pii_redaction": true,
    "human_in_the_loop": {"enabled": true, "triggers": ["send_email","spend>100"]},
    "limits": {"max_steps": 25, "max_tool_calls": 15, "timeout_s": 120, "max_cost_usd": 2.0}
  },

  "embedding": [0.01, ...],        // capability vector for reuse matching
  "created_at": "...", "updated_at": "...", "changelog": "..."
}
```

### 9.2 Collection: `workflows`
```json
{
  "workflow_id": "uuid",
  "name": "Quarterly Sales Analysis",
  "version": 2,
  "goal_prompt": "Analyze last quarter's sales CSV ...",
  "designed_by": "workflow_designer_agent@1",
  "topology": "graph",
  "nodes": [
    {
      "node_id": "n1",
      "agent_ref": "agent_cards/data_extractor@4",
      "status": "reused",
      "overrides": {"temperature": 0.0},
      "input_bindings": {"input_data": "workflow.input.file"},
      "output_key": "raw_data"
    },
    {
      "node_id": "n2",
      "agent_ref": "agent_cards/financial_analyst@3",
      "status": "modified",
      "input_bindings": {"raw_data": "n1.raw_data"},
      "output_key": "analysis_result"
    },
    {
      "node_id": "n3",
      "provisional_card": { "...draft for a to-be-created agent..." },
      "status": "to_be_created",
      "input_bindings": {"analysis_result": "n2.analysis_result"},
      "output_key": "email_draft"
    }
  ],
  "edges": [
    {"from": "n1", "to": "n2", "type": "sequential"},
    {"from": "n2", "to": "n3", "type": "sequential"}
  ],
  "control_flow": {"type": "sequential", "groups": []},
  "approval_gates": ["n3"],
  "created_at": "...", "updated_at": "..."
}
```

### 9.3 Other collections
- `tool_specs` — function signatures, OpenAPI specs, MCP endpoints, auth-binding references (secrets stored in a vault, only references here).
- `runs` — run metadata + pointer to MLflow trace ID (large trace data lives in MLflow, not NoSQL).
- `versions` / `audit_log` — immutable history for agents & workflows.
- `users`, `teams`, `roles` — RBAC.

---

## 10. Context-Passing Architecture

Context flows through three coordinated layers:

**1. Intra-workflow (agent → agent):** the canonical mechanism is **`Session.state` + `output_key`**. Each agent writes to its declared `output_key`; downstream agents read via `input_bindings` (mapped into their prompt with `{state_key}` templating). The Workflow Compiler validates that every `input_binding` has a producing upstream node — this is a typed **context contract**, preventing "unbound input" runtime failures.

**2. Within an agent's reasoning:** ADK assembles context automatically — it **filters irrelevant events, summarizes older turns, lazy-loads artifacts, and tracks token budget** so the window doesn't overflow. Per-agent `context_config` lets authors override: full history, last-N-turns, summarized, or RAG-injected.

**3. Large / binary payloads:** don't stuff big blobs into `state`. Use the **`ArtifactService`** (files, images, CSVs, charts) and pass an artifact **reference** through state. Keeps token cost down and enables lazy loading.

**State scoping** governs visibility: `temp:` for scratch that must not persist, session-scope for a single run, `user:` for cross-run personalization, `app:` for global config.

---

## 11. Tool / Function / API Mapping Subsystem (your explicit requirement)

When creating an agent, the user maps capabilities so "the agent has access to those functions." Four binding types, all resolved by the ADK Factory into ADK tools:

| UI option | Author provides | ADK realization |
|---|---|---|
| **Map a Function** | Select from function catalog (or paste signature + docstring) | `FunctionTool(func=...)` — docstring/args become the LLM-visible schema |
| **Map an API** | Upload/paste an **OpenAPI/Swagger spec** + choose endpoints + auth | `OpenAPIToolset(spec=...)` → auto-generates one callable tool per operation |
| **Map a Tool Server** | MCP server URL + credentials | `MCPToolset(...)` exposes that server's tools |
| **Map an Agent** | Pick a Garden agent | `AgentTool(agent=...)` — call another agent as a tool |
| **Built-in** | Toggle | Web search, code execution, vertex RAG retrieval, etc. |

**Tool Registry (`tool_specs` collection):** central, reusable, versioned catalog so a function/API is defined once and mapped to many agents.

**Per-tool config captured in UI:**
- LLM-facing `description` (drives when the model calls it) and parameter docs.
- **Auth binding:** API key / OAuth / service account — secret stored in **Secret Manager/Vault**, only a reference persisted.
- **Guardrails:** allowed operations (e.g., read-only endpoints only), rate limits, HITL requirement for mutating calls, argument validation via `before_tool` callback.
- **Response shaping:** truncation/summarization of large tool outputs before they re-enter context.

**Security:** tool execution runs in a sandboxed worker; egress allow-lists per tool; every tool call is traced (name, args-redacted, latency, result-size, error) into MLflow.

---

## 12. Cross-Cutting Configuration & Governance

**Memory management (summary of Section 3/10 as a config surface)**
- Per-agent memory on/off, scope (`user`/`workflow`/`global`), and service choice: `VertexAIMemoryBankService` (Gemini-extracted key facts, recommended for prod), `VertexAiRagMemoryService` (semantic recall over past sessions), or Mem0. Memory **writes** happen via an `after_agent`/on-complete callback that ingests the session; **reads** via a `load_memory` tool or auto-injection.

**Guardrails & safety** — input/output filters, PII redaction, jailbreak/prompt-injection screening on tool outputs and RAG chunks, content-safety settings per model, HITL gates on "significant actions."

**Versioning & lifecycle** — immutable versions for agents, prompts (MLflow registry), workflows; draft→published→deprecated; rollback; diff view; pin workflows to specific agent versions for reproducibility.

**Multi-tenancy & RBAC** — org/team/user isolation; roles (Viewer, Builder, Publisher, Admin); visibility scopes on agents/workflows; per-team quotas.

**Cost & quota governance** — per-run and per-team budgets; model price table; block/alert on overspend; cost attribution in dashboards.

**Evaluation & CI** — golden datasets, automated `mlflow.genai.evaluate` gate before publish, regression detection against previous version.

**Secrets & compliance** — Vault/Secret Manager for all credentials; audit log of every create/edit/execute/approve; data-retention policy for traces (esp. if content capture is enabled); region pinning for data residency.

**Observability of the platform itself** — infra metrics (Cloud Trace/Prometheus) alongside agent traces (MLflow), unified via OTel.

---

## 13. Recommended Technology Stack

| Layer | Choice |
|---|---|
| Agent runtime | **Google ADK** (Python) |
| Models | **Gemini 3 (Pro/Flash)** native (current default family; 2.5 supported until 2026-10-16 shutdown); **LiteLLM** wrapper for Claude/OpenAI/self-hosted Llama to satisfy "LLM as selected" |
| Control-plane API | FastAPI (async), Pydantic schemas |
| NoSQL | Firestore (GCP-native) **or** MongoDB Atlas |
| Session/Memory (prod) | `VertexAiSessionService` + `VertexAIMemoryBankService` (or `DatabaseSessionService` on Postgres) |
| Artifacts | GCS-backed `ArtifactService` |
| Observability | **MLflow ≥ 3.6** (SQL backend: Postgres) via OTLP; optional dual-export to Cloud Trace/Grafana |
| Frontend | **React 18 + TypeScript**, **Palantir Blueprint.js** (`@blueprintjs/core`, `/table`, `/select`, `/datetime`) in **dark theme** for the Palantir-style operational UI; **React Flow** for the workflow canvas; SSE/WebSocket for streaming; Zustand/Redux for state |
| Secrets | Google Secret Manager / HashiCorp Vault |
| Deployment | Cloud Run or GKE (ADK "deploy anywhere"); or **Vertex Agent Engine / Agent Runtime** for managed sessions & scaling |
| Async/queue | Pub/Sub or Redis for long-running & HITL-paused runs |

---

## 14. End-to-End Flow (worked example)

1. **Create** a "Data Extractor" and "Financial Analyst" agent via the wizard; map the Analyst to the ERP OpenAPI + an `calc_npv` function. Cards saved to NoSQL, prompts to MLflow registry.
2. User opens **Workflow Studio**, types the goal.
3. **Workflow Designer Agent** decomposes → finds Data Extractor + Financial Analyst in the Garden (**reuse**), detects no "email drafter" match → marks one **to-be-created** with a provisional card.
4. Canvas renders 3 nodes (🟢🟢🟡). User accepts the drafted email agent (optionally saving it to the Garden) and adds an **approval gate** before send.
5. **Compile** → `SequentialAgent([extractor, analyst, email_drafter])`, data wired via `output_key`/`input_bindings`.
6. **Execute** → Runner streams the animated DAG; ADK emits OTel spans → **MLflow** trace tree, tokens, cost.
7. Approval gate pauses at the email node; user approves; run completes; artifacts + trace saved; feedback attached for future evaluation.

---

## 15. Phased Roadmap

- **Phase 0 — Foundations:** ADK runtime + Factory (card→agent), NoSQL schema, LLM gateway, MLflow tracing wired end-to-end.
- **Phase 1 — Creation + Garden:** wizard, tool registry (function + OpenAPI mapping), test panel, catalog with reuse index.
- **Phase 2 — Execution + Monitoring:** Runner service, streaming UI, MLflow dashboards, cost tracking, HITL.
- **Phase 3 — Workflow Studio:** Designer Agent, canvas, compiler, reuse-first composition, versioning.
- **Phase 4 — Enterprise hardening:** RBAC/multi-tenancy, guardrails, eval/CI gates, alerting, A2A for distributed agents, marketplace/sharing.

---

## 16. Open Decisions to Confirm

1. **Cloud posture:** all-in on Vertex (Agent Engine + Memory Bank + Firestore) vs. portable (self-hosted ADK on GKE + Mongo + open-source memory)?
2. **NoSQL choice:** Firestore vs. MongoDB.
3. **Multi-model priority:** Gemini-only first, or LiteLLM multi-provider from day one?
4. **Trace content capture:** metadata-only (default, privacy-safe) vs. full prompt/response capture (needs retention + redaction policy)?
5. **Auto-save dynamically-created agents** back to the Garden by default, or require explicit promotion?
6. **HITL transport:** synchronous hold vs. durable pause via queue (matters for long approvals).

---

## 17. Latest-ADK Feature Adoption (current release)

Explicit confirmation of which advanced ADK capabilities the platform uses, and the backend/frontend implication of each.

| Advanced ADK feature | Adopted? | Backend implication | Frontend implication |
|---|---|---|---|
| **Multi-agent collaboration** (delegation/`sub_agents`, agent-as-tool, **Chat/Task modes**, transfer flags) | ✅ Creation-time config | Factory wires `sub_agents`/`AgentTool`/A2A + transfer flags from each Card's `collaboration` block | Wizard "Collaboration" step; canvas shows delegation vs call edges, coordinator grouping, mode badges, live hand-off animation |
| **ADK 2.0 graph-based workflows** | ✅ Primary compile target | Workflow Compiler emits native graph workflows (branches/joins/DAGs), not just nested Sequential/Parallel/Loop | Canvas supports true branching, conditional edges, and join nodes — not linear-only |
| **Agent Config (YAML) + Visual Builder** | ✅ Agent Card ⇄ YAML | Factory reads/writes native ADK Agent Config; Card is a persistence+UX wrapper over it (no lock-in) | Wizard is effectively a Visual Builder; "View as YAML" / import-export of native config |
| **Runner Plugins** (`AutoTracingPlugin`, retry-and-reflect, logging) | ✅ | Plugins attached at Runner build; replaces hand-rolled OTel + adds retry/reflect and centralized logging | Toggle plugins per workflow (auto-trace, auto-retry) in run settings |
| **Native HITL** (`RequireConfirmation`) + **resumability** | ✅ | Mark tools/nodes as confirm-required; durable pause/resume across restarts | Approval inbox; per-tool "require approval" switch; resume/reject actions |
| **Bidi-streaming / Live API** (`run_live`, `LiveRequestQueue`, VAD, interruption) | ✅ New agent type | A dedicated WebSocket path using `run_live()`; audio/video in, text/audio out | "Realtime/Voice agent" template; mic/video capture; barge-in/interrupt UI |
| **A2A protocol** (cross-language remote agents) | ✅ First-class | Register remote A2A agents as nodes; runtime handles event ordering/aggregation | "Remote agent" node type; endpoint + auth config in inspector |
| **Skills system** | ✅ | Package reusable capability bundles; attach to agents | "Skills" tab in wizard; skill catalog alongside tools |
| **Dynamic tool provisioning** (`BaseToolset`) | ✅ | Tools resolved at runtime (e.g., per-tenant, per-permission) | Author sets provisioning rule; UI shows "dynamic" tool badge |
| **Context-window compression** | ✅ | Enabled for long/live sessions via RunConfig | Per-agent context strategy already exposed (Section 10) |
| **RunConfig cost controls** (`max_llm_calls`, modalities) | ✅ | Budget/step caps enforced by runtime, not just app logic | Run-settings sliders for max calls, modality, streaming mode |
| **Gemini 3 model family** | ✅ Default | Default model family updated; LiteLLM for non-Google | Model picker lists Gemini 3 + external providers |
| **Deploy targets** (Cloud Run / GKE / **Vertex Agent Engine**) | ✅ | Agent Engine gives managed sessions, scaling, built-in auth & Cloud Trace | Deployment target chosen per environment in Admin |
| **`adk web` Dev UI** (embedded tracer) | ✅ (dev only) | Used by builders for local debug; prod uses the platform's own UI | Optional "Open in ADK Dev UI" for power users |

**Net new modules/changes driven by the above**
- **Realtime Agent Runtime** (backend): a separate WebSocket service using `run_live()` + `LiveRequestQueue` for voice/multimodal agents, distinct from the request/response Runner path.
- **Agent Config service** (backend): bidirectional Card⇄YAML serialization so everything the studio produces is portable, native ADK.
- **Plugin manager** (backend): registers `AutoTracingPlugin` (→ MLflow), retry-and-reflect, and custom guardrail plugins on every Runner.
- **Graph compiler** (backend): targets ADK 2.0 graph workflows with conditional edges and joins.
- **Approval Inbox** (frontend): central queue for `RequireConfirmation` events with resume/reject.
- **Realtime/Voice canvas node + capture UI** (frontend): mic/video, live transcript, barge-in.
- **Remote (A2A) node + Skills tab** (frontend).

---

## 18. Complete API Surface (FastAPI + WebSocket)

Confirms the platform is a **thin frontend over a complete backend**: the React UI calls **only** these endpoints; FastAPI owns the entire ADK runtime. No ADK object is ever constructed client-side.

**Conventions:** REST base `/api/v1`, JSON bodies, JWT auth, RBAC-scoped, all list endpoints paginated/filterable. Long-running/streaming operations use WebSocket/SSE.

### 18.1 Auth & tenancy
- `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`
- `GET /me`, `GET /teams`, `GET /teams/{id}/members`
- `GET/POST/PATCH /admin/roles`, `GET/POST /admin/quotas`

### 18.2 Agents (Creation Studio + Garden)
- `POST /agents` — create Agent Card (draft) from wizard payload
- `GET /agents` — list/search Garden (filters: category, tag, domain, model, tool, owner) + semantic search `?q=`
- `GET /agents/{id}` · `GET /agents/{id}/versions` · `GET /agents/{id}/versions/{v}`
- `PATCH /agents/{id}` — edit (forks new version)
- `POST /agents/{id}/publish` · `POST /agents/{id}/deprecate` · `POST /agents/{id}/clone`
- `GET /agents/{id}/config.yaml` — export native ADK Agent Config; `POST /agents/import` — import YAML
- `POST /agents/{id}/test` — ephemeral run in sandbox (returns trace); `WS /agents/{id}/test/stream` — live test stream
- `GET /agents/{id}/collaborators` — list attached collaborators (delegate / agent-tool / A2A peer)
- `POST /agents/{id}/collaborators` — attach a collaborator `{agent_ref, type, mode, transfer_flags}`
- `DELETE /agents/{id}/collaborators/{collabId}` — detach
- `POST /agents/{id}/collaboration/validate` — check for cyclic delegation, missing descriptions, unshared state keys
- `GET/POST /bundles` — list/create Bundles (Role Packs); `POST /bundles/{id}/install` — install a pack (agents+tools+skills+prompts) into a team; `GET /bundles/{id}` · `GET /bundles/marketplace`

### 18.3 Tools / APIs / Functions (Tool Registry)
- `GET/POST /tools` — list/register tool specs
- `POST /tools/openapi` — upload OpenAPI spec → auto-generate tool set (preview endpoints before save)
- `POST /tools/function` — register a function tool (signature + docstring)
- `POST /tools/mcp` — register an MCP server; `GET /tools/mcp/{id}/inspect` — list its tools
- `POST /tools/{id}/auth-binding` — bind credentials (stored in Vault; only ref persisted)
- `GET /tools/{id}` · `PATCH /tools/{id}` · `GET/POST /skills`

### 18.4 Workflows (Design Studio)
- `POST /workflows/design` — send NL goal → triggers **Workflow Designer Agent** → returns graph (reused vs to-be-created nodes)
- `WS /workflows/design/stream` — stream the designer's reasoning/plan as it builds
- `POST /workflows` — save graph; `GET /workflows` · `GET /workflows/{id}` · `GET /workflows/{id}/versions`
- `PATCH /workflows/{id}` — save canvas edits (nodes/edges/bindings/topology)
- `POST /workflows/{id}/validate` — unbound inputs, type mismatches, cycles, missing auth
- `POST /workflows/{id}/compile` — compile graph → ADK graph workflow (dry-run; returns plan)
- `POST /workflows/{id}/nodes/{nodeId}/materialize` — create a `to_be_created` provisional agent into the Garden
- `GET/PUT /workflows/{id}/config` — read/update the full workflow configuration (Section 6.6: topology, collaboration defaults, models/cost, memory, streaming/modality, HITL, plugins, guardrails, observability, lifecycle)
- `GET /workflows/{id}/collaboration-graph` — resolved delegation/agent-tool/A2A edges for canvas rendering

### 18.5 Execution
- `POST /runs` — execute a workflow (or single agent) with dynamic user input → returns `run_id`
- `WS /runs/{id}/stream` — **live event stream**: tokens, tool calls/results, state mutations, node transitions, span events (drives the animated DAG); carries typed `ActivityEvent`s (Section 25) that power the live reasoning/"thinking" panel
- `GET /runs/{id}` · `GET /runs` — status, result, artifacts, MLflow trace ref
- `POST /runs/{id}/pause` · `/resume` · `/cancel`
- `GET /runs/{id}/plan` · `POST /runs/{id}/plan/approve` — Plan Mode: fetch the proposed plan, approve/edit before execution
- `POST /runs/{id}/steer` — inject mid-run guidance into a live session
- `POST /runs/{id}/deliverable/edit` — edit-in-place on a highlighted span of the output
- `GET/POST /schedules` · `PATCH/DELETE /schedules/{id}` — cron/event triggers for unattended runs
- `GET /runs/{id}/artifacts/{artifactId}` — download output artifact
- **Realtime (Bidi/Live):** `WS /runs/live` — bidirectional audio/video/text via `run_live()` + `LiveRequestQueue` (barge-in/interrupt supported)

### 18.6 Human-in-the-loop
- `GET /approvals` — pending `RequireConfirmation` events (Approval Inbox)
- `POST /approvals/{id}/approve` · `POST /approvals/{id}/reject` — resumes the paused run

### 18.7 Observability (MLflow-backed)
- `GET /traces/{run_id}` — full span tree; `GET /traces` — search/filter
- `GET /metrics/overview` — success rate, p50/p95 latency, cost, token usage (by workflow/team/day)
- `POST /runs/{id}/feedback` — attach 👍/👎 + comment (→ trace assessment)
- `GET/POST /evaluations` — golden datasets; `POST /evaluations/{id}/run` — run `mlflow.genai.evaluate`
- `GET /prompts` · `GET /prompts/{name}/versions` — MLflow Prompt Registry
- `GET/POST /alerts` — thresholds on error/latency/cost/quality

### 18.8 Admin & governance
- `GET /audit` — audit log; `GET/POST /guardrails` — org-level policies (PII, content, HITL triggers)
- `GET/POST /deployments` — deploy target config (Cloud Run / GKE / Vertex Agent Engine)
- `GET /costs` — cost attribution & budget status

### 18.9 Platform Insights (Meta-Observability — Section 24)
- `GET/PUT /insights/config` — read/update the insights configuration
- `POST /insights/run` — trigger the insights workflow on demand
- `GET /insights/runs` · `GET /insights/runs/{id}` — analysis run status & trace
- `GET /insights/reports` · `GET /insights/reports/{id}` — list / download the generated Word report
- `GET /insights/findings` — machine-readable findings JSON (feeds dashboards/alerts)

**Streaming summary:** WebSocket is used for (a) design reasoning, (b) test runs, (c) execution event streams, and (d) realtime Live-API agents. Everything else is REST. This is the complete contract the frontend needs — nothing about ADK leaks to the client.

---

## 19. Design learnings adopted from Claude / Cowork agentic design

These are **product and design patterns** drawn from Anthropic's public agent guidance ("Building Effective Agents," context-engineering, agent-harness work, the Agent SDK) and the Claude Cowork product. **Our backend stays entirely in Google ADK** — each learning is realized with native ADK primitives, not Anthropic code.

| Learning (source) | Feature we add | ADK realization | Status |
|---|---|---|---|
| Agent loop is *gather → act → **verify** → repeat*; Cowork self-verifies before reporting | **Self-verification / critic step** on outputs | Critic/reviewer agent or `LoopAgent` + eval gate; `mlflow.genai` check | 🆕 |
| Transparency: show the plan, approve before acting (Cowork "plan → approval") | **Plan Mode** (visible plan, approve/edit/steer first) | Plan step gated by `RequireConfirmation`; plan rendered on canvas | 🆕 |
| Users steer mid-task (Cowork) | **Mid-run steering** | New message into live session / `LiveRequestQueue` | 🆕 |
| Long-running, unattended, scheduled, steer-from-anywhere (Cowork) | **Scheduled/unattended runs + remote steering** | Cloud Scheduler/Pub-Sub → Runner; resumable sessions | ⬆ Expanded |
| Context is a finite budget; JIT retrieval; "file system as context" | **Workspace + file-system-as-context** | ArtifactService + list/read/search tools; `state` holds refs, not blobs | 🆕 (formalized) |
| Sub-agents = isolated context returning distilled summaries ("search subagent") | **Context-isolated collaborators returning summaries** | Task-mode isolated session branch; `AgentTool` structured return | ✅ + guidance |
| Compaction for long-horizon tasks | Context-window compression | RunConfig compression | ✅ Already |
| Simplicity; deterministic *workflows* vs autonomous *agents*; add complexity only if it helps | **Per-node deterministic-vs-autonomous toggle** | Graph/Sequential (deterministic) vs `LlmAgent` autonomy | ✅ Made explicit |
| Route easy/cheap vs hard/capable models (routing pattern) | **Cost-aware model routing/tiering** | Router node → Gemini 3 Flash vs Pro | 🆕 |
| Prompt caching; keep static content stable | **Cache-aware config** | Stable system prompt + tool set across calls | 🆕 |
| Tools: self-contained, non-overlapping, token-efficient, "justify existence" | **Tool-design linting** in the Registry | Applied to FunctionTool/OpenAPI specs (flag overlap, weak descriptions, verbose outputs) | 🆕 |
| Plugins bundle skills+connectors+sub-agents into a role specialist (Cowork) | **Bundles / Role Packs** (Legal, Finance, …) | Packaged Agent Configs + Skills + tool specs | 🆕 |
| Outcome-oriented UX: describe outcome, return to finished work (Cowork) | Core Workflow Studio flow | Goal → Designer Agent → run → review | ✅ Already |
| Parallel workstreams / sectioning (Cowork; parallelization) | Parallel decomposition | `ParallelAgent` chosen by Designer | ✅ Already |
| Edit deliverable in place ("Edit with Claude") | **Inline deliverable editing** | Scoped re-run on highlighted span | 🆕 |
| Permission model: scoped access, approval for consequential/destructive actions, sandbox (SAIF) | **Hardened permission + sandbox model** | `RequireConfirmation` on destructive tools; scoped egress; isolated exec | ⬆ Strengthened |
| Enterprise: spend controls, per-dept tool permissions, activity → SIEM via OTel (Cowork Enterprise) | **Admin spend/permission controls + SIEM export** | OTel dual-export to SIEM; RBAC by dept; budgets | ⬆ Strengthened |
| Anthropic-built vertical agents (legal/finance) | **Foundation vertical bundles** | Prebuilt Agent Configs in the Garden | 🆕 (via Bundles) |

**Net-new features introduced by this pass:** Plan Mode · self-verification/critic step · mid-run steering · workspace + file-system-as-context · cost-aware model routing · cache-aware config · tool-design linting · Bundles/Role Packs (+ vertical packs) · inline deliverable editing · expanded scheduling/unattended runs · hardened permissions + SIEM export.

**Deliberately *not* copied** (Cowork's disclosed early limitations): no cross-session memory, desktop-only/no sync, and no audit trail for regulated data. Our plan addresses all three by design — persistent Memory Bank/RAG memory (Section 12), a server-side platform reachable from any surface, and full audit logging + MLflow/OTel traces for governance.

**Guiding principle carried over:** *do the simplest thing that works.* The Designer Agent defaults to the least complex topology that satisfies the goal (single agent → workflow → multi-agent), escalating only when evaluation shows a simpler structure falls short — matching Anthropic's "add complexity only when it demonstrably improves outcomes."

---

## 20. UI Design Language (Palantir-inspired, dark)

The platform's UI should read as an **operational control surface**, not a consumer chat app — dense, precise, information-first, in the spirit of Palantir's platform design. Implement it with **Blueprint.js** (Palantir's open-source, Apache-licensed React toolkit built specifically for complex, data-dense desktop interfaces), running in **dark theme**. This gives the aesthetic natively without copying any proprietary Palantir product.

**Aesthetic principles**
- **Dark, near-black canvas.** Base background near-black; content sits on slightly lighter panels. High-contrast text; color used sparingly and only to carry meaning (status, node type, severity).
- **Density over whitespace.** Compact tables, tight rows, multi-pane layouts. Assume expert users who want a lot on screen at once.
- **Data-forward.** Everything is inspectable — IDs, timestamps, token counts, costs, versions visible on hover/expand. Monospace for identifiers, code, and metrics.
- **Structured panels.** Left nav rail → main workspace → right inspector/detail drawer. Resizable, dockable panes.
- **Purposeful motion.** Motion communicates state (a hand-off animating along an edge, a node turning active), never decoration.

**Design tokens (starting point)**
- Background `#111418` (app) / `#1C2127` (panels) / `#252A31` (raised); borders `#404854`.
- Text `#F6F7F9` (primary) / `#ABB3BF` (muted).
- Accent/intent (Blueprint dark palette): primary `#4C90F0`, success `#32A467`, warning `#EC9A3C`, danger `#E76A6E`.
- Node-type hues: reused `#32A467` (green), to-be-created `#EC9A3C` (amber), modified `#4C90F0` (blue), remote/A2A `#8F7EE6` (violet).
- Type: Inter/IBM Plex Sans for UI; JetBrains Mono / IBM Plex Mono for code & metrics.

**Blueprint components mapped to screens**
- Global: `Navbar`, `Tabs`, dark `Card`/`Section`, `Tree` (nav), `Drawer` (inspector), `Toaster` (notifications).
- Agent Garden: `Card` grid + `Table` view toggle, `TagInput`/`Menu` filters, `InputGroup` search.
- Creation wizard: `MultistepDialog`, `FormGroup`, `Select`/`MultiSelect`, `Switch`, `NumericInput`, `TextArea` (prompts), `Tabs` for tool/collaboration/memory steps.
- Workflow canvas: **React Flow** for the graph, Blueprint `ContextMenu`, `Popover` node inspectors, `Callout` for validation.
- Monitoring: dense `Table` (runs), `Tree` (span/trace), Recharts/Plotly in dark theme for metrics.
- Execution: `ProgressBar`, `Spinner`, streaming activity log in a monospace panel.

---

## 21. Surfacing the agentic learnings in the UI

Every capability added in Sections 17–19 must be *visible and operable*, not just wired in the backend. Explicit UI placement:

| Capability | Where it shows in the UI |
|---|---|
| **Collaboration** (delegate / agent-tool / A2A) | Creation wizard "Collaboration" step; canvas edge styles (dashed=delegate, dotted=call, violet=A2A), expandable coordinator container, mode badges (chat/task), live hand-off animation |
| **Plan Mode** | Pre-execution **Plan panel**: numbered plan steps rendered on the canvas; "Approve / Edit / Steer" buttons; run won't start until approved |
| **Self-verification / critic** | A verification node with a pass/fail chip; the critic's assessment shown in the run detail; auto-revise iterations counter |
| **Mid-run steering** | Persistent "Steer" input on the live run view; injected guidance appears inline in the activity log |
| **Workspace / file-as-context** | A **Workspace file tree** panel per run (artifacts in/out); click to preview; shows what was loaded just-in-time vs kept as reference |
| **Model routing / cost tiering** | Per-node model badge (Flash/Pro); a router node visualized as a branch; live cost meter (tokens × price) in the run header |
| **Bundles / Role Packs** | A "Bundles" tab in the Garden with install cards (Legal, Finance…); installed packs group their agents |
| **Inline deliverable editing** | On the output preview, highlight text → "Edit with agent" popover → scoped re-run diff |
| **Scheduling / unattended** | A "Schedules" screen (cron/event triggers, next-run, last-run status); runs continue server-side and are resumable from any surface |
| **HITL / approvals** | An **Approval Inbox** badge in the navbar; approve/reject cards with the pending action and its arguments |
| **Observability (MLflow)** | The run's **trace tree** (spans), token/cost/latency panels, 👍/👎 feedback, prompt-version link, and eval scores — all in dark dense tables |
| **Guardrails / permissions** | Per-tool permission chips, "requires approval" markers, redaction indicators; admin screens for spend/permission-by-department + SIEM export status |

**Rule:** if a feature has no UI surface here, it isn't done. Each row is an acceptance criterion for the frontend.

---

## 22. Seed data — default agents & runnable sample workflows

The platform must **ship pre-loaded** so a new user can execute something on first login. A **seed loader** (run on first boot / migration) writes these Agent Cards and Workflow Graphs to NoSQL and registers their prompts in MLflow.

### 22.1 Default foundation agents (seeded)
| Agent | Model | Tools / capability | `output_key` | Notes |
|---|---|---|---|---|
| **Web Researcher** | Gemini 3 Flash | built-in web search; spawns parallel search sub-agents | `research_findings` | returns distilled summaries, not raw pages |
| **Document Q&A (RAG)** | Gemini 3 Pro | Vertex RAG retrieval over uploaded docs | `answer` | grounded citations |
| **Data Extractor** | Gemini 3 Flash | `parse_file` function tool (CSV/XLSX/PDF) | `raw_data` | structured output schema |
| **Analyst** | Gemini 3 Pro | code execution | `analysis_result` | reads `raw_data` |
| **Summarizer** | Gemini 3 Flash | — | `summary` | length/format params |
| **Email/Comms Drafter** | Gemini 3 Flash | email OpenAPI tool (`RequireConfirmation` on send) | `email_draft` | HITL before send |
| **Critic / Reviewer** | Gemini 3 Pro | — | `verdict` | verification step; tagged pass/revise |
| **Router / Classifier** | Gemini 3 Flash | — | `route` | model/agent routing |
| **Workflow Designer Agent** | Gemini 3 Pro | Garden capability search | `workflow_graph` | design-time meta-agent |

### 22.2 Sample workflows (seeded, executable)

**A. Quarterly Sales Analysis** *(sequential + approval)*
`Data Extractor` (`raw_data`) → `Analyst` (`analysis_result`) → **Critic** (verify) → `Email/Comms Drafter` (`email_draft`, approval gate before "send").
Input: a sales CSV. Output: analysis + drafted exec email awaiting approval.

**B. Research Brief** *(parallel + verify)*
`Web Researcher` (parallel search sub-agents → `research_findings`) → `Summarizer` (`summary`) → **Critic** (auto-revise until pass) → deliverable.
Input: a topic/question. Output: a cited brief.

**C. Document Review Q&A** *(RAG + structured output)*
Upload docs → `Document Q&A (RAG)` (`answer`) → **Critic** (groundedness check) → structured findings table.
Input: documents + a list of questions. Output: answers with citations and a confidence chip.

Each sample ships with a small **sample input file** in the workspace so "Run" works immediately and produces a full MLflow trace for the monitoring screens.

---

## 23. Construction Guide (end-to-end, build-ready)

### 23.1 Monorepo layout
```
platform/
├── frontend/                 # React + TS + Blueprint.js (dark), React Flow
│   ├── src/screens/          # garden, creation-wizard, canvas, runs, monitor, admin
│   ├── src/components/       # blueprint-wrapped dense components
│   └── src/api/              # typed client for the FastAPI contract (Section 18)
├── backend/
│   ├── control_plane/        # FastAPI: agents, tools, workflows, runs, approvals, admin
│   ├── adk_runtime/          # Agent Factory, Workflow Compiler, Runner builder, Plugin manager
│   ├── realtime/             # WebSocket service using run_live() + LiveRequestQueue
│   ├── workers/              # scheduler (cron/event), long-running & HITL-paused runs
│   ├── seed/                 # seed loader: default agents + sample workflows (Section 22)
│   └── common/               # schemas (Pydantic), auth/RBAC, config, secrets client
├── infra/                    # IaC: Firestore/Mongo, Postgres, MLflow, GCS, Vault, deploy
└── docs/                     # this plan + ADRs
```

### 23.2 Core backend modules (the "hard parts")
- **Agent Factory** — hydrates an Agent Card → live ADK object; serializes Card ⇄ **Agent Config (YAML)**; resolves tools (`FunctionTool`/`OpenAPIToolset`/`MCPToolset`/`AgentTool`) and collaboration wiring (`sub_agents`, transfer flags, A2A).
- **Workflow Compiler** — graph JSON → ADK **2.0 graph workflow** (with Sequential/Parallel/Loop sub-cases); validates bindings; inserts verification/approval nodes.
- **Runner builder** — attaches Plugins (`AutoTracingPlugin`→MLflow, retry-and-reflect), `RunConfig` (budgets/modality/streaming), and Session/Memory/Artifact services (Vertex managed or Postgres/GCS).
- **Plugin manager, Tool Registry (+ linting), Seed loader.**

### 23.3 Data stores
Firestore/Mongo (cards, workflows, tool specs, runs, versions, audit) · Postgres (ADK sessions **and** MLflow backend — required for OTLP) · GCS (artifacts) · Vault/Secret Manager (credentials).

### 23.4 Build phases with acceptance criteria (Definition of Done)
1. **Phase 0 — Runtime spine.** Factory builds one `LlmAgent` from a hand-written Card; Runner runs it; `AutoTracingPlugin` lands a trace in MLflow. **DoD:** a scripted single-agent run appears as a trace in the MLflow UI.
2. **Phase 1 — Creation + Garden + Tools.** Wizard (incl. tool mapping via OpenAPI upload) writes a Card to NoSQL; Garden lists it; test-panel run streams. **DoD:** create an agent in the UI, map a function + an OpenAPI tool, test it live.
3. **Phase 2 — Execution + Monitoring.** Runner service + SSE/WS streaming; run list, trace tree, cost/latency dashboards; HITL Approval Inbox. **DoD:** run an agent, watch the live stream, approve a gated action, inspect the trace.
4. **Phase 3 — Workflow Studio.** Designer Agent → graph; React Flow canvas with collaboration edges; compiler → graph workflow; Plan Mode. **DoD:** type a goal, get a reuse-first graph, edit it, approve the plan, execute end-to-end.
5. **Phase 4 — Learnings layer.** Verification/critic, model routing, workspace/file-as-context, mid-run steering, scheduling, Bundles, inline editing. **DoD:** each row in Section 21 is visible and operable.
6. **Phase 5 — Enterprise hardening.** RBAC/multi-tenancy, guardrails, spend controls, SIEM export, eval/CI gates, A2A remote agents. **DoD:** admin can scope access by team, cap spend, and stream activity to a SIEM.

### 23.5 Seed & demo (proves the whole stack)
On first boot, the **seed loader** installs the Section 22 agents + sample workflows with sample inputs. **Smoke test / demo script:** open "Quarterly Sales Analysis" → Run → approve the email gate → view the completed run's MLflow trace. If that passes, the create → compose → execute → observe loop is proven end-to-end.

### 23.6 Environment & config
Per-env config for: model/LLM gateway keys (Gemini + LiteLLM providers), Vertex vs. self-hosted session/memory choice (Open Decision #1), NoSQL + Postgres + GCS + Vault endpoints, MLflow tracking URI (`/v1/traces` OTLP + `x-mlflow-experiment-id`), deploy target (Cloud Run / GKE / Vertex Agent Engine). Pin an explicit **stable** Gemini model in production rather than inheriting ADK's moving preview default, and pin a specific **ADK release** before Phase 0.

---

## 24. Module 6 — Platform Insights & Recommendation Workflow (Meta-Observability)

A **first-class, always-available workflow** that observes how the platform itself is being used — what users build, what they execute, and how it goes — and turns that into a **recommendation report (Word/.docx)**. It is the platform's self-improvement and governance loop. Crucially, it **dogfoods the platform**: it is itself an ADK workflow, compiled by the same Compiler, run by the same Runner, and traced in MLflow like any other.

### 24.1 Purpose
Act as a **data-capture and learning layer**. Continuously (or on demand) aggregate signals from across the platform, detect issues and patterns, and generate prioritized, evidence-backed recommendations that help teams fix problems, cut cost, and improve reliability and reuse.

### 24.2 Placement in the UI (surfaced upfront)
A dedicated top-level **"Insights"** entry in the left nav, split into two distinct surfaces (per the requirement that execution and report generation are separate):
- **Insights › Analysis (execution):** configure and run the meta-workflow — scope, time window, cadence, data sources, thresholds — and watch its run/trace live.
- **Insights › Reports (report library):** browse, preview inline, and download the generated Word reports; see highlights and trends. This surface never triggers analysis; it only serves finished reports.

### 24.3 What it captures (data sources)
- **MLflow:** traces/spans, latency, token & cost, tool errors, retries, eval scores, 👍/👎 feedback, prompt-version lineage, HITL rejections.
- **NoSQL:** agent cards (config, versions, models, tools), workflows (topology, edit history, abandonment before execution), runs (status/outcomes), audit log, bundles.
- **Tool Registry:** tool/API usage, failure & auth-error rates, verbose-output flags.
- **Behavioral/usage:** create vs reuse patterns, most/least used agents & workflows, dynamic-agent creation frequency, guardrail hits, spend vs budget.

It reads via **read-only** service accounts and honors the trace **content-capture policy** (metadata-only vs content) and redaction rules — it never exposes content the governance policy forbids.

### 24.4 What it analyzes (issues & patterns detected)
- **Failures:** common error signatures, failing tools/APIs, timeouts, retry storms.
- **Cost/efficiency:** expensive agents/workflows, token-heavy nodes, model-tier mismatch (Pro used where Flash suffices), redundant work.
- **Quality regressions:** eval-score drops correlated to a prompt/model version change (via MLflow lineage).
- **UX friction:** workflows heavily edited after auto-design, high HITL rejection rates, high abandonment before first execution.
- **Garden health & reuse:** duplicate/near-duplicate agents to consolidate, unused foundation agents, capabilities repeatedly created dynamically → candidates to promote into the Garden/Bundles.
- **Governance:** PII redactions, permission denials, budget-threshold breaches.

### 24.5 The workflow itself (ADK, multi-agent — seeded)
Sequential pipeline (Analyzer stage may fan out in parallel across data domains):
1. **Insights Collector** — pulls MLflow + NoSQL + Tool Registry data via function/API tools into a structured dataset; stores it in the run **workspace** as files and passes lightweight references (file-as-context), not raw blobs.
2. **Pattern & Anomaly Analyzer** — code-execution agent that computes aggregates, trends, correlations, and anomalies (e.g., cost-per-workflow over time, error clustering, version-vs-quality regressions).
3. **Recommendation Synthesizer** — LLM agent that converts findings into prioritized, actionable recommendations, each as *issue → evidence → impact → recommended action → severity*.
4. **Report Writer** — generates the **Word (.docx)** report using the backend document-generation capability (server-side docx generation), with an executive summary, tables, and embedded trend charts; saved as an **artifact** and downloadable.
5. **Critic (verification)** — confirms every recommendation is grounded in captured evidence before the report is published (reuses the platform's self-verification pattern).

### 24.6 Configuration (drives behavior)
A stored `insights_config` (schema in Appendix A): scope (org/team/user/specific workflows), time window, cadence (on-demand / cron / event), data-source toggles, thresholds (cost, latency, error-rate, eval-drop, abandonment), recommendation categories to include, minimum severity, report branding/format, delivery (download / email / scheduled), retention, and privacy mode (metadata-only vs content).

### 24.7 Output
- **Primary:** a Word document — *"Platform Insights & Recommendations Report"* — with executive summary, usage overview, issues by category (with evidence + severity), prioritized recommendations, trend charts, and a metrics appendix.
- **Secondary:** a machine-readable **findings JSON** (Appendix A) that also feeds dashboards and alerts.

### 24.8 Backend & isolation
Built and run on the standard stack (Factory → Compiler → Runner). Its own traces are **tagged `meta:true`** so they don't pollute user-facing analytics. Scheduling runs through the workers/scheduler service. Because it's a normal workflow, it is versioned, permissioned (admin/insights role), and auditable like everything else.

### 24.9 Seed
Ship a **"Weekly Platform Insights"** workflow (scheduled, **disabled by default** until an admin enables it) plus its constituent agents (Collector, Analyzer, Synthesizer, Report Writer) seeded in the Garden under a **system** category. This makes the capability present upfront and runnable on day one.

### 24.10 API (also listed in 18.9)
`GET/PUT /insights/config` · `POST /insights/run` (on-demand) · `GET /insights/runs` · `GET /insights/runs/{id}` · `GET /insights/reports` · `GET /insights/reports/{id}` (download .docx) · `GET /insights/findings` (JSON).

---

## 25. Live Reasoning & Activity Stream (real-time "thinking" updates)

During execution, the user should see a continuous, human-readable narration of what the workflow is doing — status, contemplation, reasoning — like watching a capable colleague think out loud, not reading raw logs. This is a signature experience of the platform.

### 25.1 What the user sees
A live **Activity Stream** panel (docked beside the animated DAG) with time-stamped, present-tense entries, e.g.:
- Phase markers — *"Planning the approach…"*, *"Executing step 2 of 4…"*
- Agent hand-offs — *"Handing off to the Analyst agent…"*, *"Control returned to the coordinator."*
- Tool calls — *"Querying the ERP for June invoices…"*, *"Searching the web: 'Q3 semiconductor exports'…"*
- Reasoning / musing — *"The two revenue figures don't match — reconciling before I continue."*
- Verification — *"Double-checking the summary against the source documents…"*
- Results — *"Found 412 records."*, *"Draft ready for your approval."*

Each entry is **synchronized with the DAG**: the active node pulses, and clicking an entry focuses its node. The current agent's output streams token-by-token (typewriter). A subtle "thinking" shimmer/pulsing-dots indicator shows while an agent reasons or a tool is in flight. Every entry is expandable to its raw detail (redacted args, tokens, latency).

### 25.2 Where the data comes from (ADK)
- The **Runner event loop** yields an `Event` for every step: model requests, streaming partial responses, function (tool) calls and responses, `state` deltas, agent transfers, and control returns. This is the raw material.
- **Callbacks** (`before/after_agent`, `before/after_model`, `before/after_tool`) are the hook points that emit structured activity events with rich context (which agent, which tool, arguments, timing).
- **Gemini "thinking"** (when enabled) exposes reasoning/thought parts; distilled thought summaries become *reasoning* entries — subject to the privacy policy in §25.6 (never verbatim chain-of-thought in metadata-only mode).
- An **`ActivityStreamPlugin`** on the `Runner` centralizes capture — the live-UX sibling of `AutoTracingPlugin`. One event source fans out to **two sinks**: MLflow (durable trace) and the live stream (ephemeral UX). No double instrumentation.

### 25.3 The Narration layer (turning events into musings)
A two-tier design so the "thinking" reads naturally without adding cost or latency to the actual work:
1. **Deterministic templated narrator (default).** Maps `event kind + metadata` → a friendly phrase from a varied phrase pool (avoids repetition), present-tense, localizable. Fast, free, reliable. Example: `before_tool(web_search, query=X)` → *"Searching the web for '{X}'…"*.
2. **LLM-flavored narrator (optional).** A cheap side-channel model (Gemini 3 Flash) periodically summarizes clusters of events into richer, contemplative language (*"The sources disagree, so I'm reconciling them before drafting."*). Runs **out-of-band** so it never blocks or slows the main workflow; rate-limited and cost-capped; toggle per workflow.

Phrase **style** is configurable (concise-ops vs. conversational); enterprise default is concise and professional. Reasoning entries respect the show-reasoning setting (off / generic indicator / summarized).

### 25.4 Event schema (`ActivityEvent`, streamed over WebSocket)
Extends the `WS /runs/{id}/stream` contract (§18.5). Formal schema in Appendix A. Example frame:
```json
{
  "run_id": "run_9f2",
  "seq": 128,
  "ts": "2026-07-01T06:00:12.480Z",
  "node_id": "n2",
  "agent": "financial_analyst",
  "phase": "act",
  "kind": "tool_call",
  "label": "Querying the ERP for June invoices…",
  "detail": { "tool": "erp.getInvoices", "args": "«redacted»" },
  "level": "info",
  "token_delta": 0, "cost_delta_usd": 0.0, "latency_ms": null
}
```
`kind ∈ {phase, agent_enter, agent_exit, tool_call, tool_result, reasoning, token, state_update, verification, approval_pending, error, complete}`.

### 25.5 Transport & performance
- **Pipeline:** `ActivityStreamPlugin` → in-process async queue → per-run pub/sub (Redis) → WebSocket fan-out to all watchers of the run.
- **Backpressure:** coalesce token deltas, throttle high-frequency events, and degrade-to-summary if a client is slow — the workflow never waits on the UI.
- **Ordering & resilience:** monotonic `seq`; client renders in order and tolerates gaps. On reconnect the client resumes from its last `seq`; the server replays from a bounded ring buffer.
- **Post-run replay:** events are persisted with the run, so "watch what happened" works after the fact (or is reconstructed from the MLflow trace). Realtime/BIDI agents (`run_live`) feed the same stream (plus audio).

### 25.6 Privacy & governance
The stream honors the trace **content-capture policy**: in *metadata-only* mode it shows generic phrases and redacted args (no verbatim thoughts or payloads); in *content* mode it shows richer detail with PII redaction. Everything is mirrored to MLflow for audit; the live stream itself is ephemeral but replayable.

### 25.7 UI (Blueprint, dark)
Virtualized scrolling list; monospace timestamps; a kind-colored left rail; agent/tool icons; the active entry animated (shimmer = "thinking"); expandable detail popover; filter chips (reasoning / tools / errors only); and a live **cost + latency ticker** in the header. The panel is the same in live and replay modes.

### 25.8 Configuration
Per-workflow (also in §6.6): narration on/off · narrator tier (templated / LLM-flavored) · phrase style · show-reasoning (off / generic / summarized) · throttle level · LLM-narrator cost cap.

---

## 26. Signature Screens — Agent Garden & Workflow Studio

These two screens are where users spend their time; they must feel like a polished, scalable, Palantir-grade enterprise product — dense, precise, high-signal, dark.

### 26.1 Agent Garden (a catalog users enjoy)
- **Layout:** left **facet rail** (filters: category, domain, tags, model, tools, owner, bundle, status) · center results with a **grid ↔ data-table toggle** · right **preview drawer**.
- **Agent card:** icon, name, role, one-line capability, model badge (Flash/Pro), tool chips, collaboration-role tag, version, a **usage sparkline** (runs over time), a **success-rate ring**, reuse count, rating. Hover reveals quick actions (Add to workflow · Clone · Inspect · Test).
- **Data-table view (power users):** sortable dense columns — name, category, model, runs, success %, avg cost, p95, last used, version — the Palantir "operate on thousands of rows" feel.
- **Detail drawer:** the full Agent Card (prompts, tools, a mini collaboration-graph, memory/context config), version history, **live usage metrics pulled from MLflow**, "used in N workflows," and an inline test panel.
- **Bundles tab:** Role Packs (Legal, Finance…) as install cards; installed packs group their agents — a curated marketplace feel.
- **Search:** instant hybrid keyword + **capability search** ("an agent that can summarize contracts") over the embedding index.
- **Scale & polish:** virtualized lists, server-side pagination/filter (handles thousands of agents), smooth micro-interactions, status conveyed by color, monospace metrics. First-run shows the seeded foundation agents immediately so it's never empty.

### 26.2 Workflow Studio (a canvas users enjoy)
- **Three panes:** left **palette** (Garden agents, tools, and control nodes — parallel / loop / branch / approval / sub-workflow — draggable) · center **React Flow canvas** · right **inspector**.
- **Goal bar:** a top natural-language input → the Designer Agent → the graph **assembles with animation** (nodes appear tagged reused 🟢 / new 🟡 / modified 🔵 / remote 🟣), with the design reasoning shown in the Activity Stream (§25).
- **Canvas:** node cards show name, model badge, status color, and I/O ports; distinct edge styles for data / delegation / call / A2A; expandable coordinator grouping; **minimap**, snap-grid, one-click **auto-layout** (dagre), zoom/pan, multi-select, keyboard shortcuts.
- **Inspector:** edit prompts, model, tools, collaboration, retries, approval gates, and input bindings, with **live validation callouts** (unbound inputs, cycles, missing auth).
- **Overlays:** a data-flow toggle (show which `state` keys travel each edge) · **Plan Mode** (proposed steps rendered before run: approve / edit / steer) · **execution mode** where the same canvas animates live (active node pulses, hand-offs animate, cost/latency ticker, docked Activity Stream).
- **Versioning:** version dropdown with a **visual diff** between versions (added / removed / changed nodes highlighted).
- **Scale & polish:** handles large graphs (100+ nodes) via clustering/collapse and off-screen virtualization; a dark "ops-room" aesthetic with precise grid and glowing accents on active paths.

---

## Appendix A — Data Contracts (single source of truth)

Formal schemas for every persisted entity, so the platform can be built from this document alone. `AgentCard` and `WorkflowGraph` canonical JSON already appear in **Sections 9.1 and 9.2**; the remaining entities are defined here. Types are indicative (Pydantic/JSON).

**ToolSpec** (`tool_specs`)
`id: str` · `name: str` · `type: enum[function|openapi|mcp|agent|builtin]` · `description: str` (LLM-facing) · `signature|openapi_spec|mcp_endpoint: obj` · `operations: list[str]` · `auth_ref: str` (Vault ref) · `rate_limit: obj` · `allowed_operations: list[str]` · `requires_confirmation: bool` · `output_shaping: obj` · `version: int` · `owner/visibility` · `lint: {overlap_flag, weak_description, verbose_output}`.

**CollaborationBlock** (embedded in `AgentCard.collaboration`)
`role: enum[standalone|coordinator|specialist|peer]` · `collaborators: list[{agent_ref: str, type: enum[delegate|agent_tool|a2a_peer], mode: enum[chat|task|single_turn]?, auth_ref: str?}]` · `transfer: {allow_transfer_to_parent: bool, allow_transfer_to_peers: bool, escalation_policy: str}` · `routing_instruction: str?` · `shared_state_keys: list[str]`.

**Bundle** (`bundles`)
`id: str` · `name: str` · `category: enum[legal|finance|...|custom]` · `description: str` · `agents: list[agent_ref]` · `tools: list[tool_ref]` · `skills: list[skill_ref]` · `prompts: list[prompt_ref]` · `version: int` · `visibility` · `installs: int`.

**Run** (`runs`)
`run_id: str` · `workflow_id/version: str/int` (or `agent_id` for single-agent) · `status: enum[pending|planning|awaiting_approval|running|paused|succeeded|failed|cancelled]` · `input: obj` · `plan: obj?` (Plan Mode) · `mlflow_trace_id: str` · `artifacts: list[{id,name,uri,mime}]` · `cost_usd/tokens/latency_ms: num` · `approvals: list[approval_id]` · `meta: bool` · `user/team` · `created/updated_at`.

**Schedule** (`schedules`)
`id: str` · `workflow_id: str` · `trigger: enum[manual|cron|event]` · `cron: str?` · `event: {source,type}?` · `input_template: obj` · `enabled: bool` · `next_run/last_run/last_status` · `owner`.

**Approval** (`approvals`)
`id: str` · `run_id: str` · `node_id: str` · `tool: str` · `arguments: obj` (redacted per policy) · `status: enum[pending|approved|rejected]` · `decided_by/at` · `reason: str?`.

**InsightsConfig** (`insights_config`)
`scope: {level: enum[org|team|user|workflow_set], ids: list[str]}` · `window: {from,to}|rolling_days: int` · `cadence: enum[on_demand|cron|event]` · `cron: str?` · `sources: {mlflow,nosql,tool_registry,behavioral: bool}` · `thresholds: {cost_usd,latency_ms,error_rate,eval_drop,abandonment_rate}` · `categories: list[enum[failures|cost|quality|ux|reuse|governance]]` · `min_severity: enum[low|med|high]` · `report: {format,branding}` · `delivery: {download,email,scheduled}` · `retention_days: int` · `privacy_mode: enum[metadata_only|content]`.

**Finding** (element of `findings JSON`)
`id: str` · `category: enum[failures|cost|quality|ux|reuse|governance]` · `severity: enum[low|med|high]` · `title: str` · `evidence: list[{source: enum[mlflow|nosql|tool_registry], ref: str, metric: obj}]` · `impact: str` · `recommended_action: str` · `affected: {agents,workflows,tools: list[str]}` · `first_seen/last_seen`.

**InsightsReport** (`insights_reports`)
`id: str` · `run_id: str` · `generated_at` · `docx_uri: str` (artifact) · `findings: list[Finding]` · `summary: str` · `scope` · `window`.

**Prompt** (MLflow Prompt Registry ref) · **AuditEntry** (`audit_log`): `id, actor, action, entity_type, entity_id, before/after, at`.

**ActivityEvent** (streamed over `WS /runs/{id}/stream`; ring-buffered + persisted for replay — §25)
`run_id: str` · `seq: int` (monotonic) · `ts: iso8601` · `node_id: str?` · `agent: str?` · `phase: enum[plan|act|verify|done]` · `kind: enum[phase|agent_enter|agent_exit|tool_call|tool_result|reasoning|token|state_update|verification|approval_pending|error|complete]` · `label: str` (narrated phrase) · `detail: obj` (redacted per privacy mode) · `level: enum[info|warn|error]` · `token_delta: int?` · `cost_delta_usd: num?` · `latency_ms: int?`.

---

### Naming ideas
AgentForge · AgentStudio · Constellation · AgentMesh · Orchestrate · Nexus Agents · AgentGarden Enterprise.
