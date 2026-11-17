"""Fine-tuning notebook execution on DSLab runtimes.

Pieces (all additive; nothing else in the platform depends on this package unless a workflow
uses the fine-tuning step handlers):

  config.py         settings (Governance settings doc, section "finetune")
  catalog.py        notebook catalog built from File Storage  (finetuning/notebooks/)
  notebook.py       papermill-style parameter injection
  planner.py        requirement -> notebook + parameters (LLM, validated; keyword fallback)
  remote.py         DSLab runtime access: job control through the DSLab MCP server
  mlflow_log.py     MLflow run for each fine-tuning job (MlflowClient only - never fluent)
  storage.py        per-run output folder  (finetuning/runs/<run_id>/)
  progress.py       structured, persisted progress on run.progress
  steps.py          the three workflow step handlers (planner / executor / reporter)
  resume.py         re-attach running jobs after a backend restart
  seed.py           folders, sample notebooks, agents and the template workflow
  remote_runner.py  the job runner that executes ON the DSLab runtime
"""

# set by the app's shutdown hook: a cancelled monitor must then leave the remote job running
SHUTTING_DOWN = {"value": False}
