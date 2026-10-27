"""Explicit MLflow GenAI tracing.

autolog only reliably instruments litellm's *sync* path; our runtimes use async
`acompletion`, so we create spans explicitly. Every agent model call becomes a
span under MLflow's GenAI -> Traces view, with inputs, outputs, and token counts.
All helpers are safe no-ops when MLflow tracing isn't configured/installed.
"""
from __future__ import annotations

import contextlib
import logging
import os

_log = logging.getLogger("tcs.tracing")


def enabled() -> bool:
    return bool(os.getenv("MLFLOW_TRACKING_URI")
                or os.getenv("OBSERVABILITY", "").lower() == "mlflow")


@contextlib.contextmanager
def span(name: str, inputs: dict | None = None, attributes: dict | None = None):
    """Open a GenAI span; yields the span (or None when tracing is off)."""
    if not enabled():
        yield None
        return
    try:
        import mlflow
    except Exception:
        yield None
        return
    try:
        with mlflow.start_span(name=name) as sp:
            try:
                if sp is not None and inputs is not None:
                    sp.set_inputs(inputs)
                if sp is not None and attributes:
                    sp.set_attributes(attributes)
            except Exception:
                pass
            yield sp
    except Exception as e:  # never let tracing break execution
        _log.warning("trace span '%s' failed: %s", name, e)
        yield None


def set_outputs(sp, outputs: dict) -> None:
    try:
        if sp is not None:
            sp.set_outputs(outputs)
    except Exception:
        pass
