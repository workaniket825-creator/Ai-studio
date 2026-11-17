# Fine-tuning notebooks

Put every fine-tuning notebook (`.ipynb`) in this folder (sub-folders are fine). The
**Fine-Tuning (DSLab)** workflow reads them all, picks the one that best fits the request, runs it on
a DSLab runtime and stores the results in `finetuning/runs/<run_id>/`.

## How a notebook is chosen

The planner agent sees, for each notebook:

1. **Title and description** – the first markdown cell. Say what the notebook fine-tunes, with which
   method, on what data, and its hardware needs.
2. **`studio_finetune` metadata** (optional, notebook metadata) – e.g.
   ```json
   "studio_finetune": {
     "task": "text classification",
     "keywords": ["intent", "sentiment", "bert"],
     "method": "full fine-tuning",
     "model_family": "encoder",
     "hardware": "GPU", "min_gpu_gb": 8,
     "data_formats": ["csv", "jsonl"]
   }
   ```
3. **Parameters** – the cell tagged `parameters` (papermill convention).

You can always force a notebook: name it in the request ("use text_classification_finetune") or pick
it in the template dialog.

## Parameters

Tag one code cell `parameters` and give every parameter a literal default and a comment:

```python
base_model = "distilbert-base-uncased"   # encoder checkpoint
num_train_epochs = 3
learning_rate = 5e-5
output_dir = "outputs"
```

The platform inserts an `injected-parameters` cell after it with the values for this run. Values
are converted to the type of the default. Notebooks without a parameters cell still run, as they are.

## Conventions at run time

| What | Where |
|---|---|
| Working directory | the job folder on the runtime: `<jupyter root>/studio-jobs/<run_id>/` |
| Save models and artifacts to | `output_dir` (set to `outputs`) or `os.environ["STUDIO_OUTPUT_DIR"]` |
| Dataset from File Storage | staged to `data/<file>`; passed to the dataset parameter (`dataset_path`, `train_file`, ...) and `STUDIO_DATASET` |
| MLflow | `MLFLOW_TRACKING_URI`, `MLFLOW_RUN_ID`, `MLFLOW_EXPERIMENT_NAME` are set: `mlflow.start_run()` and the Hugging Face Trainer (`report_to=["mlflow"]`) log into the run the platform created |
| Metrics file (optional) | write `metrics.json` (or `eval_results.json` / `all_results.json`) in the output folder; it is copied to `metrics/` |
| Custom progress (optional) | `print("##STUDIO_PROGRESS " + json.dumps({"step": 10, "total_steps": 100, "loss": 0.4}))` |

tqdm progress bars (Trainer, datasets) are picked up automatically and shown in Chat.

## Samples

| Notebook | Use |
|---|---|
| `smoke_test_cpu.ipynb` | One-minute CPU check of the whole path (no GPU, standard library only) |
| `lora_sft_causal_lm.ipynb` | LoRA / QLoRA instruction tuning of a causal LLM (template – needs GPU, `transformers`, `peft`, `datasets`) |
| `text_classification_finetune.ipynb` | Full fine-tune of a BERT-style classifier (template – needs `transformers`, `datasets`) |

The two GPU notebooks are starting templates: check model ids, data columns and package versions
against your runtime before relying on them. Edit or delete the samples freely; they are only
copied here once.
