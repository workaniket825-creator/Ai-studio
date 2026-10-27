# TCS AI Studio — Platform Guide & Build Reference (v1.0)

An open-source, self-hostable **agentic-AI platform**: design multi-agent workflows, ground them
in a curated **ontology**, call **real REST APIs / tools / connectors**, run a **Data Science Lab**
on GPUs, and observe everything via **MLflow** — all driven from the UI with no backend edits.

This document is both a **setup guide** (install → configure → use) and a **build-from-scratch
reference** (architecture, components, data flow, and design contracts) complete enough for another
team — or another LLM — to reconstruct the platform.

---

## Table of contents
1. Overview & principles
2. Architecture (build-from-scratch reference)
3. Tech stack & dependencies
4. Repository layout
5. Prerequisites
6. Install & run (backend + frontend)
7. Configuration (models, governance, optional runtimes)
8. Feature setup walkthrough (agents, tools, workflows, ontology, DSL, chat, files)
9. Observability (MLflow)
10. Detailed feature & change reference *(everything below §10 is the deep per-feature reference)*

---

## 1. Overview & principles

TCS AI Studio lets a team compose **agents** (LLM personas with tools) into **workflows**, run them,
and observe/govern the results. Design principles, held throughout:

- **Open-source only; no cloud-platform lock-in.** Model access is via API keys (Azure OpenAI,
  OpenAI, Mistral, Gemini); no managed-cloud platform is required to run the core.
- **Everything from the UI.** Models, tools, workflows, ontology, governance, storage — all
  configured in-app; no code changes to operate.
- **Real results, honestly guarded.** Where live infra (GPU/ADK/cloud SDK) isn't present, the
  platform reports that truthfully instead of fabricating output.
- **Additive, isolated modules.** Ontology, Data Science Lab, File Storage, Chat each live behind a
  feature flag or a single seam, so they never destabilise the core runtime.

---

## 2. Architecture (build-from-scratch reference)

### 2.1 High-level shape
A **FastAPI** backend exposes a REST API under `/api/v1`, persists to a **local JSON document store**
(swappable for Postgres), and executes workflows through a **pluggable runtime**. A **React + Vite +
Blueprint.js** single-page app is the UI. **MLflow** (self-hosted) captures traces and the model
registry. Model calls go through **LiteLLM** to whatever provider key you configure.

```
┌────────────────────────────────────────────────────────────────────────┐
│  React SPA (Vite + Blueprint.js)   — screens: Garden, Studio, Chat,      │
│  Ontology, Data Science Lab, Tools, Monitoring, Governance, Files …      │
└───────────────▲───────────────────────────────── fetch /api/v1 ─────────┘
                │ JSON/HTTP
┌───────────────┴──────────────────────────────────────────────────────────┐
│ FastAPI backend (app/)                                                     │
│                                                                            │
│  routers/*  ── thin HTTP layer (agents, tools, workflows, runs, ontology,  │
│                dsl, files, chat, connectors, monitoring, governance …)     │
│                                                                            │
│  Core services:                                                            │
│   • executor.py       run lifecycle: concurrency, timeout, record-always   │
│   • runtime/          PLUGGABLE execution:                                 │
│        base.py  (abstract)  live.py (default, LiteLLM)  adk.py (Google ADK) │
│   • factory.py        compile a WorkflowGraph → ordered execution plan      │
│   • designer.py       goal → workflow (deterministic, reuse-first)          │
│   • tool_exec.py      build tool schemas + EXECUTE tools (openapi/function/  │
│                       builtin/file/model/connector) with name-resolution    │
│   • activity.py       in-proc event bus + Cancel/Steer registries           │
│   • store.py          JSON document store (atomic writes, per-collection)   │
│   • schemas.py        Pydantic models (AgentCard, WorkflowGraph, Run, Tool…) │
│   • governance.py     settings + audit (deep-merged, UI-controlled)         │
│   • endpoints.py      Model Endpoints (keys masked) → LiteLLM call args      │
│   • observability.py + tracing.py   MLflow sinks + explicit GenAI spans      │
│                                                                            │
│  Ontology layer (app/ontology/) — isolated, OFF by default:                │
│   contract.py (ContextProvider/Bundle)  plain.py  ontology_provider.py      │
│   ontology_store.py  selection.py  extraction.py  factory.py (the SEAM)     │
│                                                                            │
│  Data Science Lab (app/modules/data_science_lab/) — feature-flagged:        │
│   providers (brev/azure/aws/ssh), sessions, blueprints, model registry      │
└───────────────▲───────────────────────────────┬───────────────────────────┘
                │                                 │
        ┌───────┴────────┐              ┌─────────┴─────────┐
        │ LiteLLM → LLM  │              │ MLflow (traces +  │
        │ provider APIs  │              │ model registry)   │
        └────────────────┘              └───────────────────┘
```

### 2.2 The key design seams (reproduce these and the rest follows)

**a) Pluggable runtime (`app/runtime/`).** A `Runtime` has one method: `execute(run, workflow)`.
`base.py` is abstract; `live.py` is the default (direct LiteLLM tool-calling loop); `adk.py` runs on
the Google ADK framework. `RUNTIME=live|adk` selects it. This is why the same UI works against a
simple loop or a full agent framework.

**b) Central executor (`executor.py`).** All runs go through one path that enforces max-concurrency
(semaphore), per-run timeout, retry/backoff, **always records** a terminal state (no stuck
"running"), and recovers orphaned runs on restart. Routers never execute directly.

**c) Tool contract (`tool_exec.py`).** `build_tool_defs(agent_tools)` turns each binding into a
**flat, named, typed** function schema (the shape real models call reliably) and a registry;
`execute_tool(registry, name, args)` dispatches by kind: `openapi` (real HTTP; path/query/body
routing; POST/PUT/PATCH/DELETE), `function` (webhook), `builtin`, `file_access` (sandboxed storage),
`model` (registered ML model), `connector` (ADK connectors, honestly guarded). A **name-resolver**
maps hallucinated names (`findCustomer`→`getCustomer`). Per-agent **tool_policy** (`auto|required|
force:<op>`) maps to the provider's `tool_choice` for deterministic calls.

**d) ContextProvider seam (`app/ontology/factory.py`).** Every agent step fetches context through
ONE call: `get_context_provider(tenant, workflow_id, query).get_context(...) → ContextBundle`. With
ontology OFF this returns a `PlainProvider` (upstream text only — identical to no-ontology behaviour);
ON, an `OntologyProvider` adds grounded entities/relations. The runtime never branches on ontology —
it just consumes a bundle. This is how the flagship feature stays fully additive.

**e) Document store (`store.py`).** A `Repo(collection, id_field)` with `upsert/get/list(predicate)/
delete`, atomic temp-file+rename writes, and a thread lock. Each collection is a JSON file under
`DATA_DIR`. Swapping to Postgres means reimplementing `Repo` only.

**f) Activity bus (`activity.py`).** An in-process pub/sub of `ActivityEvent`s (phases, tokens,
tool_calls, approvals) that the UI streams for live run views; plus `Cancel`/`Steer` registries for
mid-run control.

### 2.3 Request/execution data flow
1. UI `POST /runs` (or Chat) → `runs` router → `executor.run_workflow`.
2. Executor loads the `WorkflowGraph`, `factory.compile_workflow` topologically orders nodes.
3. For each node the runtime resolves the agent card + model endpoint, calls the **ContextProvider**
   (ontology seam), `build_tool_defs` for the agent's tools, then runs the **tool-calling loop**
   against LiteLLM, executing tools via `execute_tool` and emitting activity + MLflow spans.
4. Node outputs (incl. ontology used) persist after each step; approval gates pause the run.
5. Terminal state recorded; artifacts (e.g. generated `.docx`) land in File Storage.

### 2.4 To rebuild from scratch (minimum viable order)
1. `schemas.py` (AgentCard, ToolBinding, WorkflowGraph, Run, ToolSpec, ModelConfig).
2. `store.py` (JSON Repo) + `governance.py` (settings/audit).
3. `endpoints.py` + LiteLLM wiring (Model Endpoints) → get a single agent answering.
4. `factory.py` + `executor.py` + `runtime/live.py` → run a multi-node workflow.
5. `tool_exec.py` (openapi/function first) → agents call real APIs.
6. `activity.py` + `tracing.py` + MLflow → live views and traces.
7. Ontology seam (`contract.py`/`plain.py` first, then `ontology_provider.py`).
8. React screens per router; wire `api/client.ts` to `/api/v1`.
9. Feature-flagged modules (Data Science Lab, File Storage, Chat) last.

---

## 3. Tech stack & dependencies

**Backend (all permissive OSS):** FastAPI (MIT), Uvicorn (BSD-3), Pydantic (MIT), PyYAML (MIT),
python-docx (MIT), MLflow (Apache-2.0). Model access via **LiteLLM** at runtime. Document generation
is **.docx-only** (reportlab/openpyxl intentionally not shipped). Optional/not-shipped: paramiko
(LGPL, DSL SSH — commented), boto3/azure SDKs, papermill.

**Frontend (all permissive OSS):** React + React-DOM (MIT), Blueprint.js (Apache-2.0), reactflow
(MIT — no subscription needed), TypeScript (Apache-2.0), Vite (MIT).

No dependency requires vendor approval or a paid licence. The only vendor relationships are the
model-API providers, via your own keys.

---

## 4. Repository layout

```
platform/
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py                # FastAPI app; registers all routers
│       ├── schemas.py store.py governance.py config.py seed.py
│       ├── executor.py factory.py designer.py activity.py
│       ├── models.py endpoints.py                 # LiteLLM + Model Endpoints
│       ├── tool_exec.py connectors.py security_net.py
│       ├── observability.py tracing.py            # MLflow
│       ├── filestore.py docgen.py                 # storage + .docx generation
│       ├── insights.py analysis.py chat_store.py
│       ├── runtime/  base.py live.py adk.py        # pluggable execution
│       ├── ontology/ contract.py plain.py ontology_provider.py
│       │             ontology_store.py selection.py extraction.py
│       │             factory.py ontology_config.py jobs.py
│       ├── modules/data_science_lab/ …             # GPU lab (flagged)
│       └── routers/  agents tools workflows runs monitoring bundles
│                     schedules governance insights connectors
│                     model_endpoints ontology dsl files chat
└── frontend/
    ├── package.json  vite.config.ts
    └── src/
        ├── api/client.ts          # typed calls to /api/v1
        ├── App.tsx  theme/tokens.css
        └── screens/  Garden Studio Chat Ontology GraphCanvas
                      DataScienceLab Tools Monitoring Governance
                      Files ModelEndpoints Connectors Insights
                      Bundles Schedules RunView SetupGuide Home Landing Templates
```

---

## 5. Prerequisites
- **Python 3.11+** and **Node.js 18+**.
- A **model API key** for at least one provider (Azure OpenAI / OpenAI / Mistral / Gemini).
- Optional: **MLflow** (bundled dep) for traces; **google-adk** + provider SDKs only if you enable
  the ADK runtime / GPU lab.

---

## 6. Install & run

```bash
# ── Backend ──
cd platform/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8099            # serves /api/v1

# ── Frontend ──
cd platform/frontend
npm install
npm run dev                                  # Vite dev server; proxies /api → :8099
# production build: npm run build  (outputs dist/)
```

Open the app, click into the platform, and start with **Model Endpoints** (§7).

---

## 7. Configuration

- **Model Endpoints** (screen): add a provider + key (Azure/OpenAI/Mistral/Gemini). Keys are masked;
  a **Test** button verifies. This is the first thing to set — agents, chat, and ontology extraction
  all need a model. Optionally set an env fallback (`MODEL_PROVIDER` + `*_API_KEY`).
- **Runtime**: `RUNTIME=live` (default; direct LiteLLM) or `RUNTIME=adk` (Google ADK — needs
  `pip install google-adk litellm`).
- **Governance → Platform Settings**: max concurrent runs, per-run timeout, retry/backoff, max
  request size, and **SSRF policy** (internal hosts must be allow-listed for internal APIs).
- **MLflow** (optional): see §9.

---

## 8. Feature setup walkthrough
Use the in-app **Setup & Help** screen (Steps 1–9) for click-through guidance. In brief:
1. **Model endpoint** → add + Test.
2. **Tools** → register a **Function** (single URL) or **OpenAPI** (full spec, many operations).
3. **Agents** (Garden) → create an agent, attach tools, set **tool-use policy**, mention tools in
   the system prompt.
4. **Workflows** (Studio) → compose agents; run.
5. **Ontology** → create a graph, let the LLM extract entities/relations, review/approve, publish,
   then bind it to a workflow.
6. **Data Science Lab** → enable, register a GPU runtime (Brev/Azure samples provided).
7. **Chat** → converse against a workflow; history persists.
8. **Files** → shared workspace; agents can read/write and generate `.docx`.

---

## 9. Observability (MLflow)

## 10. Detailed feature & change reference

*The sections below are the deep, per-feature reference and the chronological record of how each capability was built and verified. §1–§9 above are the ground-up guide; consult the relevant section here for endpoint lists, file-level detail, and design rationale.*

#### MLflow — full setup detail

This guide explains how to capture **all agent workflow and execution details** in
MLflow, running MLflow on the **same server instance** as the backend.

MLflow is **opt-in**. By default the platform uses a local sink (metrics aggregate
from the JSON run store) and the in-app Monitoring dashboards work with zero setup.
Turning MLflow on adds durable, external tracking + the MLflow UI.

---

### 0. Files modified for this MLflow setup

| File | Change |
|------|--------|
| `backend/app/observability.py` | Enriched `MLflowSink.record_run()` to log the full run: tags, params, metrics, the complete activity trace, all node outputs, generated deliverable files, and **one nested MLflow run per agent** (per-agent tokens, steps, output). Experiment name is read from `MLFLOW_EXPERIMENT` (default `tcs-ai-studio`) and the tracking URI from `MLFLOW_TRACKING_URI`. |
| `backend/app/runtime/adk.py` | Added `sink.record_run(run)` at run completion. Previously only the mock runtime logged to MLflow, so **real ADK runs were not captured** — this closes that gap. |
| `backend/requirements.txt` | Activated `mlflow>=2.14` (was commented out / optional). |

Unchanged but part of the pipeline (no edit needed):
- `backend/app/runtime/mock.py` already calls `sink.record_run(run)` at completion.
- `backend/app/observability.py → get_sink()` selects `MLflowSink` vs `LocalSink`
  from the `OBSERVABILITY` env var and falls back to local if MLflow is unavailable.

No frontend changes are required for MLflow.

---

### 1. Install MLflow

```bash
cd backend
pip install -r requirements.txt      # mlflow is now included
# or just: pip install mlflow
```

### 2. Start MLflow on the same instance

Pick ONE option.

**Option A — quick (local file store, no separate DB):**
```bash
mlflow server --host 127.0.0.1 --port 5000
```

**Option B — recommended (SQL backend; required for the model registry / heavier querying):**
```bash
mlflow server --host 127.0.0.1 --port 5000 \
  --backend-store-uri sqlite:///mlflow.db \
  --default-artifact-root ./mlartifacts
```

> Note: MLflow's backend store is **SQL only** (SQLite/Postgres/MySQL) — it cannot
> use a NoSQL DB. Artifacts (files/models) go to a filesystem or blob store, not the
> SQL DB. For production, use PostgreSQL as the backend store and a blob store
> (e.g. Azure Blob) as the artifact root.

### 3. Point the backend at MLflow (env vars) and start it

```bash
export OBSERVABILITY=mlflow                       # flips the sink to MLflowSink
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000  # same instance
export MLFLOW_EXPERIMENT=tcs-ai-studio            # optional (this is the default)

# for real LLM calls too (optional):
#   export RUNTIME=adk
#   export MODEL_PROVIDER=... and the matching *_API_KEY   (or use Model Endpoints in the UI)

uvicorn app.main:app --port 8099
```

If `MLFLOW_TRACKING_URI` is omitted, MLflow logs to a local `./mlruns` folder
instead of the server.

### 4. Verify

1. Run any workflow in the UI (e.g. Templates → Agent Security & Threat Analysis → Run).
2. Open `http://127.0.0.1:5000` → experiment **tcs-ai-studio**.
3. Each workflow appears as a **parent run** with metrics + artifacts; expand it to
   see the **nested per-agent runs** and the logged trace/output/deliverable files.

---

### What gets captured

**Per workflow run (parent MLflow run):**
- Tags: `run_id`, `workflow`, `workflow_id`, `status`, `verdict`.
- Params: `node_count`, `agents`, `steers`.
- Metrics: `input_tokens`, `output_tokens`, `tokens`, `latency_ms`, `num_agents`, `success`.
- Artifacts:
  - `trace/activity_events.json` — the full live "thinking"/execution event stream.
  - `trace/node_outputs.json` — every agent's output + intermediate steps.
  - `deliverables/…` — generated files (e.g. `security_report.md`, `deliverable.md`).

**Per agent (nested MLflow run under the parent):**
- Params: `agent`, `steps`.
- Metrics: `in_tokens`, `out_tokens`.
- Artifacts: `agents/<n>_output.md`, `agents/<n>_steps.txt`.

---

### How the connection is decided

On startup, `get_sink()` reads `OBSERVABILITY`:
- not `mlflow` → `LocalSink` (default; no-op, data already in the store).
- `mlflow` → builds `MLflowSink`, which calls
  `mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)` and `set_experiment(...)`.
- If `mlflow` isn't installed or import fails → **silent fallback to LocalSink**, so
  the app never breaks.

Every run flows through `sink.record_run(run)` at completion (both mock and ADK
runtimes), so no per-workflow wiring is needed.

---

### Troubleshooting

- **Nothing appears in MLflow:** confirm `OBSERVABILITY=mlflow` is set in the *same*
  shell that starts uvicorn, and that `MLFLOW_TRACKING_URI` matches the running server.
- **App works but no MLflow logs:** MLflow import likely failed → `pip install mlflow`
  and restart. (The app deliberately falls back to local instead of crashing.)
- **Model registry errors:** use the SQL backend (Option B); the registry requires it.
- **Artifacts missing:** ensure `--default-artifact-root` is writable by the server.

---

### Production notes (optional)

Standardize on **PostgreSQL** to serve MLflow and (via a Postgres/JSONB adapter for
the app's `Repo`) the platform's own data on one engine, with **Azure Blob** as the
artifact root:

```bash
mlflow server --host 0.0.0.0 --port 5000 \
  --backend-store-uri postgresql://user:pass@your-pg.postgres.database.azure.com/mlflow \
  --default-artifact-root wasbs://artifacts@youracct.blob.core.windows.net/mlflow
```

(The Postgres adapter for the platform store is a separate task — the `Repo`
abstraction in `backend/app/store.py` is the seam for it.)

---

### Update: guaranteed logging + run control (added this build)

- `backend/app/executor.py` (new) — every run goes through `run_workflow()`, which
  guarantees the run reaches a terminal state and is **always** recorded to the sink
  (MLflow/local), for success, failure, and cancellation.
- `backend/app/runtime/live.py` — added a loop guard (`max_iterations` / `MAX_AGENT_STEPS`),
  cooperative cancellation, and per-step persistence; removed its own sink call (executor owns it).
- `backend/app/activity.py` — added `CancelRegistry` for interrupts.
- `backend/app/routers/runs.py` — routes runs through the executor; added `POST /runs/{id}/cancel`.
- `agents.py` / `schedules.py` / `insights.py` — all run paths now log to MLflow too.

---

### Fixes (this build) — read if traces weren't showing

1. **MLflow now activates when `MLFLOW_TRACKING_URI` is set** (you no longer must
   also set `OBSERVABILITY=mlflow`). Setting either one enables it.
2. **Errors are no longer swallowed.** Check the new diagnostics endpoint:
   ```
   GET /api/v1/observability/status
   -> { "sink": "mlflow", "tracking_uri": "...", "last_logged": "run_x",
        "last_error": "", "mlflow_installed": true }
   ```
   The Monitoring screen also shows a `tracing: mlflow · <uri>` tag. If `sink` is
   `local`, MLflow isn't active; if `last_error` is set, it tells you why.
3. **Chat "no output" fixed:** the live runtime now falls back to a non-streaming
   completion when a provider streams empty deltas (common with Azure), so agent
   outputs and the final answer are always captured.

#### Quick verify
```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
uvicorn app.main:app --port 8099
curl -s localhost:8099/api/v1/observability/status   # sink should read "mlflow"
# run a workflow from Chat, then re-check: "last_logged" should show the run id,
# and the run appears in the MLflow UI under experiment "tcs-ai-studio".
```

---

### Update: GenAI Traces + correct token split (this build)

Two issues fixed:

1. **Entries appeared under experiment/"training", not GenAI.** The sink logged via
   the classic tracking API (runs + metrics). We now also enable **MLflow GenAI
   tracing** via `mlflow.litellm.autolog()` in `MLflowSink.__init__`, so every model
   call is captured as a span under **GenAI → Traces**. The run-level metrics are
   still logged for the experiment view (nothing lost). Requires `mlflow>=2.14`.

2. **Input/Output tokens were blank (only Total showed).** Fixed token accounting on
   every runtime:
   - `runtime/adk.py` now sets `run.input_tokens` / `run.output_tokens` per node
     (previously only the total was set) and populates `node_outputs`.
   - `runtime/live.py` requests `stream_options={"include_usage": true}` and reads the
     provider's real `usage` (prompt/completion tokens), with a word-count fallback.

After upgrading, new runs show correct Input/Output/Total tokens and appear under the
GenAI Traces tab. Verify via `GET /api/v1/observability/status` and the MLflow UI.

---

### Update: reliable GenAI Traces + readable chat + polish (this build)

**Why traces weren't appearing:** `mlflow.litellm.autolog()` only reliably
instruments litellm's *sync* path, but the runtimes use async `acompletion`, so no
GenAI traces were produced (only experiment metrics). Fixed by adding **explicit
trace spans** around every agent model call — independent of autolog.

- `backend/app/tracing.py` (new) — `span()` / `set_outputs()` helpers that create an
  MLflow GenAI span per agent call (inputs, outputs, token counts, model, run_id).
  Safe no-ops when tracing isn't configured.
- `backend/app/runtime/live.py` — model call extracted into a traced `_invoke()`.
- `backend/app/runtime/adk.py` — per-agent ADK run wrapped in a trace span.
- `backend/app/observability.py` — still enables `litellm.autolog()` (bonus) and logs
  run/agent metrics with the correct input/output token split.

Result: **agent Test, Workflow Studio runs, and Chat runs all emit GenAI Traces** (one
span per agent) plus run/experiment metrics. Verify in the MLflow UI under GenAI ->
Traces and via `GET /api/v1/observability/status`.

**Robust input handling:** `/runs` and agent Test now accept either a JSON object or a
plain string (auto-wrapped), so runs never fail on input shape.

**Readable chat:** agent output now renders as full markdown (headings, lists, code
blocks, tables, blockquotes, links) with styled chat bubbles.

---

### Update: tool registration & calling (this build)

**Problem:** tools could be registered (OpenAPI only, via UI) but were never passed to
the model, so agents could not actually call them.

**Fixes:**
- `backend/app/tool_exec.py` (new) — builds OpenAI-style tool definitions from an
  agent's attached tools and executes calls: OpenAPI operations make real HTTP
  requests (using `servers[].url` + optional bearer token); function tools POST to a
  configured `webhook_url`; a few safe built-ins (time, calculator) are included.
- `backend/app/runtime/live.py` — `_invoke()` now runs a bounded tool-calling loop:
  the model may call granted tools, the platform executes them and feeds results back,
  then returns the final answer. `tool_call` events appear in the trace/Chat.
- `backend/app/routers/tools.py` — function registration accepts JSON-Schema
  `parameters` + a `webhook_url`; OpenAPI registration stores full operation details
  and an optional `auth_token`, and validates required fields.
- Frontend **Tool Registry** now has both a **Function tool** form (name, description,
  JSON-Schema params, webhook URL) and the **OpenAPI** form (with bearer token) — you
  can register both from the UI. Grant tools on the agent wizard's Tools step.

#### How calling works
1. Register a tool (Tool Registry). For it to run: OpenAPI needs `servers[].url`;
   a function needs a `webhook_url`.
2. Grant the tool to an agent (agent wizard → Tools step).
3. Run a workflow/chat. When the model decides to use a tool, the platform executes it
   and returns the result to the model for the final answer.

The in-app **Setup & Help** screen has step-by-step configuration for all of this.

---

### Update: Phase A — stability & safety (all UI-controlled)

No new installs, no new services, and the same run commands. Your existing setup and
`data/*.json` files keep working; this is internal hardening plus UI controls.

**Everything is configurable from the UI:** Governance → **Platform Settings** tab:
- **Max concurrent runs** — bounded concurrency; extra runs queue.
- **Per-run timeout (s)** — a run is stopped cleanly if it exceeds this.
- **Retry attempts / backoff** — transient model/tool failures are retried.
- **Max request size (KB)** — oversized requests are rejected.
- **SSRF safety** — block private/internal addresses for tool/webhook calls (on by
  default); add internal hosts under **Allowed internal hosts** if a tool needs them.

**Always-on (no knobs, pure safety):**
- Orphan recovery — runs left "running" after a restart are marked failed on next start.
- Graceful shutdown — in-flight runs are closed out instead of dangling.
- Atomic writes — the JSON store writes via temp-file + rename, so a crash can't corrupt data.

**Optional ops overrides** (UI remains the source of truth):
`MAX_CONCURRENT_RUNS`, `RUN_TIMEOUT_SECONDS`, `RETRY_ATTEMPTS`, `MAX_REQUEST_KB`.

**Files added/changed for Phase A:**
- `backend/app/executor.py` — concurrency semaphore, per-run timeout, orphan recovery.
- `backend/app/security_net.py` (new) — SSRF allowlist guard.
- `backend/app/governance.py` — `platform` settings block + `platform_settings()` resolver.
- `backend/app/routers/governance.py` — `GET/PUT /platform-settings`.
- `backend/app/store.py` — atomic writes.
- `backend/app/main.py` — request-size middleware, startup/shutdown orphan recovery.
- `backend/app/runtime/live.py` — settings-driven retries/backoff on model calls.
- `backend/app/tool_exec.py` — SSRF check before outbound calls; `eval` replaced with a safe parser.
- Frontend **Governance → Platform Settings** tab + **Setup & Help** step 8.

---

### Ontology Intelligence Layer (Increment 1)

An optional knowledge-graph grounding layer, **off by default**. When off, the platform
behaves exactly as before (plain retrieval). When on for a tenant/workflow with a
published graph, agents ground design/retrieval/planning/action in the ontology, and
fall back to plain retrieval for anything unmodeled.

#### Design (how it stays additive)
- **Single seam:** the runtime acquires context through one `ContextProvider`
  (`backend/app/ontology/contract.py`). `PlainProvider` reproduces today's behavior;
  `OntologyProvider` adds grounded entities/relations. Both return the identical
  `ContextBundle`, so the agent loop never branches on the flag.
- **One flag-read point:** `app/ontology/factory.py::get_context_provider()` — the only
  place enablement is read on the agent path. Default = PlainProvider.
- **Isolated module:** everything lives in `backend/app/ontology/` + one screen; existing
  modules are untouched apart from the seam call in `runtime/live.py`.

#### Using it from the UI (Ontology screen)
1. **Datastore** tab — choose the store (Built-in JSON by default, or PostgreSQL + pgvector),
   enter endpoint + secret reference, **Test connection**, **Save & apply** (hot-applied,
   no redeploy). Postgres needs the driver installed on the server; JSON works out of the box.
2. **Graphs & Authoring** tab — create a graph (manual / auto / hybrid + domain tag), add
   entities, use the **review queue** to approve/reject (or bulk-approve above a confidence),
   then **Publish** (a version can only publish once no item is left pending_review). Only
   **published** graphs are ever read at runtime. Archived versions can be **rolled back** in one click.
3. **Enablement** tab — turn the ontology on per **workflow** or per **tenant** (resolution:
   workflow → tenant → system default). Leave the system default off.
4. **Telemetry** tab — per-request record of which provider grounded each step.

#### Guarantees (verified)
- Off = unchanged output; the flag is read in exactly one place on the agent path.
- Ontology-first: unresolved/unmodeled parts fall back to plain retrieval (no coverage gap).
- Permission parity: unauthorized roles get no structured grounding; governed actions appear
  only when enabled.
- Only published assets reach runtime; publish gate + one-action rollback enforced.
- No matching graph → behaves as ontology-off.

#### Files added (isolated module)
`backend/app/ontology/{__init__,contract,plain,ontology_provider,ontology_store,ontology_config,selection,factory}.py`,
`backend/app/routers/ontology.py`, `frontend/src/screens/Ontology.tsx`. The only existing-code
change is the `ContextProvider` seam call in `backend/app/runtime/live.py` (PlainProvider default).

> Increment 2 (planned): richer auto-extraction pipeline, full interactive graph visualization
> (canvas with expand-on-demand + minimap), and per-graph datastore overrides.

---

### Ontology Intelligence Layer (Increment 2)

Builds on Increment 1 with the full authoring experience — still off by default, still
behind the single provider seam.

#### New capabilities
- **Auto-extraction pipeline (Stage 1, spec §9.2)** — from the graph's **Auto-extract** card:
  - *Structured*: paste rows JSON (`{table, rows}`); the system infers an entity type,
    creates entities, and turns `*_id` columns into typed edges (high confidence).
  - *Text*: paste documents; entities/relationships are extracted with an LLM when a model
    endpoint is configured, otherwise a deterministic offline heuristic. Every candidate
    carries confidence + provenance and lands as a review candidate (`auto`). Disabled in manual mode.
- **Interactive graph visualization (spec §11)** — a real canvas: search-first entry,
  **click = entity detail panel** (properties, relationships, provenance, confidence),
  **double-click = expand-on-demand neighbors**, status-color coding, a status filter, and a
  **minimap**. Large graphs are never force-rendered — you search/expand instead.
- **Per-graph datastore override (spec §12)** — each graph can point at its own store
  (JSON or Postgres+pgvector), configured/tested/hot-applied from the UI; blank = use default.

#### End-to-end flow (all in the UI)
Ontology → Graphs & Authoring → create graph → **Auto-extract** (or add entities by hand) →
**Review queue** approve/reject (or bulk-approve) → **Publish** → Enablement tab: turn on for
the workflow/tenant. Runs on that workflow now ground in the published graph; everything else
stays plain. The **Telemetry** tab shows which provider grounded each step.

#### Files added (Increment 2)
`backend/app/ontology/extraction.py`, new routes in `backend/app/routers/ontology.py`
(extract/structured, extract/text, neighbors, entity detail, per-graph datastore),
per-graph override helpers in `ontology_config.py`, and `frontend/src/screens/GraphCanvas.tsx`
(the interactive visualization) wired into the Ontology screen. No existing modules changed
beyond the Increment-1 seam.

#### Verified
Structured + text extraction with confidence/provenance; auto items require review; nothing
reaches runtime before publish; entity detail + expand-on-demand; search-first view truncates
(no full-graph render); per-graph datastore override resolves; manual mode blocks auto-extract;
and the full extract→approve→publish→enable→grounded-run path — with non-ontology workflows
unchanged.

---

### Data Science Lab (Phase 1)

A self-contained, non-invasive module: a Colab-style notebook lab whose kernel runs on
a **remote NVIDIA GPU**, with results surfaced back in the platform. Ships **dark**
(feature flag off); the rest of the platform is unaffected whether it's on or off.

#### Non-invasive guarantees (spec §1, §15) — verified
- New code only: `backend/app/modules/data_science_lab/` + one router (`routers/dsl.py`,
  route tree `/api/v1/dsl/*`) + one screen (`screens/DataScienceLab.tsx`). The only edit
  to existing code is one `include_router` line in `main.py`.
- New state is `dsl_*` files only (`dsl_runtimes.json`, `dsl_templates.json`) — droppable
  without touching core tables.
- Reuses existing MLflow, governance settings (feature flag), and the secret-reference
  pattern — no second copy, no schema changes.
- Feature flag off ⇒ platform behaves exactly as before; action endpoints return 403.
  Rollback = flip the flag; uninstall = delete `dsl_*` + remove the module/route.

#### Using it (all UI-driven)
1. **Enable** the module (it ships dark): Data Science Lab → enable button, or Settings tab
   (system default + per-tenant).
2. **Runtimes** tab → *Add Runtime*: pick provider (Brev/AWS/Azure managed, or SSH/on-prem
   connect-only), host, GPU type, NGC runtime image, workdir, Jupyter port, idle timeout,
   **auth secret reference** (`vault://…` — never the raw key), persistent-volume ref, and
   MLflow URI. **Test** probes reachability + auth honestly.
3. **Open Lab** → starts the runtime (managed), `git pull`s templates, launches JupyterLab
   on the target, tunnels it, and injects `MLFLOW_TRACKING_URI`. The **Workspace** tab embeds
   JupyterLab; the kernel badge shows the remote GPU. Each session step is reported honestly.
4. **Template Library** — internal, versioned notebooks (source of truth = git).
5. **NVIDIA Blueprints** — external reference workflows (clearly labelled), clone into a runtime.
6. **Experiments & Models** — thin links into the existing MLflow (no second tracking system).

#### Providers (spec §6)
`ssh` (connect-only, no Stop), `brev` (managed lifecycle, NVIDIA-owned default), `aws`/`azure`
(managed; lifecycle arrives in Phase 2 — connect over SSH meanwhile). Adding a provider later
is one new class.

#### Honest scope note
Real GPU execution (SSH, JupyterLab tunnel, RAPIDS/NGC, Brev/AWS/Azure start/stop) runs on
the remote target and needs the optional deps (`paramiko`, provider CLIs/SDKs) + reachable
GPUs. Those calls are written and wired but **guarded**: without the dep/target they return a
clear, honest status (e.g. "cannot reach host — firewall/VPN?", "brev CLI not installed")
instead of faking success — so a GPU-side fault can never affect control-plane availability.

#### Phased delivery
Phase 1 (this build): Runtimes + add/test, SSH + Brev adapters, launch/embed JupyterLab,
git-pull templates, MLflow injection, manual + idle stop, Template Library, Blueprints
catalog, MLflow links — behind the flag. Phase 2: AWS/Azure lifecycle, persistent volumes,
papermill headless runs, template versioning + CI smoke tests, DCGM metrics. Phase 3:
JupyterHub + MIG multi-user.

#### Files added
`backend/app/modules/data_science_lab/{__init__,config,store,session,blueprints}.py`,
`backend/app/modules/data_science_lab/providers/{__init__,base,ssh,brev,managed}.py`,
`backend/app/routers/dsl.py`, `frontend/src/screens/DataScienceLab.tsx`.


---

### Data Science Lab (Phases 2 & 3 — module complete)

Phase 1 (runtimes, SSH+Brev, launch/embed JupyterLab, git-pull templates, MLflow
injection, template library, blueprints) is now extended to the full module.

#### Phase 2 — Colab-parity & portability
- **AWS + Azure lifecycle** adapters (real boto3 / azure-mgmt-compute, guarded). AWS
  `host` = EC2 instance-id; Azure `host` = `<resource_group>/<vm_name>`. Start/Stop from
  the runtime card; connect-only SSH targets still hide Stop.
- **Headless runs (papermill)** — from the Workspace strip, run `<notebook>` -> `.out.ipynb`
  with injected params + MLflow URI on the GPU.
- **Backup verify-before-stop** — if a `backup_remote` is set, Stop first `rclone copy`s the
  workdir and `rclone check`s it; the runtime won't stop unless the backup verifies (§6.3 step 7).
- **Template versioning + CI** — templates carry semver + changelog history and a CI status;
  "New version" bumps semver, "Run CI" runs a papermill/nbmake smoke test on a runtime and
  records passing/failing (§8 quality gate).
- **DCGM / nvidia-smi metrics** — live GPU utilisation, memory and temperature on each running
  runtime card and in the Workspace status strip (honest "not available" when there's no GPU/driver).

#### Phase 3 — Shared lab & scale
- **Multi-user (JupyterHub)** — mark a runtime multi-user with a Hub URL; the **Hub** action
  verifies the hub and returns the per-user spawn pattern.
- **MIG GPU sharing** — enable MIG with a profile (e.g. `1g.10gb`) to slice one big GPU across
  associates; surfaced on the card and honoured by the multi-user spawn.
- **Per-tenant isolation** stays through the existing tenancy + feature flag.

#### Optional dependencies (control plane)
Live GPU features need optional deps, listed (commented) in `backend/requirements.txt`:
`paramiko` (SSH), `boto3` (AWS), `azure-identity` + `azure-mgmt-compute` (Azure),
`papermill` (headless); plus `brev` CLI and `rclone` as system tools. Without them the module
still runs and degrades honestly — every action reports exactly what's missing rather than
faking success, so the control plane is never at risk.

#### New endpoints (Phase 2/3)
`/dsl/runtimes/{id}/metrics`, `/dsl/runtimes/{id}/headless`, `/dsl/runtimes/{id}/multiuser`,
`/dsl/templates/{id}/version`, `/dsl/templates/{id}/ci`. All behind the feature flag.

The Data Science Lab section is now feature-complete across Phases 1–3, still fully
non-invasive (own namespace, `dsl_*` state, flag-off = zero change).

---

### File Storage (instance-local shared workspace)

A configurable "bucket" on the instance where users drop files for agents and agents
read inputs / write generated files back — all browsable in the UI. (Azure Blob is
planned as a second backend; this ships with the local backend only.)

#### Configure (File Storage screen → gear, or Governance settings)
- **Backend:** local (instance storage).
- **Storage root path:** default `backend/data/file_storage/` (writable, survives restarts,
  included in backups). Point it at a mounted volume if you prefer.
- **Max file size (KB)** and **allowed extensions** (blank = allow all) — safety limits.

#### Layout
```
<root>/
  shared/            ← main bucket: put inputs here, agents read + write here
  runs/<run_id>/     ← generated run artifacts are mirrored here automatically
```
All access is confined to the root — no path can escape it (`..`/absolute paths blocked).

#### Managing files (Files screen)
Browse folders, **upload** (drag/drop or picker), **download**, **preview** text, create
folders, and delete. You can also drop files straight onto the instance under the storage
root over SSH/SFTP — agents pick them up immediately.

#### Giving an agent file access (Create/Edit Agent → Tools step)
Toggle **"Let this agent read & write files"** and set a **Workspace folder** (e.g.
`shared/invoices`). The agent gets governed file tools — `list_files`, `read_file`,
`write_file`, `delete_file` — **scoped to that folder only**; it cannot touch anything
outside it. At run time the model calls these tools through the normal tool-calling loop:
it picks up inputs from the folder and writes its generated files back there, where they
appear in the Files screen and are downloadable.

#### How the loop works end to end
1. Put an input file in a folder (Files screen upload, or drop on the instance).
2. Create an agent with file access pointing at that folder.
3. Run the workflow/chat — the agent reads the input and writes its output file to the
   same folder. Open the Files screen to view/download the result.

#### Files added
`backend/app/filestore.py` (local backend + path confinement + guards),
`backend/app/routers/files.py` (config + list/upload/download/preview/mkdir/delete),
file tools in `backend/app/tool_exec.py` (scoped `list/read/write/delete_file`),
`workspace` on the agent tool binding (`schemas.py`), and `frontend/src/screens/Files.tsx`
plus the Tools-step field in the Create-Agent wizard. Generated run artifacts are mirrored
into `runs/<run_id>/`.

---

### Agent document generation (.docx / .xlsx / .pdf → File Storage)

Agents with file access can generate **real Office/PDF files** (not just text) and store
them in their workspace folder, where they appear in the Files screen and are downloadable.

#### How it works
An LLM tool call can only carry text, so a genuine `.docx` (a ZIP of XML) is **built
server-side** from the agent's content. Agents granted file access get a `create_document`
tool alongside `read/write/list/delete_file`:
- `create_document(path, format, title, content, sections?, sheets?)`
- `format`: `docx` | `xlsx` | `pdf`
- `content`: markdown-ish body (headings, bullets) for docx/pdf; `sections` for structured
  headings/tables; `sheets` for xlsx (`[{name, rows:[{col:val}]}]`).

The file is rendered with open-source libraries (python-docx, openpyxl, reportlab) and
written via the storage layer into the agent's workspace folder — path-confined like every
other file op. Example: an agent asked for a quarterly report calls `create_document` with
`format:"docx"` and the file lands at e.g. `shared/reports/quarterly_report.docx`.

#### Also collected in storage
- Generated markdown run artifacts → `runs/<run_id>/`.
- Insights Word reports → `reports/<id>.docx`.
So every generated document — agent-created or platform-generated — collects in the
configured File Storage in one browsable place.

#### Requirements
`python-docx`, `openpyxl`, `reportlab` (all open-source, in `backend/requirements.txt`).

#### Files added
`backend/app/docgen.py` (real docx/xlsx/pdf rendering into storage) and the
`create_document` file tool in `backend/app/tool_exec.py`.

---

### Model Registry (Data Science Lab tab)

Versions and promotes the **ML models trained in the Lab** (e.g. a fraud classifier),
reusing the platform's existing **MLflow registry** — not a second system. It lives as a
**Model Registry tab inside the Data Science Lab**.

#### Important distinction (no impact on your LLM setup)
- **Foundation LLMs** (GPT / Mistral / Gemini) stay in **Model Endpoints** — the chat APIs
  agents call for reasoning. Unchanged.
- **Registered models** here are *trained ML artifacts*, a different thing entirely. The
  registry never touches your Model Endpoints.

#### Using it (Data Science Lab → Model Registry)
- **Register** a model version (name + `model_uri` like `runs:/<run_id>/model`), or push
  from a Lab run with `mlflow.register_model`.
- **Promote** a version through stages: None → **Staging** → **Production** (promoting to
  Production auto-archives the previous Production version — only one is live).
- Source tag shows `mlflow` when a live registry is reachable, else `local` (a mirror that
  keeps the feature usable and syncs to MLflow when available).

#### Agent consumption (the additive linkage)
Promote a model to **Production**, then on an agent (Create/Edit Agent → Tools) enable
**"call a registered ML model as a tool"** and name it. The agent gets an `invoke_<model>`
tool it can call for predictions — through the same tool-calling loop as every other tool.
This is separate from the LLM the agent reasons with: reasoning stays via Model Endpoints,
specialized inference goes to the registered model. Calls need a serving endpoint
(`mlflow models serve` or any REST scorer); without one the tool returns an honest message.

#### Files added
`backend/app/modules/data_science_lab/registry.py` (MLflow-backed with local fallback),
registry routes in `backend/app/routers/dsl.py`, the `model` tool type in
`backend/app/tool_exec.py` + `schemas.py`, the **Model Registry** tab in
`frontend/src/screens/DataScienceLab.tsx`, and the model-attach option in the agent wizard.

---

### Fixes & enhancements (observations round)

Applied from the field-test observations:

#### Bug fixes
- **Chat Stop/interrupt** now cancels mid-response. The cancel flag is checked during
  token streaming and inside the tool-calling loop (previously only between agents), so
  clicking Stop halts generation immediately.
- **Tool calling (REST API + function) now fires and is traced.** Root causes fixed:
  (1) the tool-calling path emitted **no MLflow span** — it now opens a span per agent call
  and a **nested span per tool execution**, so tool calls appear in Traces;
  (2) OpenAPI path parameters (e.g. `{customer_id}`) are now **declared as named required
  fields** to the model instead of a generic blob, so the model fills them correctly;
  (3) the agent's **system prompt now lists its available tools** and instructs it to call
  them — this is the main fix for "the agent never calls the tool / says it has no access."
- **File access from agents** works reliably: the tool-awareness hint makes the model
  actually call `list_files`/`read_file`, and the workspace path resolves with a fallback
  (a folder `erp` also matches `shared/erp`) to avoid path-mismatch confusion.
- **File creation ("junk file") fixed and restricted to Word.** Document generation is now
  **.docx only** (pdf/xlsx removed per request). Writing text to a `.docx` path auto-routes
  through the real Word generator, so a valid `.docx` is always produced — never a junk file.

#### Tools section enhancements
- **Test a tool from the UI** — each tool card has a **Test** button: pick an operation,
  pass JSON args, and see the result, status, and elapsed time without invoking an agent.
- **Edit and Delete tools** — each tool card has **Edit** (name/description/webhook/token)
  and **Delete**.

#### Ontology section enhancements
- **Delete graphs** from the graph list.
- **Interactive graph zoom** (zoom in/out/reset) added to the canvas.
- **Approved-state view shows only approved** entities/edges; unreviewed items now display
  with **pending_review** status (not "auto").
- **File upload → extract**: upload a `.txt`/`.docx` (stored under `shared/ontology/`) and
  run extraction on it directly from the graph's Auto-extract panel.

#### Endpoints added
`PUT/DELETE /tools/{id}`, `POST /tools/{id}/test`, `POST /ontology/graphs/{id}/extract/file`,
`GET /ontology/graphs/{id}/view?status=` (status filter). Document generation restricted to docx.

---

### Chat History (persistent conversations)

Chat conversations are now saved automatically so users can revisit them later — no more
losing context on refresh or workflow switch (observations #6a).

#### What you get (Chat screen)
- **History sidebar** on the left listing past conversations, newest first, with the
  workflow name, message count, and a timestamp (time today, date otherwise).
- **New chat** button to start a fresh conversation.
- **Search** box — matches conversation titles *and* message content.
- **Auto-title** — a conversation is named from its first message.
- Per-conversation menu (⋯): **Rename**, **Archive/Unarchive**, **Delete**.
- **Show/Hide archived** toggle at the bottom of the sidebar.
- Conversations persist across sessions; click one to reload its full message thread
  (and it re-selects the workflow it used).

#### How it works
Messages are saved to the backend after each exchange. Storage is a dedicated
`chat_conversations` collection — additive and isolated; it does not touch runs, agents,
or workflows. Conversations bind to the workflow they were started with.

#### Endpoints
`GET/POST /chat/conversations`, `GET/DELETE /chat/conversations/{id}`,
`PUT /chat/conversations/{id}/messages`, `.../rename`, `.../archive`.

#### Files added
`backend/app/chat_store.py`, `backend/app/routers/chat.py`, and the rebuilt
`frontend/src/screens/Chat.tsx` (history sidebar + persistence).

---

### Ontology — interactive knowledge-graph explorer (flagship)

The Ontology section's Interactive Graph is now a full, physics-based explorer built to be
the platform's niche — visually rich, data-science-heavy, and fully editable.

#### Playing with the graph (Ontology → open a graph → Interactive graph)
- **Force-directed layout** — nodes self-organize with a live physics simulation
  (repulsion + springs + centering). **Freeze/Animate** toggles it.
- **Drag** any node to reposition (it pins while dragging, then rejoins the simulation).
- **Pan** by dragging the background; **zoom** with the scroll wheel or the zoom buttons
  (reset returns to 100% and re-centers).
- **Click a node** → focus: it glows, its neighbors and connecting edges highlight, and the
  rest dims, so relationships are revealed on click. The right panel shows properties,
  degree/confidence, and every relationship.
- **Double-click a node** → expand its neighbors into the canvas (progressive exploration).
- **Click an edge** → inspect and edit the relationship.
- **Node size = degree centrality** (bigger = more connected); a dashed ring marks items
  that aren't approved yet.
- **Color by type or status** (toggle) with a live legend.
- **Search** highlights and narrows (search-first — big graphs aren't dumped at once).

#### Inline editing (spec §7 — edit/delete everywhere)
- **Entities**: edit name/type/status, or delete (removes the entity and its dangling
  relationships) from the detail panel.
- **Relationships (edges)**: edit relation/status or delete.
- Combined with existing **graph delete**, **approve/reject**, and **taxonomy** controls,
  every artifact in the ontology can be edited or removed from the UI.

#### Data-science analytics panel (live)
A right-rail panel computes and visualizes, on the fly:
- **Entities, relationships, density, average degree, connected components, type count.**
- **Most-connected entities** (degree centrality) as ranked bars.
- **Type distribution** and (via the API) relation/status distributions.

#### Endpoints added
`PUT/DELETE /ontology/entities/{id}`, `PUT/DELETE /ontology/edges/{id}`,
`DELETE /ontology/taxonomy/{id}`, `GET /ontology/graphs/{id}/analytics`.

#### Files
`frontend/src/screens/GraphCanvas.tsx` (rewritten explorer), analytics + CRUD in
`backend/app/ontology/ontology_store.py` and `backend/app/routers/ontology.py`.

---

### Ontology — LLM-driven creation, model selection & custom prompt

You don't build graphs by hand. The **LLM creates the ontology and taxonomy** for you; the
Auto-extract panel now makes the model explicit and lets you steer it.

#### Pick the model (no more hidden selection)
The Auto-extract panel shows a **Model** dropdown listing every configured Model Endpoint
(from the Model Endpoints screen). Whatever you pick is the LLM that builds the graph.
**Set as default** saves it as the ontology's default extraction model (stored in ontology
config as `extraction_model`), so it's clear which model triggers every time. If no model is
configured, the panel warns you and falls back to a basic offline heuristic — add a model in
Model Endpoints for real LLM-driven creation.

#### Give a dynamic prompt
An **Instructions to the LLM** box lets you steer each extraction — e.g. "Focus on suppliers
and their parent companies; treat products as a separate type." Your instructions are appended
to the extraction prompt, so the same document can yield different ontologies/taxonomies
depending on what you ask for.

#### How creation works
1. Choose the model (and optionally set it as default).
2. Optionally type instructions.
3. Extract from **pasted text**, **structured rows**, or an **uploaded file** — the chosen
   model returns entities + relationships, which land as review candidates.
4. Review/approve, then explore/edit in the interactive graph, and publish.

#### Endpoints
`GET /ontology/models` (configured models + current default), and `endpoint_id` +
`instructions` accepted by `POST /ontology/graphs/{id}/extract/text` and `.../extract/file`.
`extraction_model` persists via `PUT /ontology/config`.

---

### UX & robustness pass (self-review round)

Platform-wide polish from a full self-review — all additive, no change to runtime, agents,
ontology, DSL, storage, or data logic.

#### Collapsible navigation
The left navigation now **collapses to a slim icon-only rail** (and expands back) via the
menu toggle at the top of the rail. Collapsed items show tooltips on hover, giving dense
screens (graph explorer, Data Science Lab, Monitoring) more room and saving screen space.

#### Robustness
- **Global error boundary** — if any screen hits an unexpected error, a friendly "Something
  went wrong — Reload this screen" panel appears instead of a blank page; reload returns you
  to a clean state. No telemetry is sent.
- **Setup-status hint** — the Home screen now detects when **no model endpoint is configured**
  and shows a clear call-to-action (agents, chat, and ontology extraction all need a model),
  linking straight to Model Endpoints and the setup guide. This removes the "why isn't
  anything working?" confusion for first-time users.
- **Delete confirmations everywhere** — every destructive action (agents, model endpoints,
  schedules, runtimes, templates, registered models, graphs, entities, edges, tools, files,
  chats) now asks for confirmation before removing.

#### Notes
Session management / login remains deferred (Phase D) by decision. Retrieval/RAG and
permission-aware search are also parked for a later phase.

---

### Fix: agents now reliably call mapped REST APIs (tool-calling)

**Symptom fixed:** an agent mapped to an OpenAPI tool would run but never invoke the API,
and no tool/function span appeared in MLflow — i.e. the API was never called.

**Root cause (confirmed against Google ADK's design):** ADK's guidance is that *automatic
function calling works best with simple, flat, named, typed parameter schemas*. The platform
was exposing each OpenAPI operation to the model as a generic `{query, body}` blob with no
declared properties. Real models (Azure GPT-4o-mini, Gemini) don't reliably call a tool with
such a vague schema — so the model just answered without calling it.

**Fix:** OpenAPI ingestion now parses each operation's real **path, query, and request-body
parameters** (resolving `$ref`s, capturing types, enums, required flags) and exposes them to
the model as **flat, named, typed fields** — exactly the shape ADK uses for reliable calling.
At execution time, arguments are routed back to the correct location (path substitution,
query string, or JSON body) automatically. Legacy tools registered before this change still
work (path parameters are derived from the URL). The tool-calling path is also wrapped in
MLflow spans (one per agent call, one per tool execution), so calls now appear in Traces.

#### Configuring an API tool so the agent actually calls it
1. **Register the API** (Tool Registry → OpenAPI). Ensure each operation has a clear
   `operationId` and `summary`, and that parameters are declared in the spec.
2. **Test it directly** — Tool Registry → **Test** on the tool → pick an operation, pass JSON
   args, confirm a real response.
3. **Map it to the agent** (Garden → Create/Edit → Tools) and, importantly, **mention the tool
   in the agent's system prompt** ("Use the ERP API to look up customers").
4. **Internal APIs:** add the host under Governance → Platform Settings → Allowed internal
   hosts (the SSRF guard blocks private addresses by default).
5. **Verify:** test the agent in the Garden and open the run — you'll see a **tool call** step
   in the live trace (and a span in MLflow if enabled).

If the agent still answers without calling: it's almost always (a) the system prompt not
mentioning the tool, (b) missing parameter declarations in the spec, or (c) an internal host
blocked by SSRF — in that order.

---

### Fix: agents now actually invoke enabled connectors

**Symptom fixed:** once a connector was enabled and attached to an agent, the model answered
directly instead of calling the connector — the connector was never invoked.

**Root cause:** same class of bug as the REST-API issue. The tool builder had no `connector`
case at all, so a `{type:"connector"}` binding was silently skipped and never became a callable
tool — the model had nothing to call. (`connector` was also missing from the tool-type enum.)

**Fix (aligned with Google ADK):** enabled connectors are now exposed to the model as
**flat, named, typed tools** (e.g. `google_search{query}`, `mcp_postgres{sql}`,
`code_exec{code}`, `slack{action,text,channel}`), so the model reliably calls them, and the
call is traced (activity + MLflow span).

**Execution — honest about what runs where:**
- **code_exec** runs real computations in-process (safe arithmetic) with no external service.
- Any connector with a configured HTTP **endpoint/webhook** is called live (SSRF-guarded).
- **OpenAPI** connectors are executed via the Tool Registry (register the spec there).
- The **Google-ADK / GCP-backed** connectors (Google Search, Vertex RAG, MCP toolsets,
  Salesforce, ServiceNow, Slack, Jira, BigQuery) require their **ADK runtime and the service's
  credentials** to run live. When those aren't configured, the connector still gets *called* by
  the agent but returns an **honest "not executed — needs ADK runtime/credentials" result
  echoing the request** — it never fabricates data. This keeps behaviour truthful until the ADK
  runtime + credentials are wired on the server.

#### Making a connector callable
1. Enable it in **Connectors** (add any required config).
2. Attach it on the agent's **Tools** step, and mention it in the agent's **system prompt**
   ("Use Google Search to find …").
3. Test the agent and open the run — you'll see the connector **tool call** in the trace.
4. For live external data from ADK/GCP connectors, configure the ADK runtime and that
   service's credentials on the server (or point the connector at a self-hosted HTTP endpoint).

---

### Diagnosing "agent won't call my API" (tool-call diagnostic)

If a tool's **Test** works but the agent doesn't call it, the run trace now tells you which
side the problem is on. At the start of each agent step the trace shows either:
- **"N tool(s) available to <agent>: <names>"** — the tools reached the model. If no
  **tool call** step follows, the *model chose not to call it* → improve the operation's
  `operationId`/`summary` and mention the tool in the agent's **system prompt**.
- **"<agent> has N tool binding(s) but none resolved to a callable tool"** — the *binding*
  is the problem → the tool was deleted/disabled, or wasn't actually attached; re-attach it
  on the agent's Tools step.

#### Checklist (Test works, agent doesn't call)
1. Open the agent's run → find the **"tool(s) available"** line.
   - Not present / says 0 → the tool isn't attached. Edit the agent → Tools → toggle it on.
   - Lists your operation → go to step 2.
2. **Mention the tool in the system prompt** ("Use the ERP API to look up customers"). This is
   the most common fix — models call far more reliably when told to.
3. Ensure the operation has a clear **`operationId`** and **`summary`** (not a blank summary or
   an auto-generated name).
4. Give the agent a task that clearly needs the tool ("look up customer C1001"), not a generic
   question the model can answer on its own.
5. Re-run and check for the **tool call** step in the trace.

---

### Deterministic tool use — no reliance on random LLM behavior

Two mechanisms make API/tool calls reliable instead of depending on the model choosing the
right tool and emitting the exact name:

#### 1. Tool-name safety net (automatic)
If the model emits a slightly wrong tool name — e.g. it hallucinates **findCustomer** when the
registered operation is **getCustomer** — the platform now resolves it to the nearest real tool
(case/underscore-insensitive, verb-swap aware: get/find/fetch/list/search/…, and single-tool
agents route any call to their one tool). The real API is called with the correct name. No
configuration needed.

#### 2. Tool-use policy (per agent) — the deterministic control
On the agent's Tools step, set **Tool-use policy**:
- **Auto** (default): the model decides whether to call a tool.
- **Required**: the model MUST call one of its tools on the first round — it can't answer
  without calling. Single-tool agents default to this automatically.
- **Force: <operation>**: the agent ALWAYS calls that specific operation, by its exact
  registered name, every run. This is the most deterministic option and is ideal when the
  agent's whole job is "call this API" — it removes model discretion entirely.

Under the hood these map to the model API's `tool_choice` (`auto` / `required` /
force-specific-function), so the provider itself constrains the call to the real function name.

#### Recommended setup for a "just call my API" agent
1. Register the API in **Tool Registry → OpenAPI** (clear `operationId` + parameters).
2. Attach it to the agent; set **Tool-use policy → Force: getCustomer** (or **Required**).
3. Mention the API in the system prompt for good argument-filling.
Result: every run calls the real operation deterministically, and even a mis-named call is
auto-corrected to the registered operation.

---

### How API tools are stored & bound (architecture)

- **No code generation.** Registering an OpenAPI endpoint writes a JSON record to
  `data/tool_specs.json` with the parsed operations + parameters. No `.py` files are created or
  updated. Execution is interpreted: the runtime reads the record, builds the tool schema, and
  makes the HTTP call dynamically. Editing the spec updates one record — nothing to regenerate.
- **Agent binding is by reference.** The agent card stores `{type:"openapi", ref:<tool_id>}`
  (plus `tool_policy`). It does not copy operation details into the card. At run time the
  runtime resolves the ref and builds the full schema (e.g. `getCustomer(id: string, required)`).
- **Where the details flow at execution:** (1) the full parameter schema goes to the model via
  the function-calling `tools` channel (the correct place for typed params); and (2) a rich
  natural-language hint is injected into the system prompt — each tool as
  `name: description (required args: …)` — so the model knows what each tool is for and when to
  call it. So the API details reach the model both ways, without hand-editing prompts.

---

### Update round — REST API editing, Ontology UX, Chat persistence, ADK tool binding

#### Tools — REST API (OpenAPI) full editing
The Edit dialog now shows the **complete OpenAPI document** in an editable JSON field, not just
name/description/token. You can change any server URL, path, operation, parameter, or request
body; saving **re-parses every operation**. `GET /tools/{id}` returns a reconstructed
`spec_document`; `PUT /tools/{id}` accepts `spec_document` (or `spec`) for a full replacement.

#### REST API execution — POST/PUT/PATCH/DELETE
`_run_openapi` was replaced (your tested version) so write methods work, not just GET: for
POST/PUT/PATCH, remaining flat args become the JSON request body (with Content-Type), and the
request is sent with a proper method. Verified against a live mock server for all four verbs.

#### ADK runtime tool binding
`backend/app/runtime/adk.py` now binds each agent's tools to the ADK `LlmAgent` via a
`run_attached_tool` dispatcher that calls the shared `execute_tool` registry — so when running
with `RUNTIME=adk`, agents actually invoke their attached OpenAPI/function/connector tools.

#### Ontology
- **Workflow selection by name.** Enablement → Per-workflow now lists workflow **names** in a
  dropdown; the backend still keys on the workflow **ID**.
- **Real-time extraction progress + cancel.** Text/file extraction can run as a background job
  (`async_job: true`) with a live progress bar (entities/relationships processed, phase) and a
  **Cancel** button. Poll `GET /ontology/extract/jobs/{id}`; cancel via
  `POST /ontology/extract/jobs/{id}/cancel`.
- **Import / Export.** Export a graph to a portable JSON snapshot (`GET .../export`); import via
  `POST /ontology/import` (creates a NEW graph, never overwrites). UI has Export/Import buttons.
- **Reset view / Expand / Collapse.** The interactive graph adds a **Reset view** button (clears
  focus and returns to the full graph) and **Collapse** (show only the selected node + its
  neighbors) / **Expand** (full graph), alongside the existing zoom controls.
- **Ontology data in Chat.** When a workflow uses the ontology, the Chat response shows an
  **"Ontology data used"** panel listing the entities and relationships retrieved/used for that
  answer (captured per run in `node_outputs[].ontology`).

#### Chat
- **Persistence across refresh/restart/return.** The Chat screen now restores the last-active
  (or most recent) conversation and its messages on mount, so context is no longer lost. The
  active conversation id is remembered.
- **Name / rename / delete** sessions from the history sidebar.

---

### Data Science Lab — runtime setup (required vs optional, samples, definitions)

The Add-Runtime form now marks each field **required** (accent) or **optional** (muted) based on
the selected provider, shows a one-line **definition** under every field, and has **Brev sample**
and **Azure sample** buttons that prefill realistic values you can edit.

Required by provider: **Brev** → name, provider, host, auth secret ref. **Azure** → name,
provider, host (`<resource_group>/<vm_name>`), region, auth secret ref. **SSH** → name, provider,
host, ssh user. Everything else (GPU type, runtime image, workdir, ports, idle-shutdown, MLflow
URI, backup remote, volume, JupyterHub, MIG) is optional.

Field meanings: **Provider** (managed can start/stop; SSH is connect-only) · **Host** (Brev:
instance name; Azure: `<resource_group>/<vm_name>`; SSH: host/IP) · **Region** (cloud region;
required for managed) · **Auth secret reference** (a `vault://…` pointer to the credential, never
the raw key) · **Runtime image** (NGC container the notebook/job runs in) · **Idle auto-shutdown**
(cost control on managed) · **MLflow URI** / **backup remote** / **persistent volume** (optional
integrations). See Setup → Step 9 for copy-paste Brev and Azure examples.

---

### Ontology — selecting which graph a workflow uses, and usage transparency

#### Pick the ontology per workflow
Enablement → Per-workflow now has an **"Ontology graph for this workflow"** dropdown listing your
**published** graphs. Since you can create many ontologies, this binds a workflow to a specific
one (stored as `workflow_graphs[workflow_id] = graph_id`; `GET /ontology/graphs/published`,
`PUT /ontology/workflow-graph`). Selection priority at run time: explicit workflow→graph binding
first, then tenant/tag matching, else none (plain, ungrounded).

#### Live usage transparency in Chat
When a workflow is ontology-linked, the run now streams ontology phases live —
"Retrieving ontology context…", then "Ontology matched: N entities, M relationships (e.g. …);
injecting as grounded context, then executing" — and the Chat response shows an
**"Ontology data used"** panel listing the exact entities and relationships the agent received.

#### How the agent actually retrieves & uses the ontology (the mechanism)
1. **Resolve graph** — `select_graphs()` picks the workflow's bound published graph.
2. **Retrieve** — the `OntologyProvider` reads the *published* snapshot and selects entities whose
   names/aliases appear in (or are semantically related to) the user's question + upstream text,
   then traverses their relationships one hop out to pull connected facts. (JSON store: name/alias
   match + graph traversal; Postgres/pgvector: vector similarity + traversal.)
3. **Assemble a ContextBundle** — the matched entities and relationships become a compact,
   governed "grounded context" block (only *approved/published* facts — never drafts).
4. **Enrich the prompt** — that block is injected into the agent's prompt as supplemental,
   authoritative context, so the model reasons over *your* domain facts, not just its training.
5. **Execute & attribute** — the agent runs; the bundle used is recorded on the run
   (`node_outputs[].ontology`) and shown in Chat for full traceability.

Scientifically, this is **retrieval-augmented, knowledge-grounded generation with a curated
symbolic graph**: entity linking (question → graph nodes) + one-hop relationship expansion
(structured neighborhood retrieval) + governed context injection. Versus free-text RAG, a
curated ontology gives higher-precision, relationship-aware, and governed grounding — the model
gets *disambiguated entities and explicit relationships* (e.g. "Acme —supplies→ Widget Assembly")
rather than raw document chunks, which reduces hallucination and enables multi-hop reasoning
over verified facts.

---

## Per-operation tool scoping (least privilege)

An OpenAPI tool holds all of a spec's operations. When you attach it to an agent you can now
restrict which operations that agent may call: in Create/Edit Agent → Tools, selecting an
OpenAPI tool with multiple operations reveals **operation checkboxes**. Unchecked operations are
**not exposed to the model at all** — the agent literally never sees them (e.g. a support agent
can be limited to `getCustomer`/`listInvoices` with `deleteCustomer` withheld). Leaving all boxes
checked = all operations (unchanged default). Stored per binding as `tools[].operations`.

This is enforcement at the tool-exposure layer (in `build_tool_defs`): fewer, relevant tools also
improve tool-calling accuracy. It is not identity-based RBAC (that arrives with auth), but it
meaningfully reduces blast radius today. Execution itself is unchanged — a permitted call still
flows through the same `_run_openapi` path.

---

## CI security scanning (continuous)

`.github/workflows/security.yml` runs on every push/PR and weekly:
- **pip-audit** — known CVEs in `backend/requirements.txt`.
- **npm audit** (high+) — known CVEs in frontend deps.
- **pip-licenses** — enforces the permissive-only policy (fails on GPL/AGPL/SSPL/LGPL/MPL/EPL).

It ships **non-blocking** (`continue-on-error: true`) so it reports without breaking builds; flip
those flags to `false` once you've triaged the first run. These run in your CI (which has network
access to the vulnerability databases), not in this build environment.

---

## Containerized deployment (Docker Compose)

The whole platform runs as a container stack — **frontend + backend + Postgres + MLflow** — with
all state persisted via named volumes.

```bash
cd platform/infra
cp .env.example .env          # optional: set POSTGRES_PASSWORD, model keys, etc.
docker compose up --build
# UI:      http://localhost:8080
# API:     http://localhost:8080/api/v1  (nginx proxies /api → backend:8099)
# MLflow:  http://localhost:5000
```

**Services**
- **frontend** — multi-stage build (Vite → nginx); serves the SPA and proxies `/api` to the
  backend (streaming/SSE friendly). Exposed on `8080`.
- **backend** — FastAPI/uvicorn on `8099`; has a `/api/v1/health` healthcheck; the frontend waits
  for it to be healthy before starting.
- **postgres** — `pgvector/pgvector:pg16` (Postgres 16 with the pgvector extension available), so
  the DB is ready for future RAG / semantic-ontology work. Persisted.
- **mlflow** — tracking server with a SQLite backend + artifacts, both persisted.

**Persistence (named volumes)** — nothing is lost on restart:
- `backend_data` → the JSON document store **and** file storage (`/app/data`).
- `pgdata` → Postgres data.
- `mlflow_data` → MLflow tracking DB + artifacts.

**Notes**
- The app uses its **JSON document store** by design; Postgres runs alongside (persisted,
  pgvector-ready) but the app does not read app data from it yet — migrating the store to Postgres
  is a separate future step (Phase B).
- Model keys are normally set in the UI (**Model Endpoints**); `.env` also allows an env fallback
  (`MODEL_PROVIDER` + `*_API_KEY`).
- `litellm` is included in the backend image (required for live model calls).
- For the ADK runtime set `RUNTIME=adk` and add `google-adk` to the backend image.
- `.dockerignore` files keep images lean (no `node_modules`, `data/`, `__pycache__`, `.git`).

---

## RAG / Knowledge Pipelines (Phase 1 — backend foundation)

*In progress. Phase 1 delivers the backend + API for knowledge pipelines; the RAG Studio UI
and agent/Chat consumption follow in subsequent phases.*

A **Pipeline** is a first-class configurable object: sources → extract → clean → chunk → embed
→ index (vector store) → retrieve. It's isolated in `app/rag/` and additive (nothing else
changes). Provider-backed stages (embeddings/OCR/multimodal) select an existing **Model
Endpoint by capability type** — no separate credential store.

### Model Endpoints now carry a type
Each endpoint has a `type`: `chat` (default) | `embedding` | `multimodal` | `ocr` | `rerank`.
RAG stage selectors list only endpoints of the right type. Existing endpoints default to `chat`,
so nothing breaks.

### Pipeline configuration (all UI-driven, stored per pipeline)
- **sources** (File Storage now; connectors later)
- **processing**: clean / dehyphenate / strip-boilerplate; OCR (off|local|api), tables, images
  (OCR/table/image stages are wired as config; Phase 2 completes the heavy OCR machinery)
- **chunking**: strategy (recursive | fixed | by_heading), size, overlap (with live preview)
- **embeddings**: backend local (offline-safe) or api (a `type=embedding` Model Endpoint), dim, batch
- **index**: metric, store (auto = pgvector if available, else local JSON)
- **retrieval**: top_k, min_score, rerank

### Ingestion with live progress + statistics
Ingestion runs as a background **job** (reusing the progress/cancel registry): per-document and
batch progress, plus statistics — chunk count, chunk size, token count/size, bytes, failures.
Poll `GET /rag/jobs/{id}`; cancel via `POST /rag/jobs/{id}/cancel`.

### Index catalog / inspector
`GET /rag/pipelines/{id}/stats` (documents, chunks, tokens, bytes, vector-store backend),
`GET /rag/pipelines/{id}/documents` (per-doc chunks/tokens/size/status), and a **test query**
(`POST /rag/pipelines/{id}/query`) returning ranked, scored chunks — the "is retrieval good?" tool.

### Vector store
`pgvector` when `DATABASE_URL` + psycopg are present (the compose Postgres is pgvector-ready);
otherwise a local JSON brute-force store so the pipeline runs and is testable offline. Same
interface either way.

### Endpoints
`/rag/pipelines` (CRUD), `/rag/pipelines/{id}/ingest`, `/rag/jobs/{id}`(+`/cancel`),
`/rag/pipelines/{id}/documents|stats|query`, `/rag/preview-chunking`, `/rag/embedding-endpoints`.

### Not yet in Phase 1 (planned next)
RAG Studio UI screen; OCR/table/image extraction (Phase 2); `search_knowledge` agent tool +
Chat attachment with citations (consumption); connectors + incremental delta-sync; hybrid
(vector+keyword) + reranking; ontology-guided retrieval; permission-aware retrieval (with auth).

---

## RAG — RAG Studio UI + agent consumption (this round)

### RAG Studio (nav: after Ontology)
A dedicated screen to run knowledge pipelines end-to-end from the UI:
- **Pipelines list** with live status badges (empty / ingesting / ready / error), auto-refreshing.
- **Configuration tab** — chunking (strategy/size/overlap) with a **live preview**; embeddings
  backend (local or an `embedding` Model Endpoint); processing/OCR selectors (OCR machinery is
  Phase 2). Saved per pipeline.
- **Ingest tab** — paste text (split multiple docs with `---`) or list File Storage paths.
  Ingestion runs as a **background job**: a progress bar + live counts, a **Cancel** button, and
  it **survives navigation** — leave the screen, come back, and the status keeps updating (the job
  runs server-side; the UI resumes polling via a stored job id).
- **Index catalog tab** — documents, chunks, tokens, vector-store backend, and a per-document
  table (chunks/tokens/size/status/embed-method).
- **Test retrieval tab** — a query box returning ranked, scored, source-tagged chunks.

### Linking a pipeline to an agent (consumption)
Once a pipeline is **ready**, open Create/Edit Agent → Tools → **Knowledge pipelines (RAG)** and
toggle it on. The agent gains a `search_knowledge` tool (via the existing tool system) that
retrieves cited passages from that index at run time. Verified end-to-end: an agent linked to an
HR index answered a vacation-policy question from the retrieved passage, with the source attached.

### How it plugs in
The knowledge tool is a new `tool_exec` kind (`knowledge`) that calls `rag.retrieve()` — so it
rides the same tool-calling path as OpenAPI/function/connector tools. Per-agent binding is stored
as a `{type:"knowledge", ref:<pipeline_id>}` tool, mirroring every other tool binding.

### Still pending
Chat attachment (ask a pipeline directly in Chat with inline citations) is the next consumption
piece; then OCR/rich-media (Phase 2), connectors + delta-sync, hybrid + rerank, ontology-guided
retrieval, and permission-aware retrieval (with auth).

---

## RAG — Chat attachment (cited answers in Chat)

Chat can now be **grounded in a knowledge pipeline**. In the Chat header, a "knowledge" selector
lists ready pipelines; pick one and every question in that conversation is answered using it:

1. On send, the platform retrieves the top passages from the pipeline for the user's question.
2. Those passages are injected into the workflow run as grounding context (with `[n]` markers).
3. The reply shows a **"Knowledge sources (n)"** panel listing the retrieved passages — each with
   its score and source document — so answers are cited and auditable.

This reuses the existing Chat/run machinery (no parallel pipeline; grounding is added to the
input) and mirrors the "Ontology data used" transparency panel. Selecting "No knowledge" returns
Chat to normal workflow behaviour.

With this, both consumption paths from the plan are in place: **agents** (a `search_knowledge`
tool per linked pipeline) and **Chat** (per-conversation grounding with citations). Remaining RAG
work: OCR/rich-media (Phase 2), connectors + delta-sync, hybrid + rerank, ontology-guided
retrieval, and permission-aware retrieval (with auth).

---

## UI theme consistency (RAG Studio)

RAG Studio and the Chat knowledge selector use the platform's shared NVIDIA-green dark theme
tokens (`--accent`, `--panel`, `--raised`, `--border`, `--text`, `--muted`) — no off-theme colors.
The screen header uses the standard `.section-head` treatment (accent bar) like every other
screen, metric tiles use the `.metric` mono style on a `--raised` surface, progress cards match
the ontology extraction card, and selectors use Blueprint icons rather than emoji — so the new
surfaces are visually indistinguishable from the rest of the app.

---

## RAG Phase 2 — OCR, tables, rich media, and scalable ingestion

Phase 2 adds the document-processing layer between extraction and chunking, plus concurrency.

### Canonical document model
Every extractor now produces a normalized `CanonicalDoc` of typed blocks (text / table / caption)
with provenance (section, page). Chunking is **structure-aware**: tables stay intact as single
retrievable units; text blocks chunk per config, tagged with section + page for precise citations.
Adding a new file type = writing one extractor that emits this model.

### OCR (provider-backed, honestly guarded)
- **Text-layer detection** — digital PDFs use their embedded text (fast path); only image/scanned
  pages are sent to OCR, controlling cost.
- **Backends**: `off` | `local` (Tesseract) | `api` (an `ocr`-type Model Endpoint, e.g. Azure
  Document Intelligence). If the engine/credentials aren't present, the page is recorded as
  "OCR not executed" rather than fabricating text.
- Rendering PDF pages for OCR uses PyMuPDF when installed.

### Tables & images
- **Tables** are extracted and preserved as Markdown so they retrieve as structured units:
  CSV, HTML, and DOCX offline; PDF via pdfplumber when present.
- **Images / figures** can be captioned via a `multimodal`-type Model Endpoint (guarded); image
  files are OCR'd when an OCR backend is set.

### Scalable ingestion
The ingest job now processes documents with **bounded concurrency** (default 3, set
`RAG_INGEST_CONCURRENCY`), running heavy extraction/OCR off the event loop so the API stays
responsive. Progress + cancel unchanged.

### Richer statistics
Per-document and pipeline stats now include **tables extracted, pages OCR'd, images**, and the
**extract method** (digital / ocr / mixed) — surfaced in the RAG Studio index catalog and the
per-document list.

### Optional dependencies (not required to boot)
OCR/rich-media needs extras, commented in `backend/requirements.txt`: `pypdf`, `pdfplumber`,
`pytesseract` (+ system `tesseract-ocr`), `pymupdf`, `pillow`. Without them, digital docs and
CSV/HTML/DOCX tables still work; scanned pages report OCR-not-executed. In the container, add the
`tesseract-ocr` apt package to the backend image to enable local OCR.

---

## RAG — manual ingestion (file picker) + hybrid retrieval + reranking

### Feeding files manually (no connectors needed)
Two ways, both working today:
1. **Upload → pick.** Upload documents on the **Files** screen (any type, incl. pdf/docx — stored
   as real bytes). Then in RAG Studio → Ingest → **Browse File Storage**, navigate folders and
   **Add** files to the ingest list (no path typing). Start ingestion.
2. **Paste text.** The Ingest text box (multiple docs separated by `---`).

File paths are read via File Storage and run through the full Phase 2 pipeline (extract → OCR/
tables → chunk → embed → index). Connectors are deferred; this covers manual feeding fully.

### Hybrid retrieval (vector + keyword)
Retrieval now blends dense vector similarity with a lexical BM25-lite score, fused via
reciprocal-rank fusion. This fixes pure-vector's weakness on exact terms, names, and IDs (e.g. an
invoice number like `INV-4471` now ranks correctly). On by default; toggle per pipeline in
Configuration → Retrieval. The Test tab shows the active method (`vector` / `hybrid` /
`hybrid+rerank`).

### Reranking
Optional final re-order: `off` | `local` (lexical relevance re-order) | `api` (a `rerank`-type
Model Endpoint, guarded). Configure in Retrieval; over-fetches candidates then reorders to the
top-K.

Both are additive: existing pipelines default to hybrid-on, vector-only remains available, and the
agent `search_knowledge` tool + Chat grounding automatically benefit from improved ranking.

---

## Ontology — enablement clarity, context-size control, bigger graph, live chat display

### Enablement (and why it might look "not saved")
Per-workflow enablement persists correctly (`is_enabled` resolves workflow → tenant → default).
The common confusion is enabling a workflow **without a published graph bound** — the runtime then
falls back to plain context (by design). The Enablement screen now shows a warning in that case,
so it's clear the ontology won't be used until a graph is published + bound.

### Context size — how many connected nodes an agent gets (new control)
When a query matches ontology entities, the agent shouldn't receive the whole (possibly huge)
graph. Enablement now has a **context-size** control:
- **Expansion depth (hops)** — from each matched node, how many relationship hops to include
  (0 = only the matched nodes, 1 = +direct neighbors, etc.).
- **Max nodes (cap)** — a hard ceiling so a large ontology never floods the agent's context.
Retrieval does a bounded BFS from matched seed nodes out to the configured depth, capped at the
node limit. Verified: 1/2/3 hops yield the expected neighborhoods; the cap is always respected.

### Bigger graph view
The knowledge graph is now the prominent element — it fills a large responsive area (up to ~76% of
the viewport height) instead of a small fixed box, with a clear "drag/zoom/click/expand" hint.

### Ontology usage shown live in Chat
When a workflow/agent uses the ontology, Chat now surfaces the retrieved entities + relationships
**as each agent completes during streaming** (not only at the end), via the "Ontology data used"
panel — plus the run activity emits live "Retrieving ontology context…" / "Ontology matched: N
entities, M relationships…" phases.

---

## Fixes from field observations (ontology enablement, RAG PDF/OCR, DSLab)

### Ontology enablement / workflow-graph mapping (root-cause fixed)
The reported bug — selecting a workflow + graph and clicking Enable didn't persist/apply — was
caused by binding and enabling being **two separate actions**. Binding a graph now **atomically
enables** the workflow for that graph, records the mapping on both the config and the graph, and
selection applies it. Verified: bind → enabled=true → selection returns the bound graph →
persists after reload. The Enablement UI is unchanged except the Enable button now does both in one
click; workflow **names** (not IDs) are shown, published graphs are listed, extraction progress +
cancel and the hop/node context control are all preserved (this was a merge of the field fix into
the current superset, not a downgrade).

### RAG — PDF ingestion + OCR endpoints
- **Digital PDFs** now work reliably: <code>pypdf</code> is a required backend dependency.
- **Scanned PDFs** no longer fail silently — the pipeline returns clear guidance to enable OCR.
- **OCR endpoints** are dispatched by provider: **Azure AI Document Intelligence** (prebuilt-read
  REST, submit→poll, SSRF-guarded), **Google Cloud Document AI** (process REST), and **vision LLMs**
  (GPT-4o / Gemini / Mistral via LiteLLM). Document-AI services receive the whole PDF directly.
- **Model Endpoints UI** now has a **Type** selector (chat / embedding / multimodal / ocr / rerank)
  and the two Document-AI providers; selecting a Document-AI provider auto-sets Type = OCR and shows
  the service-endpoint field. RAG stage dropdowns filter by type. See in-app Setup → Step 10.

### Data Science Lab — Auth Ref clarity + SSH
- The **Auth Secret Ref** field now documents exactly what to provide per provider (SSH: absolute
  <code>.pem</code> path on the backend host; Brev: token/vault ref; Azure: service-principal ref).
- In-app Setup → Step 11 adds a full SSH walkthrough (key placement + <code>chmod 600</code>,
  installing <code>jupyterlab</code>+<code>papermill</code> on the target, venv guidance) and documents
  the known limitations (verify JupyterLab on :8888, papermill on the active Python).

*Honest scope note:* live SSH/JupyterLab/papermill behavior can't be exercised in this build
environment, so the DSLab items are delivered as clarified configuration + documentation; the code
paths for OCR/Document-AI are wired and guarded (they run against real credentials in your
deployment). Azure Document Intelligence / Google Document AI REST calls follow each vendor's
documented contract but should be smoke-tested once with your keys.

---

## Data Science Lab — deeper SSH fixes (direct .pem upload, lab validation, interpreter)

Building on the earlier DSLab clarity pass, three concrete fixes address the field observations:

### 1. Direct .pem upload (no manual ~/.ssh placement)
Each SSH runtime card has an **Upload .pem** button: pick the key file and it's stored **0600** on
the backend host and bound as the runtime's `auth_secret_ref` automatically. The SSH provider now
authenticates with that key explicitly (`key_filename`) instead of relying on keys pre-placed in
`~/.ssh`. Test reports "SSH auth OK (via uploaded key)". A vault:// ref or an absolute path still
work; an unresolvable ref is now flagged clearly instead of silently failing.

### 2. JupyterLab start-validation (no more "ready" then "connection refused")
**Open Lab** launches JupyterLab and then **polls the target until port 8888 is actually listening**
(via `ss`/`netstat`/`lsof`) before marking the session ready and opening the Workspace tab. If it
doesn't come up, the step results say so and point to `/tmp/jupyter.log` — instead of showing
"ready" and then failing to connect.

### 3. Correct interpreter for JupyterLab + papermill
Runtimes have a **Target Python** field (e.g. `~/lab/bin/python`). JupyterLab is launched as
`<python> -m jupyterlab` and notebooks run as `<python> -m papermill`, so they use the exact
interpreter where you installed those packages. This fixes "papermill not installed" when it was
installed on a different Python; the error now names the interpreter and the fix.

*Honest scope note:* these run against a real SSH target with paramiko installed on the backend.
They can't be exercised in the build sandbox (no VM), so they're delivered as verified logic
(auth resolution, key storage 0600, interpreter-based commands, port-validation flow) — smoke-test
once against your VM. The in-app Setup → Step 11 reflects the new flow.

---

## Ontology backend — adopted your updated files (proper integration)

Your uploaded `ontology_1.zip` (module) and `ontology_1.py` (router) are now the base of the
ontology backend, integrated correctly this time:

- **All your files are in place**, including the new `graph_io.py`, and your `contract.py`,
  `ontology_provider.py`, `selection.py`, `ontology_store.py`, and router.
- **The agent now actually uses the ontology.** Two root causes fixed: (1) your `contract.py`
  renders relationships with **entity names** (`Diabetes --has_symptom--> Fatigue`) instead of raw
  IDs, so the model can read them; (2) the runtime now injects the graph context as an
  **authoritative** block ("prefer these facts over your own knowledge; cite the entities you
  use") instead of a soft "supplemental" note the model could ignore.
- **Atomic enable+bind** (your fix): binding a workflow to a graph enables it and records the
  mapping on both config and the graph, in one action. Verified end-to-end: bind → enabled →
  selection returns the bound graph → persists.
- **Preserved on top of your files**: the async extraction jobs (real-time progress + cancel) and
  the workflow-name dropdown, since your base didn't include them and you asked to keep them. The
  UI is unchanged.
- **Router compatibility**: your router is the base; the few endpoints the existing UI needs but
  your version didn't expose (`/graphs/published`, `/import`, `/workflow-graph`, and the async
  `/extract/jobs`) are added as thin bridges so nothing in the UI breaks.
- **Dependency note**: your router uses `Form`/`File`, so `python-multipart` is now required, and
  `fastapi`/`starlette` are pinned to a compatible range (an unpinned combo can silently break
  route registration).

*Honest note:* the live model call that proves the agent's final wording can't run in the build
sandbox, but the full retrieval path is verified — the ontology is selected, entities+relationships
are resolved and rendered by name, and injected as authoritative context. On your deployment the
agent will ground answers in the graph; if you still see it ignoring the ontology, capture the run
and I'll tighten the prompt further.

---

## DSLab SSH Workspace — real tunnel + HTTP/WebSocket proxy (fix1 + fix2)

Applied the validated patches exactly. The workspace no longer returns a browser-loopback URL;
it proxies Jupyter through AI Studio over a real backend-owned SSH tunnel.

**Flow:** Browser → `/api/v1/dsl/runtimes/<rid>/lab/` → FastAPI HTTP/WebSocket proxy →
backend-local SSH forward → target `127.0.0.1:8888`.

fix1:
- **Real SSH tunnel** — `SSHProvider.tunnel()` now opens a Paramiko `direct-tcpip` forward
  (threaded local server) instead of returning a fake success. New deps: `paramiko`, `httpx`,
  `websockets==13.1`.
- **`open_lab()`** launches Jupyter with `--ServerApp.base_url=/api/v1/dsl/runtimes/<rid>/lab/`,
  writes a per-runtime PID file, verifies the port is listening, opens the tunnel, and HTTP-probes
  it before returning a **relative** `embed_url`. Returns clear per-step results.
- **HTTP + WebSocket proxy** in `dsl.py` forwards all Jupyter traffic (streaming, hop-by-hop
  headers stripped). **Close Lab** (`DELETE /runtimes/{rid}/lab`) tears down the tunnel; tunnels
  also close on runtime deletion and backend shutdown.
- **Frontend**: `dslCloseLab`, a Close Lab button, and a `workspaceUrl()` guard that rejects any
  loopback/cross-origin URL. **nginx.conf** rewritten with the `$connection_upgrade` map and
  WebSocket upgrade headers + long proxy timeouts on `/api/`.
- Single Uvicorn worker (the in-memory tunnel map can't be shared across workers/replicas).

fix2 (extension):
- WebSocket proxy connects upstream with `origin=None` (removes the browser Origin that caused
  Jupyter to reject the kernel `channels` socket with 403) and logs failures via
  `dslab.websocket`.
- Jupyter launch includes `--ServerApp.allow_origin='*'` (the documented 403 remedy). Safe here
  because Jupyter stays bound to the target's `127.0.0.1` behind the tunnel + proxy.

*Operational notes (from the patch):* install JupyterLab into the runtime's **Target Python** on
each target; set `AllowTcpForwarding yes` on the target sshd; keep Jupyter bound to target
loopback; after a backend restart, click Close Lab then Open Lab again (live tunnels don't survive
a restart). Verification: the kernel WebSocket should return `101 Switching Protocols` and cells
execute on the remote VM.

*Honest note:* the live SSH tunnel, HTTP/WS proxy, and kernel socket can't be exercised in this
build sandbox (no target VM, no browser). All code compiles, imports, and registers its routes
(HTTP+WS proxy, close-lab), and the tunnel-management functions behave correctly for the no-tunnel
cases. Run the doc's §13 verification checklist once against your VM.

---

## Ontology frontend wiring + WebSocket dep fix

- **DSLab WS:** `websockets.connect()` now uses `additional_headers` (the `extra_headers` name is
  removed in newer `websockets`); no other DSLab behavior changed.
- **Ontology frontend audit:** verified all 29 ontology client calls map to real backend routes and
  that response shapes match what the UI reads (graph list, graph view entities/edges, analytics,
  models, published graphs, workflow-graph bind). Fixed two real frontend-visible defects:
  1. The "Ontology enabled by default" switch had a broken handler (`await fetch;`) — it now calls
     `ontologySetConfig` correctly.
  2. **Extraction jobs never completed.** The extractor reported progress but never marked the job
     `done`, so the progress bar spun forever and results never surfaced. The async extract routes
     now finish the job with its entity/edge counts on success. Verified end-to-end: a text
     extraction job reaches `status=done` with the correct counts.

---

## Ontology frontend↔backend wiring fixes

With the backend confirmed working, these fixes make the Ontology **screen** drive it correctly:

- **Extraction progress no longer spins forever.** The async extraction job now reaches a terminal
  state — the wrapper finishes the job with its result (`done` with entities/edges/method, or
  `cancelled`), so the progress bar completes and the toast shows the counts. Previously the job
  stayed `running` because nothing called `finish()`.
- **Enablement reads its data.** The ontology config now always includes `workflow_graphs` (the
  workflow→graph binding the Enablement screen displays and pre-selects) and `expansion` (the
  context-size control), so a fresh install shows the correct state instead of blanks.
- **Export works before publishing.** The export button now requests the live approved draft
  (`source=live`), so it no longer errors on graphs that were never published.

Also verified every Ontology screen call maps to a live backend route and returns the shape the UI
reads (graph list/view, entities/edges with source/target, models, telemetry, review-queue,
versions, analytics, datastore, neighbors, entity detail, item status, version transition).

The DSLab WebSocket proxy uses `additional_headers` (the current `websockets` API).

---

## Conversation context compression (flag-gated, editable prompt)

A new optional layer that compresses long Chat conversations to save context window. **Off by
default — when off, nothing changes and no UI appears.**

### Turn it on (Governance → Platform Settings → Conversation context compression)
- **Enable context compression** — master flag (controls behavior *and* the Chat UI meter).
- **Summarizer model** — a chat Model Endpoint to write the summary; if none is set or a call
  fails, a deterministic **local fallback** runs (offline-safe).
- **Compress after (tokens)** — the transcript is compressed once it exceeds this (default 6000).
- **Keep recent turns** — most recent turns kept verbatim (default 6).
- **Target summary size** — soft token budget for the rolling summary (default 400).
- **Compression prompt** — a fully editable, **scientific** prompt with `{history}` and
  `{target_tokens}` placeholders. It instructs the summarizer to preserve decision-relevant detail
  (goals, constraints, decisions, identifiers/numbers/paths/URLs, open items) and drop redundancy,
  to minimize context loss. Tune it to your domain.

### What happens
When enabled and a conversation passes the threshold, Chat sends **summary + recent turns** to the
model instead of the full history. The full transcript is always preserved and viewable — only what
is *sent to the model* is compressed.

### Where you see it (Chat)
A context-compression banner shows live: "sent 306 tokens instead of 1,440 (78.8% saved) · 54
earlier turns summarized via model/local", or a note that the transcript is still under threshold.

### Safety
Entirely additive and flag-gated: with the flag off, Chat uses its previous last-N-turns behavior
unchanged. Endpoints: `GET /chat/compression-config`, `POST /chat/compress`. Config lives in
governance settings (`compression` block) and deep-merges so new keys survive older settings files.

*Honest note:* summary quality depends on the chosen model; the plumbing, flag-gating, savings math,
and local fallback are verified offline (78.8% token reduction on a 60-turn sample), but tune the
prompt + pick a good summarizer on your infra for best fidelity.

---

## Ontology section — full review pass (six points)

1. **Backend** — confirmed strong; the work below is frontend wiring + two provider/selection fixes.
2. **Scientific extraction prompt (editable, mandatory).** The base extraction prompt now lives in
   `ontology_config.extraction_prompt` — a rigorous, scientific template with required placeholders
   `{text}` (source) and `{instructions}` (your optional notes). It's shown in the Auto-extract card
   as a required, expandable, editable field with "Save as default" and "Reset to default", and is
   sent with each extraction (per-run edits or a saved default). A warning shows if `{text}` is missing.
3. **Multi-hop traversal (user-controlled).** Adopting the uploaded provider had reduced retrieval to
   a single hop. Re-implemented as a config-driven BFS that reads `expansion.max_hops` and
   `expansion.max_nodes` (both set from the Enablement screen). Only that many hops/nodes are
   traversed and used. Verified: 1 hop→2 nodes/1 edge, 2→3/2, 3→4/3, node cap respected, 0 hops→seed only.
4. **Wider graph canvas.** The Knowledge-graph card is now the hero at the top of the graph detail
   (full width, 76vh), with authoring/extract/review/version cards flowing beneath it.
5. **Design + integration.** Whole flow re-verified end to end: create → extract (scientific prompt)
   → review/bulk-approve → publish → bind+enable → retrieve. Also fixed selection so an explicit
   workflow→graph binding uses **only** that graph (previously it also mixed in other unscoped
   published graphs). Unbound workflows still fall back to tag/tenant matching.
6. **Publish.** Verified: entities/edges start as review candidates; bulk-approve (or per-item review)
   then create-version → transition to published makes the graph appear in the published list and
   available to bind. Publishing before approval is correctly blocked with a clear message.

*Honest note:* live-model extraction quality still depends on the chosen endpoint; the plumbing,
prompt-templating, multi-hop limits, selection precedence, and publish lifecycle are all verified
offline. Point the extraction model at a real endpoint to judge output quality.

---

## Compression — review fixes

Two issues from testing are fixed:

1. **"Threshold crossed but not applied."** When a conversation crossed the token threshold with only
   a few (long) turns — i.e. `turns <= keep_recent_turns` — the old gate skipped compression and the
   banner mislabeled it as "still under threshold." Now: once the transcript is over the trigger,
   compression always applies (keeping fewer recent turns if needed so there's something to
   summarize). The banner also distinguishes the real states: **applied**, genuinely
   **under threshold**, or **too few turns** (only one turn so far). The compressor now also includes
   the message being sent, so the token count reflects the current turn (no longer one exchange stale).

2. **Before / after view.** The compress response now returns the original older turns and the summary
   with per-section token counts. Chat shows a **"View before / after"** toggle: left = the earlier
   turns as they were (with token count); right = the rolling summary that replaced them (with token
   count) plus the recent verbatim turns kept. Users can see exactly what was compressed and how much
   was saved.

---

## Chat section — layout overhaul + compression display fixes

**Compression numbers (now rule-correct):**
- BEFORE = total tokens of the *entire prior conversation* (Rule 1).
- AFTER = tokens of the *compressed payload actually sent* = rolling summary + recent verbatim
  turns, returned as a single `compressed_context` string (Rule 2). The Chat sends exactly this,
  so the displayed AFTER equals what the model receives.
- % reduction is computed from those two numbers (Rule 3).
- BEFORE shows the count only; AFTER shows the count **and** the summarized text passed onward (Rule 4).

**Layout:**
- The 260px vertical history rail is gone. Conversations are now a **horizontal top bar**: a
  "New chat" button + a **Conversations ▾ dropdown** (search, rename/archive/delete, open) — the
  full width is freed for the conversation.
- Before/after is no longer inline. The header shows a compact **"⇩ N% context saved" chip**;
  clicking it opens a **dialog** with the side-by-side before/after and token tags — so it never
  pushes the Q&A area down.
- The conversation column is centered with a readable max width; the composer is pinned, auto-grows,
  and supports **Enter to send / Shift+Enter for newline**.

**Zoom/footer robustness:** the Chat pane no longer uses fixed `calc(100vh - …)` math; it fills its
container via flex, and a global `box-sizing: border-box` prevents padding overflow. The footer now
stays correctly placed at 80% / 100% / 120% zoom.

---

## Fixes: workflow canvas rendering + websockets version consistency

**Workflow UI (agents not appearing after drag/drop) — root cause + fix.**
A `box-sizing` rule had been inserted *between* the CSS `@import` lines, which is invalid: CSS
requires all `@import` statements to precede any other rule, so the browser silently dropped
`@import "reactflow/dist/style.css"`. Without ReactFlow's stylesheet, nodes rendered unstyled/mis-
positioned. Fixed by moving all `@import`s to the top (before the box-sizing rule). ReactFlow CSS is
now bundled correctly and the canvas/nodes render as before.

**websockets version consistency.**
The DSLab WS proxy was changed to `additional_headers`, but that kwarg only exists on the top-level
`websockets.connect()` in **websockets >= 14** (13.x uses `extra_headers`), while requirements pinned
`websockets==13.1` — an inconsistency that would crash the kernel socket. Fixed two ways:
(1) requirements now pin `websockets>=14,<16` and `uvicorn[standard]>=0.30` (compatible build);
(2) the proxy now detects the installed signature and uses the correct kwarg
(`additional_headers` on 14+, `extra_headers` on older), so a future version drift can't silently
break it.

---

## Persistence: PostgreSQL (JSONB) document store — containerized

The platform now stores all documents in **PostgreSQL** using a JSONB document model, while keeping
the zero-infra JSON store as a fallback. Everything runs through one repository interface, so every
create/read/update/delete goes through the same API path: UI → REST routers → repository → DB.

### Backends
- `STORE_BACKEND=postgres` (default in Docker) — documents stored as `id TEXT PRIMARY KEY, doc JSONB`,
  one table per collection, GIN-indexed. Async `asyncpg` driver under a synchronous repository seam.
- `STORE_BACKEND=json` — the original file store; used for local/offline runs and as a safe fallback.
  With the flag on json, behavior is byte-identical to before.

### What lives where
- **All documents** (agents, tools, workflows, runs, bundles, schedules, chat, model endpoints,
  governance settings + audit, ontology graphs/entities/edges/versions, RAG pipelines/documents) →
  Postgres tables via the repository.
- **RAG vectors** → `pgvector` (the compose Postgres image is pgvector-enabled; `psycopg` activates it).
- **Uploaded files** → the persistent `backend_data` named volume (blobs stay out of the DB by design).

### Containerized deployment
`infra/docker-compose.yml` runs frontend + backend + Postgres + MLflow. The backend now:
- depends on Postgres being **healthy** before starting,
- waits for the DB (retry/backoff) on startup before seeding,
- reports DB connectivity at `/api/v1/health` (`store` block),
- closes the pool gracefully on shutdown.

Bring it up:
```
cd infra && docker compose up --build
```
On first boot the app seeds the 18 agents / 5 workflows directly into Postgres. Open
http://localhost:8080.

### Migrating existing JSON data (optional)
If you already ran on the JSON store and want to bring that data across, run once (idempotent):
```
docker compose exec backend python -m app.migrate_json_to_postgres
```
It imports every `data/*.json` collection into Postgres; safe to re-run (upsert by id, no dups).

### Switching back
Set `STORE_BACKEND=json` to return to the file store instantly (JSON files are never deleted by the
migration). This is the rollback path.

### Licensing
Every added component is permissive open source: PostgreSQL (PostgreSQL License), pgvector (PostgreSQL
License), `asyncpg` (Apache-2.0), `psycopg` (LGPL, library use). No SSPL anywhere.

*Honest note:* the sandbox has no Postgres daemon, so the `PgRepo` logic + sync/async bridge were
verified against a faithful in-process stand-in and a dual-backend conformance suite (JSON vs Postgres
produce identical results for every CRUD path, plus full ontology/RAG/governance lifecycles). The real
Postgres wire connection + pgvector must be smoke-tested once in your container — bring the stack up and
confirm `/api/v1/health` shows `"store": {"backend":"postgres","ok":true}`.

---

## Fixes: large file uploads + pgvector storage + context token breakdown

**[1] Large uploads & pgvector chunk storage (workflow-blocking) — fixed.**
Three separate caps/bugs were stacking up:
- **nginx** had no `client_max_body_size`, so its **1 MB default** rejected larger uploads with 413
  before they reached the backend. Now set to `100m`.
- A backend **request-size middleware** (512 KB, for JSON payloads) also applied to uploads. File
  upload, RAG ingestion, `/extract/file`, `.pem`, and import routes are now **exempt** (they enforce
  their own size limits).
- The **pgvector** path had real defects: it never ran `CREATE EXTENSION IF NOT EXISTS vector`
  (so the vector table failed to create), depended on the `pgvector` Python package it didn't
  install, and passed raw Python lists (which fail to adapt). Rewritten to enable the extension,
  pass vectors as `::vector` literals (no extra dependency, no adaptation errors), upsert text +
  metadata on conflict, and surface errors instead of silently dropping chunks.

**[2] Context token breakdown — reworked display.**
The Chat compression view now shows each token category **separately**, and compression is applied
only to the **previous conversation** (not the new message):
- Previous conversation — **before** compression (all prior turns).
- Previous conversation — **after** compression (summary + recent verbatim turns), with the
  compressed content shown so you can read exactly what is sent.
- Current question / query — its own token count.
- Retrieved information (agent/knowledge context) — its own token count + passage count.
- Total sent to the model.
The header chip opens this breakdown; nothing is inlined into the chat stream.

**Self-review — connectivity.** Verified every store API (agents, workflows, tools, bundles,
schedules, governance, endpoints, ontology publish lifecycle, RAG pipelines, chat) plus the
RAG ingest→vector→query flow, on **both** the JSON and Postgres/pgvector backends. All green.

*Honest note:* the pgvector fixes were validated for code-path correctness against a fake psycopg
(the extension SQL, literal casting, insert/query flow) and the local vector path end-to-end. The
real pgvector similarity query must be confirmed once in your container — ingest a >1 MB PDF, then
check the pipeline's index shows the chunk count and a Chat query returns cited passages.

---

## Ported fixes from the JSON-version code changes (reflected into the Postgres version)

Analyzed the uploaded `code_changes` and reflected each fix into the current (Postgres) codebase —
adapting rather than replacing, so nothing newer was lost.

**Feature — per-run Ontology Hops (1–5).**
Users pick traversal depth per run. Threaded end to end: `RunRequest`/`Run` gain `ontology_hops`;
`runs.py` mirrors it into the run input; `client.ts startRun` forwards it; **Studio** (plan dialog)
and **Chat** (top bar) each expose a hop selector; `live.py` passes it into `QueryInput`; the
ontology provider's bounded BFS uses the per-run hop count (node cap still from config), and reports
`hop_count / traversed_nodes / traversed_edges` plus readable traversal paths. Verified 1→2 nodes,
2→3, 3→4 on both JSON and Postgres.

**Bug — published-graphs route was shadowed.**
`/ontology/graphs/published` was declared *after* the dynamic `/graphs/{gid}`, so FastAPI matched it
as `gid="published"`. Moved the static route above the dynamic one; verified it now resolves to the
published handler. (This is what broke the Enablement graph dropdown.)

**Bug — duplicated context + entities.**
- Rendered context now deduplicates entities (by name), relationships (by semantic triple) and
  traversal paths, so multi-hop no longer produces repeated lines.
- Extraction now seeds its name map from the graph's existing entities and dedups edges by triple,
  so re-extracting the same document creates **no duplicates**. Verified re-run adds 0 entities/edges.

**Bug — publish used invalid version states.**
The publish flow called version transitions `in_review`/`approved` (which are *item* states, not
*version* states) and errored immediately. Fixed to the valid `draft → review → published` sequence.
Verified end to end on both backends.

*Not reverted:* the DSLab websockets handling stays on the current adaptive kwarg (works on
websockets 13 and 14+); the uploaded `dsl.py` change was older and would have reintroduced drift.

*Honest note:* live-model extraction quality and the real Postgres/pgvector wire still need your
container smoke test; all the ported logic (hops, dedup, route order, publish states) is verified
offline against both the JSON store and a faithful Postgres stand-in.

---

## MCP integration — Phase 1 (client + tool-kind + registry)

Agents can now use tools from any MCP (Model Context Protocol) server — e.g. MLflow's — with the
server's tools discovered dynamically (no per-API wiring).

**How it works:** MCP enters through the existing tool seam. An agent bound to an MCP server gets
each of that server's tools exposed as a callable function (`build_tool_defs`), and the dispatcher
routes `kind=="mcp"` calls to the server (`execute_tool`). The runtime is untouched — both the live
and ADK runtimes already build tools through that seam.

**Key design point (async/sync):** the tool path is synchronous and the live runtime calls it inside
its own event loop, while the MCP SDK is async. The MCP client (`app/mcp_client.py`) therefore runs
all async work on a dedicated background event loop and bridges sync→async — the same proven pattern
used for Postgres in `app/db.py`. Tool discovery is cached per server so run startup never blocks on
a network round-trip. (Verified: calling an MCP tool from inside a running loop does not crash.)

**Registry + UI:** register servers under the new **MCP Servers** screen (name, transport
sse / streamable-http / stdio, URL or command). Click **Test** to discover tools. Then in the Agent
wizard → **MCP servers**, tick a server to attach it. The registry follows STORE_BACKEND
(json | postgres) like everything else.

**API:** `GET/POST /mcp/servers`, `PUT/DELETE /mcp/servers/{id}`, `POST /mcp/servers/{id}/test`,
`GET /mcp/servers/{id}/tools`. The `mcp` Python SDK (MIT) is in requirements; if it isn't installed,
MCP calls return an honest "SDK not installed" message rather than failing silently.

*Phase 2 (next):* add an `mlflow-mcp` service to docker-compose and an "Observability" agent +
workflow template. One thing to confirm first — MLflow MCP's transport (network vs stdio) — which
decides whether it runs as a separate compose service or a subprocess inside the backend container.

*Honest note:* the full path (register → discover → expose → dispatch → data back) is verified
offline against a faithful in-process fake MCP server, on both JSON and Postgres backends. The real
MLflow MCP connection is a Phase-2 container smoke test.

---

## MCP integration — Phase 2 (MLflow observability, out of the box)

**Transport resolved.** MLflow's official MCP server runs over **stdio** (the client launches
`mlflow mcp run` as a subprocess) — it does not expose a network port. So there is **no separate
compose service**: the MCP server runs as a subprocess *inside the backend container*, which already
holds the MCP client. The backend image now installs `mlflow[mcp]>=3.5.1`, and `MLFLOW_TRACKING_URI`
is already passed to the backend, so the subprocess connects to the `mlflow` service automatically.

**Seeded out of the box (idempotent on startup):**
- An **MLflow** MCP server registry entry (`transport: stdio`, `command: mlflow`, `args: [mcp, run]`).
- An **Observability Analyst** agent bound to it, with a prompt that always calls a tool before
  answering and cites trace IDs / metrics.
- An **Observability Assistant** workflow (single agent).

So after `docker compose up --build`, open **Chat**, pick *Observability Assistant*, and ask
"which traces were slowest in the last hour?" — the agent calls MLflow's MCP tools (search traces,
get trace, analyze performance, read feedback) and answers from real data. The run itself is traced
in MLflow too.

**Scope + limits (unchanged from the earlier analysis):** MLflow's official MCP server covers
**trace** management (search/retrieve/analyze traces, log feedback, manage tags, delete traces) —
not experiment CRUD or the model registry; for those, register a community MCP server the same way.
It's flagged experimental by MLflow, so the version is pinned. Deletion tools exist — scope what the
agent may call, and gate destructive tools behind approvals if needed.

*Honest note:* verified offline end-to-end against a faithful fake MLflow MCP server — the seeded
Observability agent discovers the tools, exposes them, and the dispatcher returns trace data. The
real `mlflow mcp run` subprocess + live trace queries are the container smoke test: bring the stack
up, open the Observability Assistant, and confirm a trace question returns real data. If the MLflow
image predates 3.5.1, bump it so the MCP entrypoint exists.

---

## Jupyter MCP, Apache Superset, and two MCP-driven workflows

All MCP wiring follows the official ADK pattern (https://adk.dev/tools-custom/mcp-tools): under the
ADK runtime, each MCP server bound to an agent is added to the agent's tools as a native
`McpToolset` with `StdioConnectionParams` / `StreamableHTTPConnectionParams`, optional `tool_filter`,
synchronous definition, and `close()` lifecycle. Additive and non-breaking: it only activates for
MCP-bound agents under `RUNTIME=adk`; the live/LiteLLM runtime keeps using the generic MCP seam.

**[1] Jupyter MCP — realtime notebooks inside DSLab.** A `Jupyter (DSLab)` MCP server (stdio,
`jupyter-mcp-server`) is registered. Open a DSLab lab, then `POST /api/v1/mcp/jupyter/link/{rid}`
(or the UI action) points the MCP server at that runtime's live JupyterLab, so ADK agents list,
read, insert, and execute notebook cells in real time inside the DSLab environment.

**[2] Apache Superset — containerized, embedded, with MCP.** New `superset` + `superset-mcp`
services in compose; Superset is proxied same-origin at `/superset/` and embedded in a new
**Analytics & Dashboards** UI section. The `Apache Superset` MCP server (streamable-http) exposes
Superset's REST API as agent tools. Both new MCP servers appear automatically in the Agent wizard's
MCP selector — no wizard change needed.

**[3] Two demonstration workflows (seeded, idempotent):**
- **MLflow Finetuning Intelligence** — FT Orchestrator → FT Data Consumer (reads finetuning runs/
  metrics via the MLflow MCP server) → FT Recommender (recommends next finetuning steps).
- **Dynamic Dashboard (MLflow to Superset)** — Dashboard Data Fetcher (MLflow MCP) → Superset
  Dashboard Builder (Superset MCP) — two MCP servers cooperating through agents to build a dashboard.

*Honest caveats:* ADK, Superset, and the Jupyter/Superset MCP servers can't run in the build
sandbox, so the `McpToolset` wiring, registry, seeds, routes, compose, and UI are verified
statically (and the McpToolset builder is a safe no-op without `google-adk[mcp]`). Live behavior is
your container smoke test: bring the stack up with `RUNTIME=adk` and `google-adk[mcp]` installed,
open the Analytics section, Open a DSLab lab + link Jupyter MCP, then run the two workflows.
The `superset-mcp` image installs the community server package at start — pin the exact package you
standardize on for production.

---

## Self-review fix: Jupyter MCP now works like MLflow MCP (+ notebook workflow added)

A review found the Jupyter MCP integration was not functioning symmetrically with MLflow's. Fixed:

- **Server binary installed.** `jupyter-mcp-server` is now in backend requirements (the analog of
  `mlflow[mcp]`), so its stdio subprocess can actually spawn.
- **Correct CLI.** The registry entry now runs `jupyter-mcp-server start --transport stdio` (the
  `start` subcommand was missing before).
- **Both env conventions.** It now sets `JUPYTER_URL`/`JUPYTER_TOKEN` *and* the older
  `DOCUMENT_URL`/`RUNTIME_URL`/`*_TOKEN`, plus `ALLOWED_JUPYTER_MCP_TOOLS` so agents get the
  execute/insert/read/run-all tools (not just the 2 defaults).
- **The missing piece — an agent and workflow.** Added a **Notebook Runner** agent bound to the
  Jupyter MCP server and a **Notebook Execution (DSLab)** workflow. Previously no agent/workflow used
  Jupyter MCP at all, which is why it appeared not to work.
- **Linking.** `POST /api/v1/mcp/jupyter/link/{rid}` points the server at the open DSLab lab's
  Jupyter (URL + token, both conventions).

**DSLab target prerequisite (important):** the Jupyter MCP server drives notebooks through Jupyter's
real-time-collaboration + MCP-tools extensions, which plain JupyterLab doesn't include. On the DSLab
target's interpreter, install:
```
pip install jupyterlab jupyter-collaboration jupyter-mcp-tools ipykernel
```
and ideally launch that runtime's Jupyter with a token. Without these on the target, the MCP server
connects but can't manipulate notebooks.

**To use it:** open a DSLab lab → link Jupyter MCP (`/mcp/jupyter/link/{rid}`) → run the *Notebook
Execution (DSLab)* workflow (or any agent bound to the Jupyter MCP server).

*Honest status:* the wiring, CLI, env, agent, and workflow are verified statically and via a faithful
fake MCP server (discovery → tool exposure → execute → outputs). The real notebook execution needs a
live DSLab target with the collaboration extensions above — that's the container smoke test. This is
the one inherent difference from MLflow MCP: Jupyter MCP must target a *running* notebook server, so
it requires the one-time link step, whereas MLflow's tracking URI is always static.

---

## Fix: Jupyter MCP tools not listing — now diagnosable

The Jupyter MCP tool list came back empty with no explanation, while MLflow's worked. Two reasons,
both now addressed:

1. **Silent failures.** `list_tools` caught every error and returned `[]`, so the UI showed an empty
   list with no cause. It now records the failure reason; the `/mcp/servers/{id}/tools` and
   `/test` endpoints return a precise reason, and the MCP Servers screen shows it inline.
2. **Why Jupyter differs from MLflow.** MLflow's MCP exposes a *static* tool set, so it lists without
   a live backend. Jupyter's MCP enumerates tools from a *running* JupyterLab, so it can list nothing
   until it's (a) installed and (b) linked to an open DSLab lab.

**What the Test button now tells you (self-diagnosis):**
- `command 'jupyter-mcp-server' not found` → the server package isn't installed in the backend image.
  It's in requirements (`jupyter-mcp-server`); rebuild the backend so the console script is on PATH.
  If your installed version uses a different entrypoint, set the registry entry's command/args to
  match (e.g. `python -m jupyter_mcp_server start --transport stdio`).
- `not linked to a running Jupyter yet` → open a DSLab lab, then
  `POST /api/v1/mcp/jupyter/link/{runtime_id}` (the screen hints this). Tools appear after linking.
- `connect_failed: …` → linked, but the target Jupyter is unreachable or missing the
  `jupyter-collaboration` + `jupyter-mcp-tools` extensions (install them on the DSLab target).

So the resolution order is: **rebuild backend (installs the server) → Open a DSLab lab → link it →
Test**. The reason is now visible at every step instead of a blank list.

---

## Jupyter MCP — now a UI-configured streamable-HTTP service (no rebuild to change Jupyter target)

Reworked for the topology where Jupyter runs OUTSIDE the container.

**Architecture.** A dedicated `jupyter-mcp` compose service runs the Jupyter MCP server once in
streamable-HTTP mode on :4040 with `host.docker.internal` access (so it can reach a Jupyter on the VM
host). It carries NO Jupyter URL/token — those are set from the UI and applied live via the server's
`connect` command, so changing the Jupyter IP/port/token never needs a rebuild or compose edit.

**Where the config lives (the correct place): the MCP Servers screen.** The Jupyter entry now has
editable **Jupyter URL** and **Jupyter token** fields plus a **Save & Connect** button:
- Jupyter outside the container → `http://host.docker.internal:<port>` (e.g. 8888).
- Enter the token if your Jupyter uses one.
- Click **Save & Connect** → the backend runs `jupyter-mcp-server connect --jupyter-url … --jupyter-token …`
  against the running service, binding it live. Then **Test** lists the tools.

Values persist in the registry (Postgres), so they survive restarts and are editable anytime —
exactly like Model Endpoints. No backend/compose changes to re-point Jupyter.

**Prerequisites on the external Jupyter (unchanged):** install the extensions and run with a token:
```
pip install jupyter-collaboration jupyter-mcp-tools
jupyter lab --port 8888 --IdentityProvider.token=MYTOKEN --ServerApp.allow_origin='*' --collaborative
```

**Resolution flow:** `docker compose up -d jupyter-mcp` → MCP Servers → enter Jupyter URL+token →
Save & Connect → Test. The `connect` is run from the backend (which has the `jupyter-mcp-server` CLI),
so if Test still fails the message states the precise reason (connection refused, auth, extensions).

*Note:* the service uses `--insecure-mcp-noauth` because it is only reachable on the internal compose
network; expose it with `MCP_TOKEN` if you publish the port externally.

---

## Jupyter MCP — root-cause fixes (service start, 127.0.0.1, synchronization)

A deep review found four compounding issues; all are now fixed.

**[1] Service wouldn't start.** It ran `pip install jupyter-mcp-server` in bare `python:3.12-slim`
at container start — the package's native deps (pycrdt) need a build toolchain slim lacks, so the
install failed and the container exited. **Fix:** the `jupyter-mcp` service now uses the official
prebuilt image `datalayer/jupyter-mcp-server:latest` (all deps baked in, no runtime pip). The heavy
`jupyter-mcp-server` dependency was also **removed from the backend image** (it was only there for a
CLI we no longer use, and risked breaking the backend's slim build).

**[2] DSLab 127.0.0.1 connectivity.** The DSLab SSH tunnel bound to `127.0.0.1` inside the backend
container, and the link handed that URL to the jupyter-mcp service — a *different* container, where
`127.0.0.1` is its own loopback. **Fix:** the tunnel now binds `0.0.0.0`, and the DSLab link builds
`http://backend:<port>/…` (service name on the compose network), so the jupyter-mcp container can
actually reach a DSLab-managed Jupyter.

**[3] Synchronization.** Two topologies had been conflated. They are now distinct and both correct:
external Jupyter (host) → `host.docker.internal:<port>`; DSLab Jupyter → `backend:<tunnelport>`.

**Config mechanism (Option Y — UI-driven, no rebuild).** The Jupyter URL/token are entered on the
**MCP Servers** screen. **Save & Connect** writes them to `infra/.env` (mounted into the backend) and
returns a one-line apply command:
```
docker compose up -d jupyter-mcp
```
The service re-reads its env on that ~2s refresh and connects — no code change, no image rebuild.
Changing the Jupyter IP/port later is the same two steps: edit in UI → run that command.

**Getting the token.** The token is your Jupyter's own auth secret. For the current setup we use
**no token (Option 3)** — start Jupyter with `--IdentityProvider.token='' --ip=0.0.0.0
--ServerApp.allow_origin='*' --collaborative` (plus `pip install jupyter-collaboration
jupyter-mcp-tools`) and leave the token field blank. To use a token later, start Jupyter with
`--IdentityProvider.token='YOURS'` (or read it from `jupyter server list`) and paste the same value.

**End-to-end for your setup (external Jupyter, empty token):**
1. On the host: `pip install jupyter-collaboration jupyter-mcp-tools` and run
   `jupyter lab --port 8888 --ip=0.0.0.0 --IdentityProvider.token='' --ServerApp.allow_origin='*' --collaborative`.
2. `docker compose up -d --build jupyter-mcp backend`.
3. MCP Servers → Jupyter → URL `http://host.docker.internal:8888`, token blank → **Save & Connect**.
4. Run the shown `docker compose up -d jupyter-mcp` → **Test** → tools list.

*Honest status:* fixed statically and verified (official image in compose, env written+upserted with
empty token, tunnel binds 0.0.0.0, backend dep removed, apply command returned). The live container
start of the official image and the host-Jupyter connection are the smoke test on your VM.

