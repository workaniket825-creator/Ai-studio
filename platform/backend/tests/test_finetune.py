"""Unit tests for the fine-tuning feature (no DSLab machine, MLflow or model needed).

Run from platform/backend:   STORE_BACKEND=json python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("STORE_BACKEND", "json")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.finetune import notebook as nbu          # noqa: E402
from app.finetune import planner                  # noqa: E402

SAMPLES = BACKEND / "app" / "finetune" / "samples"


def _nb(name):
    return json.loads((SAMPLES / name).read_text())


def _entry(name):
    nb = _nb(name)
    d = nbu.describe(nb)
    return {"name": name, "path": f"finetuning/notebooks/{name}", "valid": True, "warnings": [],
            "parameters": nbu.read_parameters(nb), **d}


# ------------------------------------------------------------------ notebook helpers
def test_read_parameters_from_tagged_cell():
    ps = {p["name"]: p for p in nbu.read_parameters(_nb("smoke_test_cpu.ipynb"))}
    assert ps["epochs"]["default"] == 30 and ps["epochs"]["type"] == "int"
    assert ps["learning_rate"]["type"] == "float"
    assert ps["epochs"]["description"] == "training epochs"


def test_inject_after_parameters_cell_and_replaces_previous():
    nb = _nb("smoke_test_cpu.ipynb")
    idx = nbu.parameters_cell_index(nb)
    out = nbu.inject(nb, {"epochs": 3, "dataset_path": "data/x.csv"})
    cell = out["cells"][idx + 1]
    assert "injected-parameters" in cell["metadata"]["tags"]
    assert "epochs = 3" in cell["source"] and "dataset_path = 'data/x.csv'" in cell["source"]
    again = nbu.inject(out, {"epochs": 5})          # re-injection must not stack cells
    tagged = [c for c in again["cells"] if "injected-parameters" in (c.get("metadata") or {}).get("tags", [])]
    assert len(tagged) == 1 and "epochs = 5" in tagged[0]["source"]
    assert nb["cells"][idx + 1].get("metadata", {}).get("tags") != ["injected-parameters"]  # input untouched


def test_inject_without_parameters_cell_goes_first():
    nb = {"cells": [{"cell_type": "code", "metadata": {}, "source": "print(1)"}]}
    out = nbu.inject(nb, {"a": 1, "not valid": 2})
    assert out["cells"][0]["source"].strip().endswith("a = 1")
    assert "not valid" not in out["cells"][0]["source"]


@pytest.mark.parametrize("value,default,expected", [
    ("3", 1, 3), ("3.0", 1, 3), ("2e-4", 0.1, 2e-4), ("true", False, True), ("no", True, False),
    (5, "x", "5"), ('["a"]', ["b"], ["a"]), (None, 1, None),
])
def test_coerce(value, default, expected):
    assert nbu.coerce(value, default) == expected


def test_samples_code_cells_compile():
    for f in SAMPLES.glob("*.ipynb"):
        for c in json.loads(f.read_text())["cells"]:
            if c["cell_type"] == "code":
                compile("".join(c["source"]) if isinstance(c["source"], list) else c["source"], f.name, "exec")


# ------------------------------------------------------------------ planner
def test_keyword_pick_matches_task():
    items = [_entry(n) for n in ("smoke_test_cpu.ipynb", "lora_sft_causal_lm.ipynb",
                                 "text_classification_finetune.ipynb")]
    assert planner.keyword_pick("quick smoke test", items)[0]["name"] == "smoke_test_cpu.ipynb"
    assert planner.keyword_pick("qlora instruction tuning for llama chat", items)[0]["name"] == "lora_sft_causal_lm.ipynb"
    assert planner.keyword_pick("classify ticket intent with bert", items)[0]["name"] == "text_classification_finetune.ipynb"
    assert planner.keyword_pick("zzz qqq", items)[0] is None


def test_finalize_validates_and_prioritises_explicit(monkeypatch):
    monkeypatch.setattr(planner, "_dataset_entry", lambda p: None)
    e = _entry("text_classification_finetune.ipynb")
    req = planner.request_from_input({"message": "classify, num_train_epochs=4",
                                      "parameters": json.dumps({"batch_size": "32"})})
    raw = {"parameters": {"learning_rate": "3e-5", "num_train_epochs": 2, "invented": 1}}
    sel = planner.finalize(e, "llm", req, raw, 0.9, "fits", [])
    assert sel["parameters"]["learning_rate"] == 3e-5           # coerced from the model's string
    assert sel["parameters"]["num_train_epochs"] == 4           # key=value in the text beats the model
    assert sel["parameters"]["batch_size"] == 32                # explicit parameters win, coerced
    assert "invented" not in sel["parameters"]
    assert any("invented" in w for w in sel["warnings"])


def test_dataset_not_in_storage_is_passed_through(monkeypatch):
    monkeypatch.setattr(planner, "_dataset_entry", lambda p: None)
    e = _entry("lora_sft_causal_lm.ipynb")
    req = planner.request_from_input({"message": "sft", "dataset": "tatsu-lab/alpaca"})
    sel = planner.finalize(e, "keyword", req, None, 0.5, "kw", [])
    assert sel["dataset"] is None
    assert sel["parameters"]["dataset_path"] == "tatsu-lab/alpaca"


# ------------------------------------------------------------------ runner (real execution)
def test_runner_executes_notebook_and_writes_status(tmp_path):
    nb = nbu.inject(_nb("smoke_test_cpu.ipynb"), {"epochs": 3, "sleep_per_epoch": 0.0,
                                                  "output_dir": "outputs"})
    (tmp_path / "notebook.ipynb").write_text(json.dumps(nb))
    runner = BACKEND / "app" / "finetune" / "remote_runner.py"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MLFLOW_")}
    r = subprocess.run([sys.executable, str(runner), "--timeout-hours", "0.05"], cwd=tmp_path,
                       env=env, capture_output=True, text=True, timeout=180)
    st = json.loads((tmp_path / "status.json").read_text())
    assert r.returncode == 0, (r.stdout, r.stderr, st)
    assert st["state"] == "completed"
    assert st["cells"]["completed"] == st["cells"]["total"] > 0
    assert st["custom"]["step"] == 3 and st["custom"]["total_steps"] == 3
    man = json.loads((tmp_path / "outputs_manifest.json").read_text())
    assert {f["path"] for f in man["files"]} == {"model.json", "metrics.json"}
    assert all(len(f["sha256"]) == 64 for f in man["files"])
    assert (tmp_path / "executed.ipynb").exists() and "epoch 3/3" in (tmp_path / "run.log").read_text()


def test_runner_reports_failed_cell(tmp_path):
    nb = {"cells": [{"cell_type": "markdown", "metadata": {}, "source": "## Boom"},
                    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                     "source": "raise ValueError('bad data')"}],
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    (tmp_path / "notebook.ipynb").write_text(json.dumps(nb))
    runner = BACKEND / "app" / "finetune" / "remote_runner.py"
    r = subprocess.run([sys.executable, str(runner)], cwd=tmp_path, capture_output=True, text=True,
                       timeout=180)
    st = json.loads((tmp_path / "status.json").read_text())
    assert r.returncode == 1 and st["state"] == "failed"
    assert st["failed_cell"]["ename"] == "ValueError" and "bad data" in st["failed_cell"]["evalue"]
    assert st["failed_cell"]["title"] == "Boom"
