"""Observability & Monitoring (spec §8), Phase 2.

Two responsibilities, both open-source and cloud-free:

1. **Aggregation & trace assembly** that always works from the local run store +
   the activity ring buffer — so the Monitoring dashboards and trace tree render
   with zero external setup.

2. A pluggable **sink** for durable tracing. `LocalSink` (default) is a no-op
   because the data already lives in the store. `MLflowSink` logs params/metrics
   to a self-hosted **MLflow** (Apache-2.0) when `OBSERVABILITY=mlflow` — MLflow
   can use a local file store (`./mlruns`) or any SQL backend; no cloud required.

The real ADK runtime additionally emits OpenTelemetry spans that MLflow 3.6+ can
ingest at /v1/traces (spec §8.1); that path activates with RUNTIME=adk and does
not change anything here.
"""
from __future__ import annotations

import logging
import os
import statistics
from typing import Any

from .activity import bus
from .schemas import ActivityEvent

_log = logging.getLogger("tcs.observability")

# live diagnostics, surfaced via GET /observability/status
STATUS: dict[str, Any] = {"sink": "local", "tracking_uri": "", "experiment": "",
                          "last_logged": "", "last_error": ""}


# ------------------------------- aggregation -------------------------------
def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return round(s[k], 1)


def overview(runs: list[dict[str, Any]]) -> dict[str, Any]:
    real = [r for r in runs if not r.get("meta")]
    done = [r for r in real if r["status"] in ("succeeded", "failed", "cancelled")]
    ok = [r for r in done if r["status"] == "succeeded"]
    latencies = [r.get("latency_ms", 0) for r in ok if r.get("latency_ms")]

    by_wf: dict[str, dict[str, Any]] = {}
    for r in real:
        name = r.get("workflow_name") or "—"
        b = by_wf.setdefault(name, {"name": name, "runs": 0, "ok": 0, "tok": 0})
        b["runs"] += 1
        b["ok"] += 1 if r["status"] == "succeeded" else 0
        b["tok"] += r.get("tokens", 0)
    by_workflow = [
        {"name": b["name"], "runs": b["runs"],
         "success_rate": round(100 * b["ok"] / b["runs"], 1) if b["runs"] else 0,
         "tokens": b["tok"]}
        for b in sorted(by_wf.values(), key=lambda x: -x["runs"])
    ]

    return {
        "total_runs": len(real),
        "succeeded": len(ok),
        "success_rate": round(100 * len(ok) / len(done), 1) if done else 0.0,
        "total_tokens": sum(r.get("tokens", 0) for r in real),
        "total_input_tokens": sum(r.get("input_tokens", 0) for r in real),
        "total_output_tokens": sum(r.get("output_tokens", 0) for r in real),
        "avg_tokens": round(statistics.mean([r.get("tokens", 0) for r in real])) if real else 0,
        "p50_latency_ms": _pct(latencies, 50),
        "p95_latency_ms": _pct(latencies, 95),
        "by_workflow": by_workflow,
    }


def build_trace(run: dict[str, Any]) -> dict[str, Any]:
    """Assemble a nested span tree from the run's activity events (spec §8.2)."""
    events: list[ActivityEvent] = bus.replay(run["run_id"])
    root = {"name": run.get("workflow_name", "run"), "kind": "run",
            "status": run["status"], "input_tokens": run.get("input_tokens", 0),
            "output_tokens": run.get("output_tokens", 0),
            "tokens": run.get("tokens", 0), "latency_ms": run.get("latency_ms", 0),
            "children": []}
    current = None
    for e in events:
        if e.kind.value == "agent_enter":
            current = {"name": e.agent, "kind": "agent", "children": [],
                       "in_tokens": e.in_tokens or 0, "out_tokens": 0}
            root["children"].append(current)
        elif e.kind.value in ("tool_call", "reasoning", "verification", "approval_pending") and current:
            current["children"].append({"name": e.label, "kind": e.kind.value})
        elif e.kind.value == "token" and current:
            current["out_tokens"] += e.token_delta or 0
        elif e.kind.value == "agent_exit" and current:
            current = None
    if not root["children"]:  # trace requested before/without a live stream
        root["children"] = [{"name": "(no captured spans — run may predate this session)",
                             "kind": "note"}]
    return root


# --------------------------------- sinks ----------------------------------
class LocalSink:
    name = "local"

    def record_run(self, run) -> None:
        return  # data already persisted in the store


class MLflowSink:
    name = "mlflow"

    def __init__(self):
        import mlflow  # guarded; only imported when observability is enabled
        self.mlflow = mlflow
        uri = os.getenv("MLFLOW_TRACKING_URI")
        if uri:
            mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "tcs-ai-studio"))
        # GenAI tracing: auto-capture every LiteLLM call as a span so runs show
        # under MLflow's GenAI -> Traces view (not just the experiment/runs view).
        self.tracing = False
        try:
            mlflow.litellm.autolog()
            self.tracing = True
            _log.info("MLflow GenAI tracing enabled (litellm.autolog)")
        except Exception as e:
            _log.warning("MLflow litellm.autolog unavailable (%s); metrics still logged", e)

    def record_run(self, run) -> None:
        """Log the whole workflow run: run-level metrics, the full activity trace,
        per-agent nested runs, node outputs, and any generated deliverable files."""
        import os as _os
        from .activity import bus
        m = self.mlflow

        events = [e.model_dump() for e in bus.replay(run.run_id)]
        node_outputs = getattr(run, "node_outputs", []) or []
        artifacts = getattr(run, "artifacts", []) or []
        verdict = (getattr(run, "verification", {}) or {}).get("verdict", "")

        try:
            m.end_run()  # clear any dangling active run from a previous failure
        except Exception:
            pass

        with m.start_run(run_name=run.workflow_name or run.run_id):
            m.set_tags({"run_id": run.run_id, "workflow": run.workflow_name,
                        "workflow_id": getattr(run, "workflow_id", "") or "",
                        "status": run.status, "verdict": verdict})
            m.log_params({
                "node_count": len(node_outputs),
                "agents": ",".join(n.get("agent", "") for n in node_outputs) or "-",
                "steers": len(getattr(run, "steers", []) or []),
            })
            m.log_metrics({
                "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
                "tokens": run.tokens, "latency_ms": run.latency_ms,
                "num_agents": len(node_outputs),
                "success": 1 if run.status == "succeeded" else 0,
            })
            try:
                m.log_dict({"events": events}, "trace/activity_events.json")
                m.log_dict({"node_outputs": node_outputs}, "trace/node_outputs.json")
            except Exception:
                pass
            from .analysis import ARTIFACTS_DIR
            for a in artifacts:
                p = _os.path.join(str(ARTIFACTS_DIR), run.run_id, a.get("name", ""))
                if _os.path.exists(p):
                    try:
                        m.log_artifact(p, artifact_path="deliverables")
                    except Exception:
                        pass
            for i, n in enumerate(node_outputs, 1):
                with m.start_run(run_name=f"{i}. {n.get('agent', 'agent')}", nested=True):
                    m.log_params({"agent": n.get("agent", ""),
                                  "steps": len(n.get("steps", []))})
                    m.log_metrics({"in_tokens": n.get("in_tokens", 0),
                                   "out_tokens": n.get("out_tokens", 0)})
                    try:
                        m.log_text(n.get("output", ""), f"agents/{i}_output.md")
                        if n.get("steps"):
                            m.log_text("\n".join(n["steps"]), f"agents/{i}_steps.txt")
                    except Exception:
                        pass
        _log.info("MLflow: logged run %s (%s) to %s", run.run_id, run.status,
                  os.getenv("MLFLOW_TRACKING_URI", "./mlruns"))
        STATUS["last_logged"] = run.run_id
        STATUS["last_error"] = ""


def _mlflow_enabled() -> bool:
    # enabled if explicitly asked OR a tracking URI is configured
    return (os.getenv("OBSERVABILITY", "").lower() == "mlflow"
            or bool(os.getenv("MLFLOW_TRACKING_URI")))


_sink_cache = None


def get_sink():
    global _sink_cache
    if _sink_cache is not None:
        return _sink_cache
    if _mlflow_enabled():
        try:
            _sink_cache = MLflowSink()
            STATUS.update(sink="mlflow", tracking_uri=os.getenv("MLFLOW_TRACKING_URI", "./mlruns"),
                          experiment=os.getenv("MLFLOW_EXPERIMENT", "tcs-ai-studio"), last_error="")
            _log.info("Observability sink = MLflow (%s)", STATUS["tracking_uri"])
            return _sink_cache
        except Exception as e:
            STATUS.update(sink="local", last_error=f"MLflow init failed: {e}")
            _log.warning("MLflow init failed, using local sink: %s", e)
    _sink_cache = LocalSink()
    STATUS.update(sink="local")
    return _sink_cache


sink = get_sink()
