"""Central run executor (Phase A hardened).

Every run — from Chat, Workflow Studio, agent Test, Templates, or Schedules —
goes through `run_workflow()`. Guarantees:
  * bounded concurrency (a semaphore sized from Governance -> Platform Settings),
  * a per-run wall-clock timeout (settings-driven),
  * the run ALWAYS reaches a terminal state (pollers/chat never hang),
  * the run is ALWAYS recorded to the observability sink (MLflow/local).
All limits are read from the UI settings at run time, so they can be changed
from Governance -> Platform Settings without touching the backend.
"""
from __future__ import annotations

import asyncio
import logging

from .activity import bus, cancel
from .config import get_runtime
from .schemas import ActivityEvent, ActivityKind, Run, RunStatus
from .store import runs as runs_repo

_log = logging.getLogger("tcs.executor")

# concurrency gate; resized lazily to match the configured max_concurrent_runs
_sem: asyncio.Semaphore | None = None
_sem_size = 0


def _semaphore() -> asyncio.Semaphore:
    global _sem, _sem_size
    from .governance import platform_settings
    want = max(1, int(platform_settings().get("max_concurrent_runs", 5)))
    if _sem is None or want != _sem_size:
        _sem = asyncio.Semaphore(want)
        _sem_size = want
    return _sem


async def run_workflow(run: Run, wf) -> None:
    rid = run.run_id
    from .governance import platform_settings
    timeout = float(platform_settings().get("run_timeout_seconds", 180))

    async with _semaphore():
        try:
            await asyncio.wait_for(get_runtime().execute(run, wf), timeout=timeout)
        except asyncio.TimeoutError:
            run.status = RunStatus.failed
            run.error = f"Run exceeded the {int(timeout)}s time limit and was stopped."
            runs_repo.upsert(run.model_dump(by_alias=True))
            await _emit(rid, run.error)
        except Exception as e:  # never let a fire-and-forget task die silently
            run.status = RunStatus.failed
            run.error = f"Execution error: {e}"
            runs_repo.upsert(run.model_dump(by_alias=True))
            await _emit(rid, run.error)
        finally:
            cancel.clear(rid)
            _record(rid)


async def _emit(rid: str, msg: str) -> None:
    try:
        await bus.publish(ActivityEvent(run_id=rid, seq=bus.next_seq(rid),
                                        kind=ActivityKind.error, label=msg, level="error"))
    except Exception:
        pass


def _record(rid: str) -> None:
    try:
        latest = runs_repo.get(rid)
        if latest:
            from .observability import get_sink
            get_sink().record_run(Run(**latest))
    except Exception as e:
        _log.warning("observability logging failed: %s", e)
        try:
            from .observability import STATUS
            STATUS["last_error"] = f"record_run failed: {e}"
        except Exception:
            pass


def recover_orphans() -> int:
    """On startup, fail any run left 'running'/'pending' from a previous crash so
    nothing is stuck forever. Returns the number of runs recovered."""
    n = 0
    for r in runs_repo.list(lambda x: x.get("status") in ("running", "pending")):
        r["status"] = RunStatus.failed.value if hasattr(RunStatus.failed, "value") else "failed"
        r["error"] = "Interrupted by a server restart."
        runs_repo.upsert(r)
        n += 1
    if n:
        _log.info("recovered %d orphaned run(s) on startup", n)
    return n
