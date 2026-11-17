"""Fine-tuning planner: requirement -> (notebook, parameters, dataset).

1. Explicit choices from the request/template form always win (notebook, dataset, parameters).
2. Otherwise a model reads the requirement + the notebook catalog and returns a JSON selection.
3. The selection is VALIDATED: the notebook must exist in the catalog, parameters must be ones the
   notebook declares (values coerced to the declared type), datasets must exist in File Storage.
4. With no model (or an unusable reply) a deterministic keyword match is used instead — the same
   reuse-first idea as the Workflow Designer — and the method is reported honestly.
If nothing fits, the step fails with the list of available notebooks; it never invents one.
"""
from __future__ import annotations

import json
import re

from .. import filestore
from . import catalog, config
from .notebook import coerce

DATASET_PARAM_NAMES = ("dataset_path", "data_path", "train_file", "train_path", "train_data",
                       "dataset_file", "data_file", "train_dataset", "dataset")

_STOP = set("a an the and or for to of in on with by my our using use from into this that be is "
            "are it as at fine tune tuning finetune finetuning model train training please run "
            "notebook want need".split())

INSTRUCTIONS = """Return ONLY a JSON object, no prose:
{"notebook": "<exact 'notebook' value from the catalog, or null if none fits>",
 "confidence": <0.0-1.0>,
 "reason": "<why this notebook fits: task, model family, method, data, hardware>",
 "parameters": {"<parameter declared by THAT notebook>": <value>},
 "dataset": "<a File Storage path from the dataset list, or null>",
 "dataset_parameter": "<the notebook parameter that receives the dataset path, or null>",
 "warnings": ["<assumptions, missing information or risks the user should know>"]}
Rules:
- Choose only from the catalog. Never invent notebooks or parameter names.
- Only set parameters the request states or clearly implies; omit the rest so the notebook's
  own defaults apply. Use the declared types (numbers as numbers, booleans as true/false).
- Respect every explicit choice listed under "Explicit choices".
- If no notebook fits the request, set "notebook" to null and explain why in "reason"."""


def _text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v) if v is not None else ""


def request_from_input(inp: dict) -> dict:
    inp = inp if isinstance(inp, dict) else {"input": inp}
    text = (_text(inp.get("requirement")) or _text(inp.get("message")) or _text(inp.get("goal"))
            or _text(inp.get("input"))).strip()
    params = inp.get("parameters") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params) if params.strip() else {}
        except Exception:
            params = {}
    return {"text": text, "notebook": str(inp.get("notebook") or "").strip(),
            "dataset": str(inp.get("dataset") or "").strip(),
            "parameters": params if isinstance(params, dict) else {},
            "runtime_id": str(inp.get("runtime_id") or inp.get("runtime") or "").strip()}


def dataset_candidates(limit: int = 80) -> list[dict]:
    c = config.get()
    skip = (c["notebooks_dir"] + "/", c["runs_dir"] + "/")
    out: list[dict] = []
    for prefix in (c["datasets_dir"], "shared"):
        try:
            for f in filestore.walk(prefix, limit=limit):
                if not f["path"].startswith(skip) and not f["name"].endswith(".ipynb"):
                    out.append({"path": f["path"], "size": f["size"]})
        except filestore.StorageError:
            pass
    return out[:limit]


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _STOP and len(t) > 1}


def keyword_pick(text: str, items: list[dict]) -> tuple[dict | None, float, list]:
    q = _tokens(text)
    scored = []
    for e in items:
        if not e["valid"]:
            continue
        meta = e.get("metadata") or {}
        hay = " ".join([e["name"], e["title"], e["description"],
                        json.dumps(meta)] + [p["name"] for p in e["parameters"]])
        h = _tokens(hay)
        # metadata keywords count double: they are written for exactly this purpose
        mk = _tokens(json.dumps(meta))
        score = len(q & h) + len(q & mk)
        scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] == 0:
        return None, 0.0, [e["name"] for _s, e in scored[:3]]
    top = scored[0][0]
    return scored[0][1], round(min(1.0, top / max(3, len(q))), 2), [e["name"] for _s, e in scored[1:3]]


def kv_pairs(text: str, names: list[str]) -> dict:
    """key=value / key: value pairs in free text, for declared parameter names only."""
    out = {}
    for n in names:
        m = re.search(rf"(?<![\w.]){re.escape(n)}\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)", text)
        if m:
            v = m.group(1).strip().strip("\"'")
            out[n] = v
    return out


def _dataset_entry(path: str) -> dict | None:
    if not path:
        return None
    try:
        st = filestore.stat(path.strip("/"))
    except filestore.StorageError:
        return None
    return {"path": st["path"], "size": st["size"]} if st and st["type"] == "file" else None


def finalize(entry: dict, method: str, req: dict, raw: dict | None, confidence: float,
             reason: str, alternatives: list) -> dict:
    """Validated selection. Unknown parameters are dropped with a warning."""
    declared = {p["name"]: p for p in entry["parameters"]}
    warnings: list[str] = []
    params: dict = {}
    proposed = dict((raw or {}).get("parameters") or {})
    proposed.update(kv_pairs(req["text"], list(declared)))
    proposed.update(req["parameters"])                      # explicit always wins
    for k, v in proposed.items():
        if k in declared:
            params[k] = coerce(v, declared[k]["default"])
        else:
            warnings.append(f"ignored parameter `{k}` - `{entry['name']}` does not declare it")
    if not declared and proposed:
        warnings.append("this notebook has no 'parameters' cell, so the values are injected as "
                        "new variables at the top of the notebook")
        params = {k: v for k, v in proposed.items() if str(k).isidentifier()}

    ds_path = req["dataset"] or ((raw or {}).get("dataset") or "")
    dataset = _dataset_entry(ds_path) if ds_path else None
    ds_param = (raw or {}).get("dataset_parameter") or ""
    if ds_path and not dataset:
        # not in File Storage: pass it through untouched (e.g. a Hugging Face dataset id or a
        # path that already exists on the runtime)
        guess = ds_param if ds_param in declared else next((n for n in DATASET_PARAM_NAMES if n in declared), "")
        if guess and guess not in params:
            params[guess] = ds_path
            warnings.append(f"dataset `{ds_path}` is not in File Storage - passed as-is to `{guess}`")
        elif not guess:
            warnings.append(f"dataset `{ds_path}` is not in File Storage and the notebook has no "
                            f"dataset parameter - ignored")
    if dataset and ds_param not in declared:
        ds_param = next((n for n in DATASET_PARAM_NAMES if n in declared), "")
    warnings += [str(w) for w in ((raw or {}).get("warnings") or []) if w][:8]
    return {"notebook": entry["name"], "path": entry["path"], "title": entry["title"],
            "method": method, "confidence": confidence, "reason": reason[:1500],
            "parameters": params, "dataset": dataset,
            "dataset_parameter": ds_param if dataset else "",
            "warnings": warnings, "alternatives": alternatives,
            "declared_parameters": entry["parameters"]}


def build_prompt(req: dict, items: list[dict]) -> str:
    explicit = {k: req[k] for k in ("notebook", "dataset", "parameters") if req.get(k)}
    return (f"Fine-tuning request:\n{req['text'] or '(none given)'}\n\n"
            f"Explicit choices from the user (must be respected): "
            f"{json.dumps(explicit) if explicit else 'none'}\n\n"
            f"Notebook catalog (JSON):\n{json.dumps(catalog.for_prompt(items), default=str)[:24000]}\n\n"
            f"Datasets in File Storage:\n{json.dumps(dataset_candidates(), default=str)[:4000]}\n\n"
            + INSTRUCTIONS)
