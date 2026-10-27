"""Seed loader (spec §22): default foundation agents + runnable sample workflows.
Idempotent — safe to run on every boot; only writes if the collection is empty.
"""
from __future__ import annotations

from .schemas import (AgentCard, AgentCategory, IOContract, ModelConfig, Prompts,
                      ToolBinding, ToolType, WorkflowEdge, WorkflowGraph, WorkflowNode)
from .store import agents as agents_repo
from .store import workflows as workflows_repo

_FOUNDATION = [
    ("Web Researcher", "Web Researcher", "gemini-3-flash", "research_findings",
     [ToolBinding(type=ToolType.builtin, name="web_search")],
     "Search the web and return distilled, cited findings."),
    ("Document Q&A (RAG)", "Document Q&A (RAG)", "gemini-3-pro", "answer",
     [ToolBinding(type=ToolType.builtin, name="rag_retrieval")],
     "Answer questions grounded in uploaded documents with citations."),
    ("Data Extractor", "Data Extractor", "gemini-3-flash", "raw_data",
     [ToolBinding(type=ToolType.function, name="parse_file")],
     "Extract structured rows from CSV/XLSX/PDF files."),
    ("Analyst", "Analyst", "gemini-3-pro", "analysis_result",
     [ToolBinding(type=ToolType.builtin, name="code_execution")],
     "Analyze structured data, compute metrics, flag anomalies."),
    ("Summarizer", "Summarizer", "gemini-3-flash", "summary", [],
     "Condense content into a clear executive summary."),
    ("Email/Comms Drafter", "Email/Comms Drafter", "gemini-3-flash", "email_draft",
     [ToolBinding(type=ToolType.openapi, name="email.send")],
     "Draft professional emails; requires approval before send."),
    ("Critic / Reviewer", "Critic / Reviewer", "gemini-3-pro", "verdict", [],
     "Verify an output is grounded in its evidence; pass or request revision."),
    ("Router / Classifier", "Router / Classifier", "gemini-3-flash", "route", [],
     "Classify an input and route it to the right downstream agent."),
    ("Workflow Designer Agent", "Workflow Designer Agent", "gemini-3-pro", "workflow_graph", [],
     "Decompose a goal and compose a reuse-first workflow from the Garden."),
    # --- security scenario agents ---
    ("Trace Collector", "Trace Collector", "gemini-3-flash", "traces",
     [ToolBinding(type=ToolType.builtin, name="mlflow_query")],
     "Collect agent execution traces/spans from the trace store for analysis."),
    ("Prompt-Injection Detector", "Prompt-Injection Detector", "gemini-3-pro", "injection_findings", [],
     "Detect prompt-injection attempts in prompts, tool outputs and RAG content."),
    ("Jailbreak Analyzer", "Jailbreak Analyzer", "gemini-3-pro", "jailbreak_findings", [],
     "Identify jailbreak / guardrail-bypass attempts in conversations."),
    ("Anomaly Correlator", "Anomaly Correlator", "gemini-3-pro", "incidents",
     [ToolBinding(type=ToolType.builtin, name="code_execution")],
     "Correlate signals (bursts, egress, anomalies) into incidents."),
    ("Incident Responder", "Incident Responder", "gemini-3-pro", "incident_report", [],
     "Write the security incident report and apply automated response actions."),
    # --- document scenario agents ---
    ("Document Preprocessor", "Document Preprocessor", "gemini-3-flash", "clean_docs",
     [ToolBinding(type=ToolType.function, name="parse_file")],
     "Ingest, clean, dedupe and chunk uploaded documents."),
    ("Entity & Key-Point Extractor", "Entity & Key-Point Extractor", "gemini-3-pro", "key_points", [],
     "Extract entities, key points and cross-references from documents."),
    ("Cross-Document Analyzer", "Cross-Document Analyzer", "gemini-3-pro", "analysis",
     [ToolBinding(type=ToolType.builtin, name="code_execution")],
     "Analyze across documents for themes and contradictions."),
    ("Synthesis Writer", "Synthesis Writer", "gemini-3-pro", "final_deliverable", [],
     "Synthesize processed documents into the final deliverable file."),
]


def _agent(name, role, model, out_key, tools, desc, category=AgentCategory.foundation):
    return AgentCard(
        agent_name=name, role=role, category=category, description=desc,
        tags=[role.split()[0].lower()],
        model_config=ModelConfig(model=model),
        prompts=Prompts(system_prompt=f"You are a {role}. {desc}"),
        io_contract=IOContract(output_key=out_key),
        tools=tools,
        owner={"user_id": "system", "team": "platform"},
        metrics={"runs": 0, "success_rate": None, "avg_cost_usd": None},
    )


def _node(node_id, agent_name, out_key, bindings, status="reused"):
    return WorkflowNode(node_id=node_id, agent_ref=f"agent_cards/{agent_name}",
                        status=status, output_key=out_key, input_bindings=bindings)


def seed() -> None:
    if not agents_repo.list():
        for spec in _FOUNDATION:
            card = _agent(*spec)
            agents_repo.upsert(card.model_dump(by_alias=True))

    if not workflows_repo.list():
        # A. Quarterly Sales Analysis (sequential + approval gate)
        wf_a = WorkflowGraph(
            name="Quarterly Sales Analysis",
            goal_prompt="Analyze the quarterly sales CSV, find anomalies, draft an exec email.",
            nodes=[
                _node("n1", "Data Extractor", "raw_data", {"input_data": "workflow.input.file"}),
                _node("n2", "Analyst", "analysis_result", {"raw_data": "n1.raw_data"}),
                _node("n3", "Critic / Reviewer", "verdict", {"analysis_result": "n2.analysis_result"}),
                _node("n4", "Email/Comms Drafter", "email_draft", {"analysis_result": "n2.analysis_result"}),
            ],
            edges=[WorkflowEdge(**{"from": "n1", "to": "n2"}),
                   WorkflowEdge(**{"from": "n2", "to": "n3"}),
                   WorkflowEdge(**{"from": "n3", "to": "n4"})],
            approval_gates=["n4"],
        )
        # B. Research Brief (research -> summarize -> verify)
        wf_b = WorkflowGraph(
            name="Research Brief",
            goal_prompt="Research a topic across sources and produce a cited brief.",
            nodes=[
                _node("n1", "Web Researcher", "research_findings", {"topic": "workflow.input.topic"}),
                _node("n2", "Summarizer", "summary", {"research_findings": "n1.research_findings"}),
                _node("n3", "Critic / Reviewer", "verdict", {"summary": "n2.summary"}),
            ],
            edges=[WorkflowEdge(**{"from": "n1", "to": "n2"}),
                   WorkflowEdge(**{"from": "n2", "to": "n3"})],
        )
        # C. Document Review Q&A (RAG -> verify)
        wf_c = WorkflowGraph(
            name="Document Review Q&A",
            goal_prompt="Answer questions grounded in uploaded documents.",
            nodes=[
                _node("n1", "Document Q&A (RAG)", "answer", {"questions": "workflow.input.questions"}),
                _node("n2", "Critic / Reviewer", "verdict", {"answer": "n1.answer"}),
            ],
            edges=[WorkflowEdge(**{"from": "n1", "to": "n2"})],
        )
        # D. TEMPLATE — Agent Security & Threat Analysis
        wf_sec = WorkflowGraph(
            name="Agent Security & Threat Analysis",
            goal_prompt="Analyze agent traces for prompt injection, jailbreaks and exfiltration; respond.",
            nodes=[
                _node("n1", "Trace Collector", "traces", {"scope": "workflow.input.scope"}),
                _node("n2", "Prompt-Injection Detector", "injection_findings", {"traces": "n1.traces"}),
                _node("n3", "Jailbreak Analyzer", "jailbreak_findings", {"traces": "n1.traces"}),
                _node("n4", "Anomaly Correlator", "incidents", {"injection_findings": "n2.injection_findings"}),
                _node("n5", "Incident Responder", "incident_report", {"incidents": "n4.incidents"}),
            ],
            edges=[WorkflowEdge(**{"from": "n1", "to": "n2"}), WorkflowEdge(**{"from": "n2", "to": "n3"}),
                   WorkflowEdge(**{"from": "n3", "to": "n4"}), WorkflowEdge(**{"from": "n4", "to": "n5"})],
            config={"template": True, "category": "security",
                    "description": "End-to-end detection of agent attacks (prompt injection, jailbreak, "
                                   "exfiltration) over execution traces, producing an incident report file."},
        )
        # E. TEMPLATE — Document Processing & Synthesis
        wf_doc = WorkflowGraph(
            name="Document Processing & Synthesis",
            goal_prompt="Preprocess provided documents and synthesize a final deliverable.",
            nodes=[
                _node("n1", "Document Preprocessor", "clean_docs", {"documents": "workflow.input.documents"}),
                _node("n2", "Entity & Key-Point Extractor", "key_points", {"clean_docs": "n1.clean_docs"}),
                _node("n3", "Cross-Document Analyzer", "analysis", {"key_points": "n2.key_points"}),
                _node("n4", "Synthesis Writer", "final_deliverable", {"analysis": "n3.analysis"}),
                _node("n5", "Critic / Reviewer", "verdict", {"final_deliverable": "n4.final_deliverable"}),
            ],
            edges=[WorkflowEdge(**{"from": "n1", "to": "n2"}), WorkflowEdge(**{"from": "n2", "to": "n3"}),
                   WorkflowEdge(**{"from": "n3", "to": "n4"}), WorkflowEdge(**{"from": "n4", "to": "n5"})],
            config={"template": True, "category": "documents",
                    "description": "Ingest, clean and analyze multiple documents, then synthesize a "
                                   "final deliverable file with a verification pass."},
        )
        for wf in (wf_a, wf_b, wf_c, wf_sec, wf_doc):
            workflows_repo.upsert(wf.model_dump(by_alias=True))

    from .store import bundles as bundles_repo
    if not bundles_repo.list():
        from .schemas import Bundle
        finance = Bundle(name="Finance Pack", category="finance",
                         description="Ready-made agents for finance workflows.",
                         agents=[
                             {"agent_name": "Invoice Parser", "role": "Invoice Parser",
                              "description": "Extract line items and totals from invoices."},
                             {"agent_name": "Reconciliation Agent", "role": "Reconciliation Agent",
                              "description": "Match transactions and flag discrepancies."},
                             {"agent_name": "Variance Analyst", "role": "Variance Analyst",
                              "description": "Explain budget vs actual variances."},
                         ])
        legal = Bundle(name="Legal Pack", category="legal",
                       description="Ready-made agents for in-house legal work.",
                       agents=[
                           {"agent_name": "Contract Reviewer", "role": "Contract Reviewer",
                            "description": "Review contracts and surface risky clauses."},
                           {"agent_name": "NDA Triage Agent", "role": "NDA Triage Agent",
                            "description": "Classify and triage incoming NDAs."},
                           {"agent_name": "Citation Checker", "role": "Citation Checker",
                            "description": "Verify legal citations against sources."},
                       ])
        for b in (finance, legal):
            bundles_repo.upsert(b.model_dump())

    # MLflow MCP observability template — idempotent, runs regardless of the base-seed guards above
    try:
        seed_mcp_observability()
    except Exception as e:
        import logging
        logging.getLogger("seed").warning("observability seed skipped: %s", e)
    try:
        seed_jupyter_superset_mcp()
    except Exception as e:
        import logging
        logging.getLogger("seed").warning("jupyter/superset mcp seed skipped: %s", e)


def seed_mcp_observability() -> None:
    """Idempotently register MLflow's MCP server + an Observability agent + workflow, so
    'why are my traces slow?' works out of the box. MLflow MCP is stdio transport, so it runs as a
    subprocess inside the backend container (which has mlflow[mcp]). Safe to call on every startup."""
    import os
    from . import mcp_store
    from .store import agents as agents_repo, workflows as workflows_repo

    # 1) MLflow MCP server (stdio) — fixed id so this is idempotent
    if not mcp_store.get_server("mcp_mlflow"):
        mcp_store.add_server({
            "id": "mcp_mlflow",
            "name": "MLflow",
            "transport": "stdio",
            "command": "mlflow",
            "args": ["mcp", "run"],
            "env": {"MLFLOW_TRACKING_URI": os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")},
            "enabled": True,
        })

    # 2) Observability agent bound to the MLflow MCP server (idempotent by name)
    if not any(a.get("agent_name") == "Observability Analyst" for a in agents_repo.list()):
        card = AgentCard(
            agent_name="Observability Analyst",
            role="Observability Analyst",
            category=AgentCategory.use_case,
            description=("Answers questions about traces, latency, errors and model behavior by "
                         "querying MLflow through its MCP tools."),
            tags=["observability"],
            model_config=ModelConfig(model="gpt-4o-mini"),
            prompts=Prompts(system_prompt=(
                "You are an Observability Analyst for an AI platform. You answer questions about "
                "traces, latency, errors, cost and model behavior by calling the MLflow MCP tools "
                "(search traces, get trace, analyze performance, read feedback). Always call a tool "
                "to get real data before answering — never guess. Cite the specific trace IDs, "
                "metrics and time ranges you used, and if the data is insufficient, say so and "
                "suggest what to look at next.")),
            io_contract=IOContract(output_key="observability_answer"),
            tools=[{"type": "mcp", "ref": "mcp_mlflow", "name": "MLflow"}],
            owner={"user_id": "system", "team": "platform"},
            metrics={"runs": 0, "success_rate": None, "avg_cost_usd": None},
        )
        agents_repo.upsert(card.model_dump(by_alias=True))

    # 3) Observability workflow (single agent) — fixed name for idempotency
    if not any(w.get("name") == "Observability Assistant" for w in workflows_repo.list()):
        wf = WorkflowGraph(
            name="Observability Assistant",
            goal_prompt="Answer observability questions about the platform's traces via MLflow.",
            nodes=[_node("n1", "Observability Analyst", "observability_answer",
                         {"question": "workflow.input.message"}, status="to_be_created")],
        )
        workflows_repo.upsert(wf.model_dump(by_alias=True))


def _mcp_agent(name, role, desc, server_ref, out_key, prompt):
    """Helper: an agent bound to an MCP server (tools discovered dynamically)."""
    return AgentCard(
        agent_name=name, role=role, category=AgentCategory.use_case, description=desc,
        tags=["mcp"], model_config=ModelConfig(model="gpt-4o-mini"),
        prompts=Prompts(system_prompt=prompt),
        io_contract=IOContract(output_key=out_key),
        tools=[{"type": "mcp", "ref": server_ref, "name": server_ref}],
        owner={"user_id": "system", "team": "platform"},
        metrics={"runs": 0, "success_rate": None, "avg_cost_usd": None},
    )


def seed_jupyter_superset_mcp() -> None:
    """Register the Jupyter + Superset MCP servers and the two demonstration workflows.
    Idempotent; safe on every startup. Follows the official ADK MCP pattern (servers are bound
    to agents and surfaced as McpToolset under the ADK runtime)."""
    import os
    from . import mcp_store
    from .store import agents as A, workflows as W

    # 1) Jupyter MCP server — streamable-HTTP service (runs once in compose; see jupyter-mcp).
    # The Jupyter target (URL/token) is NOT baked in: it is set from the UI and applied at runtime
    # via POST /mcp/servers/mcp_jupyter/connect (jupyter-mcp-server `connect`) — no rebuild/restart.
    if not mcp_store.get_server("mcp_jupyter"):
        mcp_store.add_server({
            "id": "mcp_jupyter", "name": "Jupyter", "transport": "streamable-http",
            "url": os.getenv("JUPYTER_MCP_URL", "http://jupyter-mcp:4040/mcp"),
            "mcp_server_url": os.getenv("JUPYTER_MCP_ADMIN_URL", "http://jupyter-mcp:4040"),
            # Jupyter target — enter these in the UI (Jupyter running outside the container is
            # typically http://host.docker.internal:8888). Applied live via the connect action.
            "jupyter_url": os.getenv("JUPYTER_URL", ""),
            "jupyter_token": os.getenv("JUPYTER_TOKEN", ""),
            "tool_filter": [], "enabled": True,
        })

    # 2) Superset MCP server (streamable-http) — talks to Superset's REST API.
    if not mcp_store.get_server("mcp_superset"):
        mcp_store.add_server({
            "id": "mcp_superset", "name": "Apache Superset", "transport": "streamable-http",
            "url": os.getenv("SUPERSET_MCP_URL", "http://superset-mcp:8008/mcp"),
            "headers": {}, "tool_filter": [], "enabled": True,
        })

    # 3) Agents for Workflow A (MLflow finetuning intelligence)
    specs = [
        ("FT Orchestrator", "mcp_mlflow", "ft_plan",
         "You orchestrate a finetuning-analysis workflow. Plan which MLflow data to pull and what "
         "the downstream agents should analyze. Keep plans concise and actionable."),
        ("FT Data Consumer", "mcp_mlflow", "ft_data",
         "You read finetuning-related data from MLflow using its MCP tools: search runs, read "
         "metrics/params/traces for finetuning experiments. Return the raw facts you found, with "
         "run ids and metric values — never guess."),
        ("FT Recommender", "mcp_mlflow", "ft_reco",
         "Given MLflow finetuning data, recommend concrete next steps (hyperparameters to adjust, "
         "runs to promote, data issues to fix). Cite the run ids and metrics behind each recommendation."),
    ]
    for nm, srv, ok, pr in specs:
        if not any(a.get("agent_name") == nm for a in A.list()):
            A.upsert(_mcp_agent(nm, nm, f"MLflow finetuning · {nm}", srv, ok, pr).model_dump(by_alias=True))

    # 4) Agents for Workflow B (dynamic dashboard: MLflow -> Superset)
    specs_b = [
        ("Dashboard Data Fetcher", "mcp_mlflow", "dash_data",
         "You pull data as-is from MLflow via its MCP tools (runs, metrics) to be visualized. "
         "Return a compact, structured summary suitable for charting."),
        ("Superset Dashboard Builder", "mcp_superset", "dash_result",
         "You build a Superset dashboard from the provided data using Superset's MCP tools: create "
         "the dataset/chart(s) and assemble a dashboard. Return the created dashboard's URL/id."),
    ]
    for nm, srv, ok, pr in specs_b:
        if not any(a.get("agent_name") == nm for a in A.list()):
            A.upsert(_mcp_agent(nm, nm, f"Dynamic dashboard · {nm}", srv, ok, pr).model_dump(by_alias=True))

    # 4b) Notebook automation agent bound to the Jupyter MCP server (runs notebooks in DSLab)
    if not any(a.get("agent_name") == "Notebook Runner" for a in A.list()):
        A.upsert(_mcp_agent(
            "Notebook Runner", "Notebook Runner",
            "Interacts with JupyterLab in DSLab via the Jupyter MCP server to read, edit and "
            "execute notebook cells in real time.",
            "mcp_jupyter", "notebook_result",
            "You operate a JupyterLab notebook through the Jupyter MCP tools. To fulfil a request: "
            "list notebooks if needed, read the relevant cells, insert or edit cells, then execute "
            "them (e.g. run-all-cells or run-cell) and report the actual cell outputs. Always run the "
            "cells and return the real outputs — never fabricate results. Cite the notebook and cell "
            "indices you touched.").model_dump(by_alias=True))

    # 4c) Workflow — Notebook Execution (DSLab) using the Jupyter MCP server
    if not any(w.get("name") == "Notebook Execution (DSLab)" for w in W.list()):
        wf = WorkflowGraph(
            name="Notebook Execution (DSLab)",
            goal_prompt="Run and manage a notebook in the DSLab JupyterLab via the Jupyter MCP server.",
            nodes=[_node("n1", "Notebook Runner", "notebook_result",
                         {"instruction": "workflow.input.message"}, status="to_be_created")],
        )
        W.upsert(wf.model_dump(by_alias=True))

    # 5) Workflow A — MLflow finetuning intelligence (3 agents, sequential)
    if not any(w.get("name") == "MLflow Finetuning Intelligence" for w in W.list()):
        wf = WorkflowGraph(
            name="MLflow Finetuning Intelligence",
            goal_prompt="Analyze finetuning data in MLflow and recommend next steps.",
            nodes=[
                _node("n1", "FT Orchestrator", "ft_plan", {"question": "workflow.input.message"}, status="to_be_created"),
                _node("n2", "FT Data Consumer", "ft_data", {"plan": "n1.output"}, status="to_be_created"),
                _node("n3", "FT Recommender", "ft_reco", {"data": "n2.output"}, status="to_be_created"),
            ],
        )
        W.upsert(wf.model_dump(by_alias=True))

    # 6) Workflow B — dynamic dashboard via two MCP servers
    if not any(w.get("name") == "Dynamic Dashboard (MLflow to Superset)" for w in W.list()):
        wf = WorkflowGraph(
            name="Dynamic Dashboard (MLflow to Superset)",
            goal_prompt="Fetch data from MLflow and build a Superset dashboard dynamically.",
            nodes=[
                _node("n1", "Dashboard Data Fetcher", "dash_data", {"question": "workflow.input.message"}, status="to_be_created"),
                _node("n2", "Superset Dashboard Builder", "dash_result", {"data": "n1.output"}, status="to_be_created"),
            ],
        )
        W.upsert(wf.model_dump(by_alias=True))


def link_jupyter_mcp_to_runtime(rid: str) -> dict:
    """Point the external jupyter-mcp container at a DSLab runtime.

    Uses the backend's lab PROXY, not the raw tunnel port: the URL is stable (survives lab
    re-opens and backend restarts), Jupyter sees a loopback Host header, and the proxy injects
    the lab token. So the one-time `docker compose up -d jupyter-mcp` stays valid afterwards."""
    import os
    from . import mcp_store
    from .modules.data_science_lab import session as dsl_session
    from .modules.data_science_lab import store as dsl_store
    rt = dsl_store.get_runtime(rid)
    if not rt:
        return {"ok": False, "detail": "runtime not found"}
    token = dsl_store.ensure_jupyter_token(rid)
    host = os.getenv("BACKEND_SERVICE_HOST", "backend")
    port = os.getenv("BACKEND_PORT", "8099")
    base = f"http://{host}:{port}/api/v1/dsl/runtimes/{rid}/lab/"
    mcp_store.update_server("mcp_jupyter", {"jupyter_url": base, "jupyter_token": token})
    from .routers.mcp import connect_server
    res = connect_server("mcp_jupyter", {})
    lab_open = bool(dsl_session.get_tunnel_port(rid))
    detail = res.get("detail", "")
    if not lab_open:
        detail += " Note: the lab is not open yet - click Open Lab in Data Science Lab first."
    return {"ok": res.get("ok", False), "jupyter_url": base, "lab_open": lab_open,
            "apply_command": res.get("apply_command", ""), "env_written": res.get("env_written"),
            "detail": detail}
