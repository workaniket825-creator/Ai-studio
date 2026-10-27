# TCS AI Studio — v1.0

> **TCS AI Studio v1.0** — an open-source enterprise studio to build, run and observe
> agentic workflows on **Google ADK**. Models via API (**Mistral & Gemini**); **no cloud
> platform lock-in**. © 2026 Tata Consultancy Services.

**What's new in this build**
- **Tokens, not cost:** all metrics use **input tokens, output tokens, and latency** (no dollar figures).
  Governance uses a **monthly token budget**.
- **ADK Connectors:** a catalog of Google ADK's out-of-box connectivity — built-in tools
  (Google Search, Code Execution, Vertex RAG), **MCP toolsets**, **LangChain/CrewAI**, **OpenAPI**,
  and enterprise **Application Integration** connectors (Salesforce, ServiceNow, Slack, Jira, BigQuery).
  Enable + configure them and link them to agents. See **Setup & Help** for how-to with examples.
- **Digital-earth landing page:** a cinematic animated intro (rotating globe, starfield, glowing arcs)
  as the first screen; **Enter platform** reveals Home and all sections.
- **Rebrand:** TCS AI Studio v1.0 with a standard copyright footer.

A runnable, open-source foundation for the platform in `docs/Architecture_Plan.md`.
Includes the runtime spine, agent authoring, workflow authoring, and observability.

- **Open-source code only.** Runtime uses the open-source **Google ADK** framework
  (`google-adk`, Apache-2.0) and **LiteLLM** (MIT). **No Google Cloud / Vertex
  *platform* dependency** — no Firestore, GCS, Agent Engine, Vertex Sessions, or
  Memory Bank. Persistence is local JSON; sessions/memory use ADK in-memory services.
- **Model APIs are pluggable:** **Mistral** and **Gemini** via their APIs (keys only).
  Default is **mock** — the whole app runs and is testable with *no keys at all*.



## Reliability & control (this build)
- **All runs always terminate** — a central executor wraps every run (Chat, Studio,
  Templates, agent Test, Schedules), so failures never hang the UI.
- **Loop guard:** cap agent steps per workflow (`max_iterations`, default 20 / env
  `MAX_AGENT_STEPS`); runs stop cleanly when the cap is hit.
- **Interrupt:** `POST /runs/{id}/cancel` (Stop button in Chat) halts a run between steps.
- **MLflow logging on every run** (success, failure, cancel) via the executor.
- **Chat** runs the selected workflow on your input, shows the live agent-by-agent trail,
  and returns the final answer; a Stop button interrupts loops.
- **Workflow Studio** has an explicit **New workflow** button (name it), an editable name
  field, and a max-iterations control. No hardcoded run inputs — you supply input at run time.

## Real execution only (no mock/fabricated data)
As of this build the platform executes workflows for real via **LiteLLM over your
configured Model Endpoints** (Azure OpenAI / OpenAI / Mistral / Gemini). The
fabricated "mock" runtime, canned agent outputs, and hardcoded findings have been
**removed**. Seed **agent cards and workflows** (definitions) remain; **results are
never fabricated** — if no model is configured, a run fails with a clear message.

- Default runtime: `live` (LiteLLM). `RUNTIME=adk` for the full Google ADK runtime.
- Configure models in the UI: **Model Endpoints** (add Azure/OpenAI/etc.), then pick
  per agent in the Create-Agent wizard.

## Chat
A **Chat** screen lets you pick a workflow and send it new input repeatedly; each
message triggers the workflow and returns its final answer, with expandable per-agent
steps and any generated files.

## What's implemented

**Phase 0 — runtime spine**
- FastAPI backend, Appendix-A schemas, pluggable runtime (mock | adk), seed loader
  (9 foundation agents + 3 sample workflows), and the live **"thinking" activity
  stream** over WebSocket.

**Phase 1 — agent authoring**
- Multi-step **Create Agent wizard** (identity → prompts → model → tools →
  collaboration/memory).
- **Tool Registry** with **OpenAPI upload** → auto-extracted operations you can grant
  to agents; function/builtin registration.
- **Garden CRUD**: create, edit (forks version), clone, deprecate, delete, and an
  inline **Test** that streams a single-agent run.


**Phase 2 — observability & monitoring**
- **Monitoring dashboard**: success rate, cost, tokens, p50/p95 latency, runs-by-workflow.
- **Execution trace tree** per run (agent spans → tool calls / reasoning), assembled from
  the activity stream.
- **Feedback** (👍/👎) on runs.
- **MLflow-ready**: metrics aggregate locally with zero setup; set `OBSERVABILITY=mlflow`
  (+ optional `MLFLOW_TRACKING_URI`) to log to a self-hosted MLflow. No cloud required.


**Phase 4 — learnings layer**
- **Verification / critic** verdict on runs; **cost-aware model routing** cue;
  **mid-run steering** (inject guidance into a live run); **Bundles / Role Packs**
  (Finance, Legal) with one-click install; **Schedules** for unattended interval runs.



**Scenario templates & output viewer (new)**
- **Agent Security & Threat Analysis** template: agents that analyze execution traces for
  **prompt injection, jailbreaks, and data exfiltration**, then write an **incident report file**.
- **Document Processing & Synthesis** template: ingest/clean/analyze documents → **deliverable file**.
- **Templates** gallery to launch a wide variety of workflows (scenario + sample).
- **Claude-style Output viewer** in the Run view: per-agent content, expandable intermediate
  steps, and **downloadable generated files** (markdown rendered inline) — alongside the live stream.
- **Setup & Help** guide with copy-paste examples: adding model endpoints (Mistral/Gemini, dummy
  keys), function tools, OpenAPI APIs, and mapping tools to agents.

**Module 6 — Platform Insights (final recommendation, implemented)**
- A meta-workflow that analyzes runs/agents/workflows/metrics, streams its "thinking",
  and generates a downloadable **Word (.docx) recommendation report** (python-docx).
- **Insights** screen with Analysis (run + live stream + findings) and Reports (download).

**UI / UX (best-in-class open source)**
- **React 18 + TypeScript + Blueprint.js (Palantir's open-source design system) + React Flow + Vite.**
- **NVIDIA-green dynamic dark theme**, animated nav, hover/lift cards, a **Home dashboard**
  with KPIs and quick actions, global toasts, API error handling, loading states.
- Fully interactive workflow canvas (drag/connect/add/edit/delete/save); editable agents.

**Phase 5 — governance & admin**
- **Roles** (viewer/builder/admin), **monthly budget** with live spend gauge,
  **guardrail toggles** (PII redaction, content filter, approval-for-destructive, SIEM),
  and an **audit log**. All local; no cloud.

**UI**
- Dark, dense, **NVIDIA-green** dynamic theme (Palantir-style operational feel) on
  Blueprint.js. Workflow canvas is fully interactive: **drag, connect, add from
  palette, edit in the inspector, delete, save**. Agents are **editable** from the Garden.

**Phase 3 — workflow authoring**
- **Workflow Designer** (goal → reuse-first graph; deterministic, no key needed).
- **Canvas** (React Flow) with status-colored nodes, save + versioning, validation.
- **Plan Mode**: review the ordered plan and approve before execution.

## Run it (mock — zero setup)

**Backend**
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8099 --reload      # docs: http://localhost:8099/docs
```

**Frontend**
```bash
cd frontend
npm install
npm run dev                                     # http://localhost:5173
```

## Test the flows
- **Create an agent:** Garden → *Create agent* → step through the wizard → it appears in the grid.
- **Register an API:** Tool Registry → *Load sample* (or paste OpenAPI JSON/YAML) → *Parse & register* → operations listed; the tool is now selectable in the wizard's Tools step.
- **Design + run a workflow:** Workflow Studio → type a goal (e.g. *"Extract the sales CSV, find anomalies, draft an exec email"*) → *Design* → *Plan & run* → approve the plan → watch the live thinking stream → approve the email gate.
- **Test an agent:** Garden → any card → *Test* → live stream in the Run view.

## Switch to real models (Mistral / Gemini) — still no cloud platform

```bash
pip install google-adk litellm
export RUNTIME=adk

# either provider:
export MODEL_PROVIDER=mistral MISTRAL_API_KEY=...      # Mistral API
# or
export MODEL_PROVIDER=gemini  GEMINI_API_KEY=...       # Gemini API (not Vertex)

uvicorn app.main:app --port 8099
```
The API, schemas, UI, and activity stream are identical — only `app/runtime/adk.py`
does the real model calls (ADK `LlmAgent` + `LiteLlm`, in-memory sessions).

## Verified in this build
- Backend: all Phase 1 + 3 endpoints tested over HTTP (create/edit/clone/deprecate,
  OpenAPI ingestion, designer, plan, validate) + WebSocket streaming + approval-resume.
- Frontend: `tsc` type-check clean and `vite build` succeeds.

## Layout
```
backend/app/
  schemas.py store.py activity.py models.py designer.py factory.py config.py seed.py main.py
  routers/  agents.py tools.py workflows.py runs.py
  runtime/  base.py mock.py adk.py
frontend/src/
  App.tsx api/client.ts theme/tokens.css
  screens/    Garden.tsx Tools.tsx Studio.tsx RunView.tsx
  components/  CreateAgentWizard.tsx ActivityStream.tsx
docs/  Architecture_Plan.md
infra/ docker-compose.yml
```

## Roadmap
- **Done:** Phases 0–5 + Module 6 — full platform (runtime, authoring, workflows, observability, learnings, governance, insights).
