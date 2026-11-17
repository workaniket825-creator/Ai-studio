"""Idempotent seeding for fine-tuning (called from app.seed on every start):

  * File Storage folders: finetuning/notebooks, finetuning/datasets, finetuning/runs
  * the sample notebooks + README, copied ONCE (deleting or editing them is respected)
  * three agents: Fine-Tuning Planner / Executor / Reporter (handler-backed)
  * the "Fine-Tuning (DSLab)" template workflow

Existing records are never overwritten, so user edits survive restarts.
"""
from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger("tcs.finetune.seed")
SAMPLES = Path(__file__).resolve().parent / "samples"
WORKFLOW_NAME = "Fine-Tuning (DSLab)"
SEED_VERSION = 1

PLANNER = "Fine-Tuning Planner"
EXECUTOR = "Fine-Tuning Executor"
REPORTER = "Fine-Tuning Reporter"

PLANNER_PROMPT = (
    "You are the Fine-Tuning Planner. You read a user's fine-tuning requirement and choose the "
    "single most appropriate notebook from the organisation's fine-tuning notebook catalog. Match "
    "on task (e.g. instruction tuning vs classification), model family, method (full, LoRA, "
    "QLoRA), data format and hardware. Then derive the notebook parameters the requirement states "
    "or clearly implies (base model, epochs, learning rate, batch size, dataset...). Never invent "
    "notebooks or parameter names; leave anything unstated at the notebook's default. If nothing "
    "fits, say so. Answer with the JSON object you are asked for.")
EXECUTOR_DESC = (
    "Runs the selected notebook on a DSLab runtime through the runtime's DSLab MCP server "
    "(stage_job_file, start_notebook_job, notebook_job_status, cancel_notebook_job, "
    "list_job_outputs), tracks progress, collects outputs into File Storage and logs the run to "
    "MLflow. Deterministic platform step - no model call.")
REPORTER_PROMPT = (
    "You are the Fine-Tuning Reporter. You turn the facts of a finished fine-tuning run into a "
    "short, accurate report for a business user: outcome, key metrics with their values, where "
    "the model and outputs are stored, risks, and next steps. Use only the facts you are given.")


def _seed_files() -> None:
    from .. import filestore
    from ..governance import get_settings, update_settings
    from . import config
    c = config.get()
    for k in ("notebooks_dir", "datasets_dir", "runs_dir"):
        filestore.mkdir(c[k])
    state = get_settings().get("finetune_seed") or {}
    if int(state.get("samples", 0)) >= SEED_VERSION:
        return
    for f in sorted(SAMPLES.iterdir()):
        if f.suffix not in (".ipynb", ".md"):
            continue
        rel = f"{c['notebooks_dir']}/{f.name}"
        if not filestore.stat(rel):
            filestore.write_bytes(rel, f.read_bytes(), actor="system", enforce_limits=False)
    update_settings({"finetune_seed": {**state, "samples": SEED_VERSION}})


def _seed_agents_and_workflow() -> None:
    from ..modules.data_science_lab.agent_access import _pick_endpoint
    from ..schemas import (AgentCard, AgentCategory, IOContract, ModelConfig, Prompts,
                           WorkflowEdge, WorkflowGraph, WorkflowNode)
    from ..store import agents as A
    from ..store import workflows as W

    endpoint = _pick_endpoint("") or None
    specs = [
        (PLANNER, "finetune_planner", AgentCategory.use_case, "ft_selection",
         "Analyses a fine-tuning requirement and selects the best notebook from File Storage "
         "(finetuning/notebooks) with its parameters.", PLANNER_PROMPT),
        (EXECUTOR, "finetune_executor", AgentCategory.system, "ft_job", EXECUTOR_DESC, ""),
        (REPORTER, "finetune_reporter", AgentCategory.use_case, "ft_report",
         "Summarises a finished fine-tuning run: outcome, metrics, artifacts, MLflow links.",
         REPORTER_PROMPT),
    ]
    names = {a.get("agent_name") for a in A.list()}
    for name, handler, cat, out_key, desc, prompt in specs:
        if name in names:
            continue
        card = AgentCard(agent_name=name, role=name, category=cat, description=desc,
                         tags=["finetuning", "dslab", "mlflow"], handler=handler,
                         model_config=ModelConfig(endpoint_id=endpoint, model="gpt-4o-mini",
                                                  temperature=0.1),
                         prompts=Prompts(system_prompt=prompt or desc),
                         io_contract=IOContract(output_key=out_key),
                         owner={"user_id": "system", "team": "finetuning"},
                         metrics={"runs": 0, "success_rate": None, "avg_cost_usd": None})
        A.upsert(card.model_dump(by_alias=True))

    if not any(w.get("name") == WORKFLOW_NAME for w in W.list()):
        wf = WorkflowGraph(
            name=WORKFLOW_NAME,
            goal_prompt=("Fine-tune a model for the user's requirement: select the best notebook "
                         "from File Storage, execute it on the DSLab runtime, log everything to "
                         "MLflow and store the outputs per run."),
            nodes=[
                WorkflowNode(node_id="n1", agent_ref=f"agent_cards/{PLANNER}", output_key="ft_selection",
                             input_bindings={"requirement": "workflow.input.message"}),
                WorkflowNode(node_id="n2", agent_ref=f"agent_cards/{EXECUTOR}", output_key="ft_job",
                             input_bindings={"selection": "n1.ft_selection"}),
                WorkflowNode(node_id="n3", agent_ref=f"agent_cards/{REPORTER}", output_key="ft_report",
                             input_bindings={"job": "n2.ft_job"}),
            ],
            edges=[WorkflowEdge(**{"from": "n1", "to": "n2"}), WorkflowEdge(**{"from": "n2", "to": "n3"})],
            config={
                "template": True, "category": "finetuning", "long_running": True,
                "run_timeout_seconds": 25 * 3600, "max_iterations": 5,
                "description": ("Describe what to fine-tune; the agent picks the best notebook from "
                                "File Storage › finetuning/notebooks, runs it on your DSLab runtime "
                                "with live progress, logs to MLflow and saves the model, logs and "
                                "config to finetuning/runs/<run id>/."),
                "input_hint": ("e.g. Fine-tune distilbert on finetuning/datasets/tickets.csv to "
                               "classify support-ticket intent, 3 epochs"),
            },
        )
        W.upsert(wf.model_dump(by_alias=True))


def seed() -> None:
    try:
        _seed_files()
    except Exception as e:
        _log.warning("fine-tuning file seed skipped: %s", e)
    _seed_agents_and_workflow()
