"""Notebook helpers: read the papermill-style `parameters` cell and inject run parameters.

Convention (same as papermill): one code cell tagged `parameters` holds plain assignments with
literal defaults, optionally followed by a comment describing the parameter:

    base_model = "meta-llama/Llama-3.1-8B"   # HF model id
    epochs = 3
    learning_rate = 2e-4

At run time the platform inserts a new cell tagged `injected-parameters` right after it, so the
notebook's own defaults stay visible and the executed notebook records exactly what was used.
Notebooks without a parameters cell still run; parameters are then injected as the first cell.
"""
from __future__ import annotations

import ast
import copy
import json
from typing import Any

INJECTED_TAG = "injected-parameters"


def _src(cell: dict) -> str:
    s = cell.get("source", "")
    return "".join(s) if isinstance(s, list) else (s or "")


def _tags(cell: dict) -> list:
    return list(((cell.get("metadata") or {}).get("tags")) or [])


def parameters_cell_index(nb: dict) -> int | None:
    for i, c in enumerate(nb.get("cells", [])):
        if c.get("cell_type") == "code" and "parameters" in _tags(c):
            return i
    return None


def read_parameters(nb: dict) -> list[dict]:
    """[{name, default, type, description}] from the parameters cell (literal values only)."""
    idx = parameters_cell_index(nb)
    if idx is None:
        return []
    src = _src(nb["cells"][idx])
    lines = src.splitlines()
    out: list[dict] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in tree.body:
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            try:
                default = ast.literal_eval(value)
            except Exception:
                default = ast.get_source_segment(src, value) if value is not None else None
            line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
            desc = line.split("#", 1)[1].strip() if "#" in line else ""
            out.append({"name": t.id, "default": default,
                        "type": type(default).__name__ if default is not None else "NoneType",
                        "description": desc})
    return out


def coerce(value: Any, default: Any) -> Any:
    """Coerce an incoming value (often a string from an LLM or a form) to the default's type."""
    if default is None or value is None:
        return value
    try:
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "y", "on")
            return bool(value)
        if isinstance(default, int) and not isinstance(default, bool):
            return int(float(value)) if isinstance(value, (str, float)) else int(value)
        if isinstance(default, float):
            return float(value)
        if isinstance(default, (list, dict)) and isinstance(value, str):
            v = json.loads(value)
            return v if isinstance(v, type(default)) else default
        if isinstance(default, str):
            return value if isinstance(value, str) else json.dumps(value) if isinstance(value, (list, dict)) else str(value)
    except Exception:
        return value
    return value


def inject(nb: dict, params: dict, extra_comment: str = "") -> dict:
    """Return a copy of the notebook with an `injected-parameters` cell after the parameters cell
    (or first, if there is none). Values are written as Python literals (repr)."""
    nb = copy.deepcopy(nb)
    cells = nb.setdefault("cells", [])
    # drop an injected cell left over from a previous run of the same file
    cells[:] = [c for c in cells if INJECTED_TAG not in _tags(c)]
    lines = ["# Parameters injected by TCS Domain AI Studio"]
    if extra_comment:
        lines.append(f"# {extra_comment}")
    for k, v in params.items():
        if not str(k).isidentifier():
            continue
        lines.append(f"{k} = {v!r}")
    cell = {"cell_type": "code", "execution_count": None, "id": "studio-injected-parameters",
            "metadata": {"tags": [INJECTED_TAG]}, "outputs": [], "source": "\n".join(lines) + "\n"}
    idx = parameters_cell_index(nb)
    cells.insert(0 if idx is None else idx + 1, cell)
    return nb


def describe(nb: dict) -> dict:
    """Title + description from the first markdown cell, plus notebook-level metadata."""
    title, desc = "", ""
    for c in nb.get("cells", []):
        if c.get("cell_type") == "markdown":
            text = _src(c).strip()
            if not text:
                continue
            first, _, rest = text.partition("\n")
            title = first.lstrip("# ").strip()
            desc = rest.strip()
            break
    meta = ((nb.get("metadata") or {}).get("studio_finetune")) or {}
    n_code = sum(1 for c in nb.get("cells", []) if c.get("cell_type") == "code" and _src(c).strip())
    return {"title": title[:160], "description": desc[:1200], "metadata": meta, "code_cells": n_code}
