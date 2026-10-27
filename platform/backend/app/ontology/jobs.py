"""In-memory extraction-job registry: real-time progress + cancellation for ontology
entity/relationship extraction. Jobs are ephemeral (process-local) — fine for progress UX;
the extracted data itself is persisted durably by the store."""
from __future__ import annotations

import threading
import time

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def create(job_id: str, source: str = "") -> dict:
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id, "status": "running", "phase": "starting",
            "processed": 0, "total": 0, "entities": 0, "edges": 0,
            "source": source, "cancelled": False, "error": "",
            "started_at": time.time(), "result": None,
        }
        return dict(_JOBS[job_id])


def update(job_id: str, **kw) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kw)


def get(job_id: str) -> dict | None:
    with _LOCK:
        return dict(_JOBS[job_id]) if job_id in _JOBS else None


def cancel(job_id: str) -> bool:
    with _LOCK:
        if job_id in _JOBS and _JOBS[job_id]["status"] == "running":
            _JOBS[job_id]["cancelled"] = True
            return True
        return False


def is_cancelled(job_id: str) -> bool:
    with _LOCK:
        return bool(_JOBS.get(job_id, {}).get("cancelled"))


def finish(job_id: str, status: str, result=None, error: str = "") -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(status=status, result=result, error=error,
                                 phase="cancelled" if status == "cancelled" else "done")


def cleanup(older_than_s: int = 3600) -> None:
    now = time.time()
    with _LOCK:
        for k in [k for k, v in _JOBS.items()
                  if v["status"] != "running" and now - v["started_at"] > older_than_s]:
            _JOBS.pop(k, None)
