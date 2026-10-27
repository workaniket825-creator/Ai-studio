"""Runtime abstraction (the ADK seam).

`AgentRuntime.execute()` is the only thing the API layer knows about. Two
implementations:
  - MockRuntime  : runs today with zero credentials; streams realistic
                   ActivityEvents so the live "thinking" UX is fully testable.
  - AdkRuntime   : the real thing (google-adk + Runner + AutoTracingPlugin +
                   ActivityStreamPlugin). Selected when RUNTIME=adk and creds exist.

Swapping is a config change, not a rewrite — exactly as the spec promises.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas import Run, WorkflowGraph


class AgentRuntime(ABC):
    name: str = "base"

    @abstractmethod
    async def execute(self, run: Run, workflow: WorkflowGraph) -> None:
        """Execute the compiled workflow, publishing ActivityEvents to the bus
        and updating the run's status/metrics in the store as it goes."""
        raise NotImplementedError
