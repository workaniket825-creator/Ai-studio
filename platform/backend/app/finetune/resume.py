"""Re-attach fine-tuning runs after a backend restart.

The job runs detached on the DSLab runtime, so a backend restart does not stop it. On startup,
runs whose job was launched and not finished (executor.reattachable_runs) are resumed through
the normal executor: the runtime skips nodes already recorded on the run, and the executor step
sees the existing job handle and goes straight back to monitoring.
"""
from __future__ import annotations

import asyncio
import logging

_log = logging.getLogger("tcs.finetune.resume")


async def resume_detached(delay: float = 3.0) -> int:
    await asyncio.sleep(delay)          # let startup finish (seeding, scheduler)
    from ..executor import reattachable_runs, run_workflow
    from ..schemas import Run, RunStatus, WorkflowGraph
    from ..store import runs as runs_repo
    from ..store import workflows as workflows_repo
    n = 0
    for r in reattachable_runs():
        wf = workflows_repo.get(r.get("workflow_id") or "")
        if not wf:
            r["status"] = RunStatus.failed.value
            r["error"] = "Interrupted by a server restart (workflow no longer exists)."
            runs_repo.upsert(r)
            continue
        run = Run(**r)
        _log.info("re-attaching fine-tuning run %s", run.run_id)
        asyncio.create_task(run_workflow(run, WorkflowGraph(**wf)))
        n += 1
    return n
