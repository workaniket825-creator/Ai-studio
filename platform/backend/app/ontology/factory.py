"""Provider factory — the ONE place the ontology flag is read on the agent path
(spec A§2, A§13). The planner/executor/orchestration never see the flag; they always
receive a ContextProvider and consume a ContextBundle.

Also records per-request telemetry (spec A§7): provider used, whether ontology was
actually applied, latency, and token/cost context (filled by the runtime).
"""
from __future__ import annotations

import logging

from .contract import ContextProvider
from .plain import PlainProvider
from . import ontology_config as cfg

_log = logging.getLogger("tcs.ontology")

# in-memory telemetry ring (also mirrored to MLflow via the runtime span attributes)
_TELEMETRY: list[dict] = []


def get_context_provider(tenant: str = "default", workflow_id: str = "",
                         query_text: str = "") -> ContextProvider:
    """Return the active provider for this tenant/workflow. Default: PlainProvider
    (identical to today's behavior). Only flips to OntologyProvider when enabled AND
    at least one published graph is selected — otherwise stays plain (fallback)."""
    try:
        if cfg.is_enabled(tenant, workflow_id):
            from .ontology_provider import build_for
            prov = build_for(tenant, workflow_id, query_text)
            # Use original direct access to check if graphs matched
            if prov._graph_ids:
                return prov
            _log.info("ontology enabled but no published graph matched -> plain")
    except Exception as e:               # never let ontology break the agent path
        _log.warning("provider selection failed, using plain: %s", e)
    return PlainProvider()


def record_telemetry(entry: dict) -> None:
    _TELEMETRY.append(entry)
    if len(_TELEMETRY) > 2000:
        del _TELEMETRY[:1000]


def telemetry(limit: int = 200) -> list[dict]:
    return list(reversed(_TELEMETRY[-limit:]))
