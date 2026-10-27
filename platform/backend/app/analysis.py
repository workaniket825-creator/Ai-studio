"""Scenario analysis helpers (security + document processing).

- Security: pattern-based detection of prompt injection / jailbreak / exfiltration
  over trace text via `scan_text` (a real pattern detector).
- Artifacts: write markdown files agents can produce as deliverables.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .store import DATA_DIR

ARTIFACTS_DIR = DATA_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

INJECTION_PATTERNS = [
    "ignore previous instructions", "ignore all previous", "disregard the above",
    "reveal your system prompt", "print your instructions", "you are now",
    "do anything now", "dan mode", "developer mode", "bypass your", "jailbreak",
    "exfiltrate", "send the api key", "leak the", "override your guardrails",
]


def scan_text(text: str) -> list[dict]:
    """Real detector: match known attack patterns in a piece of trace text."""
    low = (text or "").lower()
    hits = []
    for pat in INJECTION_PATTERNS:
        if pat in low:
            kind = ("jailbreak" if pat in ("do anything now", "dan mode", "developer mode", "jailbreak")
                    else "data_exfiltration" if pat in ("exfiltrate", "send the api key", "leak the")
                    else "prompt_injection")
            hits.append({"type": kind, "pattern": pat})
    return hits


def write_markdown(run_id: str, name: str, content: str) -> dict:
    """Persist a markdown artifact and return an artifact record with a text preview.
    Also mirrors the file into the shared File Storage (runs/<run_id>/) so every
    generated file collects in one browsable place."""
    d = ARTIFACTS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(content)
    try:
        from . import filestore
        filestore.write_text(f"runs/{run_id}/{name}", content, actor="agent")
    except Exception:
        pass  # never let mirroring break a run
    return {"id": name, "name": name, "uri": f"/api/v1/runs/{run_id}/artifacts/{name}",
            "mime": "text/markdown", "preview": content}


