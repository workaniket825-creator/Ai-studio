"""Model Registry (Data Science Lab tab).

Versions and stages the ML models trained in the Lab, and lets the agentic layer
consume a Production model as a tool. This REUSES the platform's existing MLflow — it's
the MLflow Model Registry, not a second system. When a live MLflow registry is reachable
it is the source of truth; otherwise a local mirror (dsl_models.json) keeps the feature
usable and honest, and syncs to MLflow when it becomes available.

Distinction that matters: these are TRAINED ML MODELS (e.g. a fraud classifier), entirely
separate from the foundation LLMs (GPT/Mistral/Gemini) configured under Model Endpoints.
Agents keep reasoning via Model Endpoints; a registered model is an OPTIONAL tool.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ...store import DATA_DIR
from ...schemas import _id

_FILE = DATA_DIR / "dsl_models.json"
STAGES = ("None", "Staging", "Production", "Archived")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    return json.loads(_FILE.read_text()) if _FILE.exists() else {"models": {}}


def _save(db: dict) -> None:
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(_FILE.parent), prefix=".dsl_models.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(db, f, indent=2, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, _FILE)


# ------------------------------- MLflow bridge (guarded) -------------------------------
def _client():
    """Return an MlflowClient if MLflow + a tracking URI are available, else None."""
    uri = os.getenv("MLFLOW_TRACKING_URI", "")
    if not uri:
        return None
    try:
        from mlflow.tracking import MlflowClient
        return MlflowClient(tracking_uri=uri)
    except Exception:
        return None


def source() -> str:
    return "mlflow" if _client() else "local"


# ------------------------------- read -------------------------------
def list_models() -> list[dict]:
    c = _client()
    if c:
        try:
            out = []
            for m in c.search_registered_models():
                versions = []
                for v in (m.latest_versions or []):
                    versions.append({"version": v.version, "stage": v.current_stage,
                                     "source": v.source, "run_id": v.run_id})
                out.append({"name": m.name, "description": m.description or "",
                            "versions": versions, "source": "mlflow"})
            return out
        except Exception:
            pass  # fall back to local
    return [{**m, "source": "local"} for m in _load()["models"].values()]


def get_model(name: str) -> dict | None:
    for m in list_models():
        if m["name"] == name:
            return m
    return None


# ------------------------------- write -------------------------------
def register_model(name: str, model_uri: str = "", description: str = "",
                   run_id: str = "", actor: str = "associate") -> dict:
    """Register a new model version. Uses MLflow if available; always mirrors locally."""
    c = _client()
    version = "1"
    if c and model_uri:
        try:
            import mlflow
            mv = mlflow.register_model(model_uri=model_uri, name=name)
            version = str(mv.version)
        except Exception:
            pass
    db = _load()
    m = db["models"].get(name) or {"name": name, "description": description,
                                   "versions": [], "created_at": _now()}
    m["description"] = description or m.get("description", "")
    # next local version number
    if not (c and model_uri):
        version = str(len(m["versions"]) + 1)
    m["versions"].append({"version": version, "stage": "None", "source": model_uri,
                          "run_id": run_id, "at": _now()})
    db["models"][name] = m
    _save(db)
    return {**m, "registered_version": version, "via": source()}


def transition_stage(name: str, version: str, stage: str, actor: str = "associate") -> dict:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    c = _client()
    if c:
        try:
            c.transition_model_version_stage(name=name, version=version, stage=stage,
                                             archive_existing_versions=(stage == "Production"))
        except Exception:
            pass
    db = _load()
    m = db["models"].get(name)
    if not m:
        raise ValueError("model not found")
    for v in m["versions"]:
        if str(v["version"]) == str(version):
            v["stage"] = stage
        elif stage == "Production" and v["stage"] == "Production":
            v["stage"] = "Archived"   # only one Production version
    _save(db)
    return {"name": name, "version": version, "stage": stage, "via": source()}


def production_version(name: str) -> dict | None:
    m = get_model(name)
    if not m:
        return None
    for v in m.get("versions", []):
        if v.get("stage") == "Production":
            return v
    return None


def delete_model(name: str) -> bool:
    db = _load()
    if name in db["models"]:
        del db["models"][name]
        _save(db)
        return True
    return False


# ------------------------------- invocation (agent tool path, guarded) -------------------------------
def invoke(name: str, inputs, serving_url: str = "") -> dict:
    """Call a registered model's serving endpoint (MLflow serving / any REST scorer).
    Guarded: honest message if no serving URL is configured."""
    url = serving_url or os.getenv(f"MODEL_SERVING_{name.upper()}", "")
    if not url:
        return {"ok": False, "detail": f"no serving endpoint configured for '{name}'. "
                                       "Serve it (mlflow models serve / your scorer) and set the "
                                       "serving URL to enable agent calls."}
    try:
        import urllib.request
        from ...security_net import check_url, BlockedURLError
        try:
            check_url(url)
        except BlockedURLError as e:
            return {"ok": False, "detail": str(e)}
        body = json.dumps({"inputs": inputs}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"ok": True, "result": r.read().decode()[:4000]}
    except Exception as e:
        return {"ok": False, "detail": f"model call failed: {e}"}
