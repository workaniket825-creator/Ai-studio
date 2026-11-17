# Fine-Tuning notebook execution on DSLab (v1.0 build 37)

Users describe a fine-tuning need in **Chat** (or launch the **Fine-Tuning (DSLab)** template). An
agent picks the best notebook from File Storage, the platform runs it on a DSLab runtime through
the runtime's DSLab MCP server, shows live progress, logs everything to MLflow and keeps every
artifact in a per-run folder.

## 1. How it works

```
Chat / Templates ──POST /runs──▶ executor (long-running lane, 25 h limit)
                                   │
   n1 Fine-Tuning Planner ─────────┤  catalog of finetuning/notebooks/*.ipynb  ─▶ model picks notebook
      (handler finetune_planner)   │  + parameters (JSON) ─▶ validated; keyword fallback
                                   │
   n2 Fine-Tuning Executor ────────┤  per-run folder  finetuning/runs/<run_id>/
      (handler finetune_executor)  │  MLflow run (experiment "finetuning")
                                   │  DSLab MCP: stage_job_file ─▶ start_notebook_job
                                   │      runtime: studio-jobs/<run_id>/studio_runner.py (detached)
                                   │  every 15 s: notebook_job_status + MLflow metrics ─▶ run.progress
                                   │  list_job_outputs ─▶ copy outputs/logs ─▶ finalise MLflow run
                                   │
   n3 Fine-Tuning Reporter ────────┘  final answer (model; deterministic fallback)
```

* The **model never drives the hours-long job.** It chooses the notebook and parameters; a
  deterministic step controls the job, so a 6-hour training run costs no tokens while it runs.
* The job runs **detached on the runtime** (own process group). Dropped tunnels, closed browsers
  and backend restarts do not stop it. On restart the backend re-attaches and keeps monitoring.
* **Progress is persisted on the run** (`run.progress`), not only in the in-memory activity ring,
  so Chat shows it after a reload and the Run view shows the same panel.

## 2. Setup (once)

1. **Data Science Lab**: enable it and register the runtime (as today). Opening the lab or
   "Enable agent access" is optional – the job tools open the lab automatically.
2. **MLflow reachable from the runtime.** Notebooks on the DSLab machine log to the same MLflow
   as the platform. `http://mlflow:5000` only resolves inside Docker, so set an address the
   machine can reach, either on the runtime (DSLab › runtime › MLflow URI) or in
   *File Storage › Fine-tuning settings › MLflow URI used by notebooks on the runtime*, e.g.
   `http://<platform-host>:5000` (compose publishes port 5000). If it is unreachable the run still
   completes, Chat shows "notebook can't reach MLflow", and the platform still logs configuration,
   logs, metrics files and results to MLflow from the backend.
3. **Browser link to MLflow**: set *MLflow UI link* (or env `MLFLOW_UI_URL`, e.g.
   `http://localhost:5000`) so "MLflow run" links open in the browser.
4. **Model Endpoint**: the planner and reporter use the agents' endpoint. If an agent has none, the
   first chat endpoint is used (reported in the run notes). With no endpoint at all the planner falls
   back to keyword matching and the reporter to a deterministic summary – the job still runs.
5. **Runtime Python** should have the notebook's libraries (torch, transformers, peft…). The runner
   itself needs only the standard library plus `nbclient` (installed with Jupyter); without it, it
   falls back to an in-process IPython shell. `mlflow` in that Python enables notebook-side logging
   and the upload of `outputs/` to the MLflow run.

## 3. Notebooks (File Storage › finetuning/notebooks)

Seeded on first start with a README and three samples:
`smoke_test_cpu.ipynb` (1-minute CPU end-to-end check), `lora_sft_causal_lm.ipynb` (LoRA/QLoRA SFT
template) and `text_classification_finetune.ipynb` (encoder classifier template). They are copied
once; edit or delete them freely. The README in the folder explains the conventions:

* first markdown cell = title + description; optional `studio_finetune` notebook metadata
  (task, keywords, method, model family, hardware, data formats) – both drive selection;
* one cell tagged `parameters` (papermill convention); the platform inserts an
  `injected-parameters` cell after it, values coerced to each default's type;
* write models/artifacts to `output_dir` (`outputs`) or `$STUDIO_OUTPUT_DIR`;
* datasets from File Storage are staged to `data/<file>` and passed to the dataset parameter;
* `mlflow.start_run()` / HF `report_to=["mlflow"]` log into the platform's run (`MLFLOW_RUN_ID`);
* optional `##STUDIO_PROGRESS {"step":..,"total_steps":..,"loss":..}` lines; tqdm bars are parsed too.

## 4. Running it

* **Chat**: pick *Fine-Tuning (DSLab)*, describe the job ("fine-tune distilbert on
  finetuning/datasets/tickets.csv to classify intent, num_train_epochs=4"). `name=value` pairs for
  declared parameters are always applied.
* **Templates**: the card opens a form – requirement, runtime, notebook (or "let the agent
  choose"), dataset path and JSON parameter overrides (always win).

The reply bubble shows: stage tracker (select → stage → launch → execute → collect → MLflow →
report), current cell and title, overall %, within-cell step / tqdm progress with ETA, live loss /
eval loss / epoch with a loss sparkline from MLflow, live log tail, notes, MLflow and folder links,
and a Stop button. You can leave Chat or close the browser; reopening the conversation re-attaches.

## 5. Where everything goes

| Place | Content |
|---|---|
| File Storage `finetuning/runs/<run_id>/config/` | request, selection (with reason), injected parameters + notebook defaults, runtime, job handle |
| `.../notebook/` | source, parameterised and executed notebook |
| `.../logs/` | full `run.log`, `runner.out`, final `status.json`, `progress.json` |
| `.../metrics/` | `metrics.json` (MLflow latest + notebook metrics + job stats), notebook metric files |
| `.../model/` | output files up to the copy limits (default 100 MB/file, 1 GB total) + `MANIFEST.json` listing **every** output with size, sha256, remote path and whether it was copied |
| `.../summary.md`, `report.md` | deterministic summary; model-written report |
| DSLab runtime `studio-jobs/<run_id>/` | the full job directory, including all outputs (not cleaned automatically) |
| MLflow experiment `finetuning` | one run per workflow run: tags `studio.*`, params `studio.param.*`, the notebook's own params/metrics, artifacts `studio/{config,notebook,logs,metrics,model}` and `outputs/` (uploaded by the runner, up to 20 GB) |
| MLflow experiment `tcs-ai-studio` | the usual workflow-level record (unchanged) |

## 6. Failure handling

| Situation | Behaviour |
|---|---|
| No notebook fits | planner fails honestly with the list of notebooks; nothing is launched |
| Model proposes an unknown notebook / bad JSON | keyword fallback, noted in the run |
| A cell raises | run fails with `cell N (title) failed: <Exception>: <message>`; partial outputs and logs collected |
| Stop (Chat, Run view or `POST /runs/{id}/cancel`) | SIGTERM to the job's process group (SIGKILL after 20 s), outputs collected, MLflow run `KILLED` |
| Run time limit (25 h, `config.run_timeout_seconds`) / job limit (24 h on the runtime) | remote job stopped, run failed, MLflow run `FAILED` |
| Backend restart | job keeps running; on start the run is re-attached and monitored to the end |
| Runtime unreachable | retried; after 30 min (setting) the run fails, telling you the job may still be in `studio-jobs/<run_id>/` |
| Job process killed / machine rebooted | detected through a stale heartbeat (90 s) → `lost`, run fails |

## 7. Settings (`GET/PUT /api/v1/finetune/config`, File Storage › Fine-tuning settings)

`notebooks_dir`, `datasets_dir`, `runs_dir`, `experiment`, `default_runtime_id`,
`remote_mlflow_uri`, `mlflow_ui_url`, `poll_seconds` (15), `job_timeout_hours` (24),
`lost_contact_minutes` (30), `copy_max_file_mb` (100), `copy_max_total_mb` (1024),
`copy_max_files` (500), `dataset_max_mb` (200), `log_outputs_to_mlflow` (true), `mlflow_max_gb` (20).
Platform settings gained `long_run_timeout_seconds` (86400) and `max_concurrent_long_runs` (2).

## 8. What changed (all additive)

| Area | File | Change |
|---|---|---|
| Fine-tuning | `app/finetune/` (new) | catalog, planner, notebook injection, remote job control, MLflow logging, storage, progress, step handlers, resume, seed, samples, remote runner |
| Runtime | `app/runtime/handlers.py` (new) | shared step-handler seam (agent card `handler`) used by both runtimes |
| Runtime | `runtime/live.py`, `runtime/adk.py` | call the handler seam; skip nodes already recorded on a resumed run |
| Core | `schemas.py` | `Run.progress`, `AgentCard.handler` (optional, default empty) |
| Core | `executor.py`, `governance.py` | per-workflow timeout, long-running lane, re-attachable runs not failed on restart |
| Core | `main.py` | router, re-attach on startup, shutdown flag so jobs survive restarts |
| Core | `filestore.py` | `enforce_limits=False` for platform outputs, `stat`, `walk` |
| Core | `routers/runs.py` | artifact download also serves File Storage-backed artifacts |
| API | `routers/finetune.py` (new) | `/finetune/config`, `/catalog`, `/runtimes`, `/runs`, `/runs/{id}/progress` |
| DSLab | `mcp_servers/dslab_runtime.py` | 5 new MCP tools: `stage_job_file`, `start_notebook_job`, `notebook_job_status`, `cancel_notebook_job`, `list_job_outputs` (the 9 existing tools unchanged) |
| DSLab | `jupyter_remote.py` | `mkdirs`, `put_base64`, `read_text`, `read_bytes`, `exists` |
| Seed | `seed.py` | calls `finetune.seed` (folders, samples, 3 agents, template) |
| UI | `components/FineTuneProgress.tsx` (new) | progress panel |
| UI | `Chat.tsx` | progress in the reply, re-attach on reopen/reload, no 3-minute cutoff for long-running workflows, pending run saved immediately |
| UI | `Templates.tsx`, `RunView.tsx`, `Files.tsx` | fine-tuning form; progress panel + Stop; folder shortcuts, notebook catalog hints, settings |
| UI | `Markdown.tsx`, `tokens.css` | markdown tables (benefits every agent's output) |
| Tests | `backend/tests/test_finetune.py` (new) | 17 tests incl. real notebook execution through the runner |

## 9. Verification done

* 17 unit tests pass (`STORE_BACKEND=json python -m pytest tests -q` in `backend/`).
* End to end against a real JupyterLab behind the platform's lab proxy (SSH hop simulated, as in
  build 33), a real MLflow server and an OpenAI-compatible stand-in model, through `POST /runs`
  exactly as Chat calls it: model selection, invalid-parameter rejection, explicit notebook +
  File Storage dataset + overrides, no-fit request, unknown-notebook fallback, no model endpoint,
  failing cell, Stop, run time limit, backend restart mid-job (re-attached), both `live` and
  `adk` runtimes; MLflow run contents checked; existing *Research Brief* workflow and the existing
  DSLab MCP tools re-run unchanged; frontend `tsc` and `vite build` clean; Chat/Templates/Run
  view/File Storage checked in a browser, including reload mid-run.
* Not verifiable here: the two GPU sample notebooks (no GPU or Hugging Face Hub access) – they are
  templates, syntax-checked only; a real SSH-reached remote machine.
