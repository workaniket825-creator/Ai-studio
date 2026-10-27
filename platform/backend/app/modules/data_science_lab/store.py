"""Data Science Lab store (spec §10) — isolated `dsl_*` objects only.

All new state lives in its own JSON files (dsl_runtimes / dsl_templates), droppable
without touching any core table. Runs & models are NOT stored here — they live in the
existing MLflow; we only keep foreign references where useful (§10.3).
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
from datetime import datetime, timezone

from ...store import DATA_DIR
from ...schemas import _id

_RUNTIMES = DATA_DIR / "dsl_runtimes.json"
_TEMPLATES = DATA_DIR / "dsl_templates.json"

RUNTIME_STATUS = ("idle", "running", "unreachable", "not_configured")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _mask_secret(ref: str) -> str:
    # We only ever store a reference (vault://...). Never a raw secret. Show as-is.
    return ref or ""


# ------------------------------- dsl_runtimes (§10.1) -------------------------------
def list_runtimes(tenant: str | None = None) -> list[dict]:
    rows = list(_load(_RUNTIMES).values())
    if tenant:
        rows = [r for r in rows if r.get("tenant_id", "default") == tenant]
    # never expose the passphrase to the client (the key path/ref is fine)
    return [public_view(r) for r in rows]


_SECRET_KEYS = {"ssh_passphrase", "jupyter_token"}


def public_view(r: dict) -> dict:
    """Runtime as returned to the UI: secrets removed, presence flags added."""
    out = {k: v for k, v in r.items() if k not in _SECRET_KEYS}
    out["has_jupyter_token"] = bool(r.get("jupyter_token"))
    return out


def ensure_jupyter_token(rid: str) -> str:
    """Return the runtime's Jupyter token, generating one for runtimes created before tokens."""
    db = _load(_RUNTIMES)
    r = db.get(rid)
    if not r:
        return ""
    if not r.get("jupyter_token"):
        r["jupyter_token"] = secrets.token_urlsafe(32)
        _save(_RUNTIMES, db)
    return r["jupyter_token"]


def set_internal(rid: str, patch: dict) -> dict | None:
    """Server-side fields the public PUT endpoint must not touch."""
    db = _load(_RUNTIMES)
    r = db.get(rid)
    if not r:
        return None
    for k in ("agent_mcp_server", "jupyter_token"):
        if k in patch:
            r[k] = patch[k]
    _save(_RUNTIMES, db)
    return r


def get_runtime(rid: str) -> dict | None:
    return _load(_RUNTIMES).get(rid)


def create_runtime(data: dict, actor: str = "associate") -> dict:
    db = _load(_RUNTIMES)
    provider = data.get("provider", "ssh")
    r = {
        "id": _id("dsl_rt"),
        "tenant_id": data.get("tenant_id", "default"),
        "name": data.get("name", "Untitled runtime"),
        "provider": provider,                       # brev | aws | azure | ssh
        "host": data.get("host", ""),
        "ssh_user": data.get("ssh_user", "ubuntu"),
        "ssh_port": int(data.get("ssh_port", 22)),
        "region": data.get("region", ""),
        "runtime_image": data.get("runtime_image", "nvcr.io/nvidia/rapidsai/base:24.10-cuda12.5-py3.11"),
        "workdir": data.get("workdir", "/home/ubuntu/workspace"),
        "persistent_volume_ref": data.get("persistent_volume_ref", ""),
        "jupyter_port": int(data.get("jupyter_port", 8888)),
        "python_path": data.get("python_path", "python3"),   # interpreter with jupyterlab+papermill
        "jupyter_cmd": data.get("jupyter_cmd", ""),
        "has_uploaded_key": False,
        "idle_timeout_min": int(data.get("idle_timeout_min", 30)),
        "can_manage_lifecycle": provider in ("brev", "aws", "azure"),
        "auth_secret_ref": data.get("auth_secret_ref", ""),   # reference only (§11)
        "backup_remote": data.get("backup_remote", ""),
        "mlflow_uri": data.get("mlflow_uri", os.getenv("MLFLOW_TRACKING_URI", "")),
        # Phase 3 — shared lab (spec §12): multi-user via JupyterHub + MIG slicing
        "multiuser": bool(data.get("multiuser", False)),
        "hub_url": data.get("hub_url", ""),
        "mig_enabled": bool(data.get("mig_enabled", False)),
        "mig_profile": data.get("mig_profile", ""),   # e.g. "1g.10gb"
        "status": "not_configured",
        "last_test": "", "last_error": "",
        "gpu_type": data.get("gpu_type", ""),
        # per-runtime Jupyter token: generated server-side, never returned to the UI. The lab
        # proxy injects it, so the browser and agents are authenticated without seeing it.
        "jupyter_token": secrets.token_urlsafe(32),
        "agent_mcp_server": "",
        "created_by": actor, "created_at": _now(),
    }
    db[r["id"]] = r
    _save(_RUNTIMES, db)
    return r


def update_runtime(rid: str, patch: dict) -> dict | None:
    db = _load(_RUNTIMES)
    r = db.get(rid)
    if not r:
        return None
    allowed = {"name", "host", "ssh_user", "ssh_port", "region", "runtime_image", "workdir",
               "persistent_volume_ref", "jupyter_port", "idle_timeout_min", "auth_secret_ref",
               "backup_remote", "mlflow_uri", "status", "last_test", "last_error", "gpu_type",
               "multiuser", "hub_url", "mig_enabled", "mig_profile",
               "python_path", "jupyter_cmd", "has_uploaded_key", "ssh_passphrase"}
    for k, v in patch.items():
        if k in allowed:
            r[k] = v
    if "provider" in patch:  # keep lifecycle flag consistent if provider changes
        r["provider"] = patch["provider"]
        r["can_manage_lifecycle"] = patch["provider"] in ("brev", "aws", "azure")
    _save(_RUNTIMES, db)
    return r


def delete_runtime(rid: str) -> bool:
    db = _load(_RUNTIMES)
    if rid not in db:
        return False
    del db[rid]
    _save(_RUNTIMES, db)
    return True


# ------------------------------- dsl_templates (§10.2) -------------------------------
def list_templates() -> list[dict]:
    return list(_load(_TEMPLATES).values())


def create_template(data: dict, actor: str = "associate") -> dict:
    db = _load(_TEMPLATES)
    t = {
        "id": _id("dsl_tpl"),
        "name": data.get("name", "Untitled template"),
        "version": data.get("version", "0.1.0"),
        "repo_path": data.get("repo_path", ""),
        "config_schema": data.get("config_schema", {}),
        "runtime_image": data.get("runtime_image", ""),
        "tags": data.get("tags", []),
        "status": data.get("status", "draft"),        # tried_and_tested | draft
        "changelog": data.get("changelog", ""),
        "description": data.get("description", ""),
        "ci_status": data.get("ci_status", "untested"),  # untested|passing|failing (§8 quality gate)
        "ci_detail": "",
        "versions": [{"version": data.get("version", "0.1.0"),
                      "changelog": data.get("changelog", ""), "at": _now(), "by": actor}],
        "created_by": actor, "created_at": _now(),
    }
    db[t["id"]] = t
    _save(_TEMPLATES, db)
    return t


def bump_template_version(tid: str, version: str, changelog: str, actor: str = "associate") -> dict | None:
    """Save a new semver version + changelog entry (spec §8)."""
    db = _load(_TEMPLATES)
    t = db.get(tid)
    if not t:
        return None
    t["version"] = version
    t["changelog"] = changelog
    t.setdefault("versions", []).append(
        {"version": version, "changelog": changelog, "at": _now(), "by": actor})
    _save(_TEMPLATES, db)
    return t


def set_template_ci(tid: str, status: str, detail: str = "") -> dict | None:
    db = _load(_TEMPLATES)
    t = db.get(tid)
    if not t:
        return None
    t["ci_status"] = status
    t["ci_detail"] = detail
    if status == "passing" and t["status"] == "draft":
        pass  # promotion stays a manual, reviewed action
    _save(_TEMPLATES, db)
    return t


def delete_template(tid: str) -> bool:
    db = _load(_TEMPLATES)
    if tid not in db:
        return False
    del db[tid]
    _save(_TEMPLATES, db)
    return True
