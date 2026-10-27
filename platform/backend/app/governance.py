"""Governance & Admin (spec §12), Phase 5 — all local, no cloud.

- Org settings: role (RBAC-lite), monthly budget, default guardrails.
- Audit log: append-only record of notable actions.
- Budget status: cumulative spend derived from the run store vs the configured cap.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .store import DATA_DIR, runs as runs_repo, make_repo

# governance state as singleton docs (backend follows STORE_BACKEND: json | postgres)
_gov = make_repo("governance", "id")

def _load_settings_doc() -> dict:
    doc = _gov.get("settings")
    return doc.get("value", {}) if doc else {}

def _save_settings_doc(value: dict) -> None:
    _gov.upsert({"id": "settings", "value": value})

def _load_audit() -> list:
    doc = _gov.get("audit")
    return doc.get("entries", []) if doc else []

def _save_audit(entries: list) -> None:
    _gov.upsert({"id": "audit", "entries": entries})

_DEFAULT = {
    "role": "admin",                       # viewer | builder | admin
    "monthly_token_budget": 5_000_000,
    "guardrails": {"pii_redaction": True, "content_filter": True,
                   "require_approval_destructive": True},
    "siem_export": False,
    # Phase A — stability & safety controls (all editable from the UI)
    "platform": {
        "max_concurrent_runs": 5,          # bounded run concurrency
        "run_timeout_seconds": 180,        # per-run wall-clock limit
        "retry_attempts": 2,               # transient model/tool retries
        "retry_backoff_seconds": 2,        # base backoff between retries
        "max_request_kb": 512,             # request/spec payload cap
        "ssrf_block_private": True,        # block private/metadata IPs for tool calls
        "ssrf_allowed_hosts": [],          # explicit internal hosts to permit
    },
    # Conversation context compression (OFF by default — when off, nothing changes anywhere)
    "compression": {
        "enabled": False,                  # master flag: behavior AND UI visibility
        "endpoint_id": "",                 # Model Endpoint used to summarize ("" = local fallback)
        "trigger_tokens": 6000,            # compress once the transcript exceeds ~this many tokens
        "keep_recent_turns": 6,            # most recent turns kept verbatim (never summarized)
        "target_summary_tokens": 400,      # soft budget for the rolling summary
        # Editable, scientific compression prompt. {history} is replaced with the turns being
        # compressed and {target_tokens} with the summary budget. Tune freely.
        "prompt": (
            "You are a context-compression engine for a multi-turn AI conversation. Your job is "
            "to losslessly preserve DECISION-RELEVANT information while discarding redundancy, so a "
            "downstream model can continue the conversation without access to the original turns.\n\n"
            "Compress the conversation below into a dense factual brief of at most ~{target_tokens} "
            "tokens. Follow these rules strictly:\n"
            "1. PRESERVE: user goals and constraints, decisions made, facts/values/identifiers "
            "(names, numbers, IDs, file paths, URLs), open questions, unresolved action items, and "
            "any commitments or preferences the user stated.\n"
            "2. PRESERVE causal/temporal order where it affects meaning; otherwise group by topic.\n"
            "3. ATTRIBUTE each point to the speaker when it matters (user asked / assistant did).\n"
            "4. DO NOT invent, infer, or resolve anything not present in the text. If something is "
            "ambiguous, keep it ambiguous.\n"
            "5. DROP greetings, filler, repeated restatements, and superseded intermediate steps "
            "(keep only the final resolved state, plus enough trail to explain it).\n"
            "6. Use compact structured notes (short lines / bullets), not prose. No preamble.\n\n"
            "Conversation to compress:\n{history}\n\n"
            "Return only the compressed brief."
        ),
    },
}


def get_settings() -> dict:
    s = dict(_DEFAULT)
    stored = _load_settings_doc()
    if stored:
        s.update(stored)
        # deep-merge the platform block so new defaults survive older files
        s["platform"] = {**_DEFAULT["platform"], **(stored.get("platform") or {})}
        s["compression"] = {**_DEFAULT["compression"], **(stored.get("compression") or {})}
    return s


def update_settings(patch: dict) -> dict:
    s = get_settings()
    if "platform" in patch and isinstance(patch["platform"], dict):
        s["platform"] = {**s["platform"], **patch.pop("platform")}
    s.update(patch)
    _save_settings_doc(s)
    return s


def platform_settings() -> dict:
    """Phase A controls, with optional env overrides for ops teams.
    The UI (Governance -> Platform Settings) is the primary source of truth."""
    import os
    p = dict(get_settings()["platform"])
    env = {
        "max_concurrent_runs": os.getenv("MAX_CONCURRENT_RUNS"),
        "run_timeout_seconds": os.getenv("RUN_TIMEOUT_SECONDS"),
        "retry_attempts": os.getenv("RETRY_ATTEMPTS"),
        "max_request_kb": os.getenv("MAX_REQUEST_KB"),
    }
    for k, v in env.items():
        if v is not None:
            try:
                p[k] = int(v)
            except ValueError:
                pass
    return p


def audit(actor: str, action: str, entity_type: str, entity_id: str = "", detail: str = "") -> None:
    log = _load_audit()
    log.insert(0, {"ts": datetime.now(timezone.utc).isoformat(), "actor": actor,
                   "action": action, "entity_type": entity_type,
                   "entity_id": entity_id, "detail": detail})
    _save_audit(log[:500])


def audit_log(limit: int = 100) -> list[dict]:
    return _load_audit()[:limit]


def budget_status() -> dict:
    used = sum(r.get("tokens", 0) for r in runs_repo.list() if not r.get("meta"))
    s = get_settings()
    cap = s["monthly_token_budget"]
    return {"used_tokens": used, "budget_tokens": cap,
            "pct": round(100 * used / cap, 1) if cap else 0.0,
            "remaining_tokens": cap - used,
            "over_budget": used > cap}
