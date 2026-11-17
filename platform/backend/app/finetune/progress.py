"""Structured fine-tuning progress, persisted on run.progress.

The activity bus is in-memory and keeps 500 events; a fine-tuning run lasts hours and the user
may close the browser. So the source of truth for progress is the run document itself: Chat and
the Run view poll it, and it survives page reloads and backend restarts.
"""
from __future__ import annotations

from datetime import datetime, timezone

STAGES = [
    ("plan", "Select notebook"),
    ("stage", "Stage on DSLab"),
    ("launch", "Launch job"),
    ("execute", "Execute notebook"),
    ("collect", "Collect outputs"),
    ("mlflow", "Log to MLflow"),
    ("report", "Report"),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure(run) -> dict:
    p = run.progress
    if p.get("kind") != "finetune":
        p.clear()
        p.update({"kind": "finetune", "stage": "plan", "state": "running",
                  "stages": [{"key": k, "label": l, "status": "pending"} for k, l in STAGES],
                  "warnings": [], "created_at": now()})
    return p


def stage(run, key: str, status: str, detail: str = "") -> None:
    """Mark a stage active|done|failed|skipped (and make it the current stage when active)."""
    p = ensure(run)
    for s in p["stages"]:
        if s["key"] == key:
            if status == "active" and s["status"] != "active":
                s["started_at"] = now()
            if status in ("done", "failed", "skipped"):
                s["ended_at"] = now()
            s["status"] = status
            if detail:
                s["detail"] = detail[:300]
    if status == "active":
        p["stage"] = key
    p["updated_at"] = now()


def set(run, **kw) -> None:   # noqa: A001 - module-level helper name
    p = ensure(run)
    p.update(kw)
    p["updated_at"] = now()


def warn(run, msg: str) -> None:
    p = ensure(run)
    if msg not in p["warnings"]:
        p["warnings"].append(msg[:400])
        p["updated_at"] = now()


def finish(run, state: str) -> None:
    """state: completed | failed | cancelled. Pending stages after a failure become skipped."""
    p = ensure(run)
    p["state"] = state
    for s in p["stages"]:
        if s["status"] == "active":
            s["status"] = "done" if state == "completed" else "failed"
            s["ended_at"] = now()
        elif s["status"] == "pending" and state != "completed":
            s["status"] = "skipped"
    p["updated_at"] = now()
