"""Notebook catalog: every .ipynb under the fine-tuning notebooks folder in File Storage,
described from its own content (first markdown cell, `studio_finetune` metadata, parameters
cell). Cached per file modification time so repeated runs stay cheap."""
from __future__ import annotations

import json
import threading

from .. import filestore
from . import config
from .notebook import describe, read_parameters

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()


def load_notebook(path: str) -> dict:
    return json.loads(filestore.read_bytes(path).decode("utf-8"))


def _entry(f: dict) -> dict:
    with _LOCK:
        hit = _CACHE.get(f["path"])
        if hit and hit[0] == f["modified"]:
            return hit[1]
    root = config.get()["notebooks_dir"].strip("/") + "/"
    e = {"name": f["path"][len(root):] if f["path"].startswith(root) else f["name"],
         "path": f["path"], "size": f["size"], "modified": f["modified"], "valid": True,
         "warnings": []}
    try:
        nb = load_notebook(f["path"])
        e.update(describe(nb))
        e["parameters"] = read_parameters(nb)
        if not e["parameters"]:
            e["warnings"].append("no cell tagged 'parameters' - the notebook will run with its "
                                 "own hard-coded values")
        if not e["title"]:
            e["warnings"].append("no markdown description - selection relies on the file name")
    except Exception as ex:
        e.update({"valid": False, "title": "", "description": "", "metadata": {},
                  "parameters": [], "code_cells": 0})
        e["warnings"].append(f"not a readable notebook: {ex}")
    with _LOCK:
        _CACHE[f["path"]] = (f["modified"], e)
    return e


def list_notebooks() -> list[dict]:
    folder = config.get()["notebooks_dir"]
    try:
        files = [f for f in filestore.walk(folder) if f["name"].endswith(".ipynb")
                 and "/.ipynb_checkpoints/" not in f["path"] and not f["name"].startswith(".")]
    except filestore.StorageError:
        return []
    return [_entry(f) for f in files]


def find(name_or_path: str) -> dict | None:
    """Match by catalog name, path, or bare file name (case-insensitive)."""
    q = (name_or_path or "").strip().strip("/").lower()
    if not q:
        return None
    items = [e for e in list_notebooks() if e["valid"]]
    for key in ("name", "path"):
        for e in items:
            if e[key].lower() == q:
                return e
    for e in items:
        stem = e["name"].lower()
        if stem.rsplit("/", 1)[-1] in (q, q + ".ipynb") or stem.removesuffix(".ipynb") == q:
            return e
    return None


def for_prompt(items: list[dict]) -> list[dict]:
    """Compact catalog view for the planner prompt."""
    out = []
    for e in items:
        if not e["valid"]:
            continue
        out.append({
            "notebook": e["name"], "title": e["title"], "description": e["description"][:700],
            "metadata": e["metadata"],
            "parameters": [{"name": p["name"], "default": p["default"], "type": p["type"],
                            **({"description": p["description"]} if p["description"] else {})}
                           for p in e["parameters"]][:40],
        })
    return out
