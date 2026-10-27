"""Conversation context compression — additive, flag-gated.

When enabled (governance.settings.compression.enabled), a long transcript is compressed into a
rolling summary + the most recent verbatim turns, so the context sent to the model stays small.
When disabled, nothing here is called and Chat behaves exactly as before.

Summarization uses a configured Model Endpoint; if none is set or the call fails, a deterministic
local fallback runs so the feature works offline (lower quality, but never blocks).
"""
from __future__ import annotations

import re

from .governance import get_settings


def _approx_tokens(text: str) -> int:
    # ~0.75 words per token heuristic (matches the RAG chunker's estimate)
    return max(0, int(len((text or "").split()) / 0.75))


def config() -> dict:
    return get_settings().get("compression", {}) or {}


def is_enabled() -> bool:
    return bool(config().get("enabled"))


def _render_turns(turns: list[dict]) -> str:
    """turns: [{role, text}] -> compact transcript block."""
    out = []
    for t in turns:
        role = (t.get("role") or "user").lower()
        who = "User" if role == "user" else "Assistant"
        out.append(f"{who}: {t.get('text','').strip()}")
    return "\n".join(out)


def _local_summarize(history_text: str, target_tokens: int) -> str:
    """Offline fallback: extractive compression that keeps decision-relevant lines.
    Not as good as a model, but deterministic and dependency-free."""
    lines = [l.strip() for l in history_text.splitlines() if l.strip()]
    keep_markers = ("user:", "assistant:")
    # score lines: prefer those with identifiers/numbers/decisions
    scored = []
    for l in lines:
        s = 0
        low = l.lower()
        if any(low.startswith(m) for m in keep_markers):
            s += 1
        if re.search(r"\d", l):                          # numbers / ids / dates
            s += 2
        if re.search(r"[/\\.]|https?://", l):            # paths / urls
            s += 1
        if re.search(r"\b(decide|will|must|need|goal|because|so that|chose|use|set|"
                      r"error|fix|todo|next|prefer|require)\b", low):
            s += 2
        scored.append((s, l))
    # keep highest-signal lines until the token budget is hit, preserving order
    budget = max(120, int(target_tokens))
    chosen, used = [], 0
    for _, l in sorted(scored, key=lambda x: x[0], reverse=True):
        t = _approx_tokens(l)
        if used + t > budget:
            continue
        chosen.append(l); used += t
    # restore original order
    order = {l: i for i, l in enumerate(lines)}
    chosen.sort(key=lambda l: order.get(l, 0))
    header = "[Compressed summary of earlier turns — local fallback]\n"
    return header + "\n".join(f"- {l}" for l in chosen)


def _model_summarize(history_text: str, cfg: dict) -> tuple[str, str]:
    """Summarize via a Model Endpoint. Returns (summary, method). Raises on hard failure."""
    from .endpoints import get_full, litellm_call_args
    ep = get_full(cfg.get("endpoint_id", ""))
    if not ep:
        raise RuntimeError("no compression endpoint configured")
    target = int(cfg.get("target_summary_tokens", 400))
    prompt = (cfg.get("prompt") or "").replace("{history}", history_text)\
        .replace("{target_tokens}", str(target))
    args = litellm_call_args(ep)
    import litellm
    resp = litellm.completion(
        model=args["model"],
        messages=[{"role": "user", "content": prompt}],
        **args.get("params", {}),
    )
    return (resp["choices"][0]["message"]["content"] or "").strip(), "model"


def compress(turns: list[dict]) -> dict:
    """Compress a transcript into {summary, recent_turns, tokens_before, tokens_after, method,
    compressed_count, applied}. `turns` is the full ordered list of {role, text}.

    If compression is disabled or the transcript is under the trigger, returns applied=False and
    the caller should use the transcript as-is (existing behavior)."""
    cfg = config()
    full_text = _render_turns(turns)
    tokens_before = _approx_tokens(full_text)

    if not cfg.get("enabled"):
        return {"applied": False, "summary": "", "recent_turns": turns,
                "tokens_before": tokens_before, "tokens_after": tokens_before,
                "method": "off", "compressed_count": 0}

    trigger = int(cfg.get("trigger_tokens", 6000))
    keep = int(cfg.get("keep_recent_turns", 6))

    over_threshold = tokens_before > trigger
    # Need at least one older turn to summarize. If we're over the token budget but there aren't
    # more than `keep` turns (e.g. a few very long turns), keep fewer so compression still applies.
    effective_keep = keep
    if over_threshold and len(turns) <= keep:
        effective_keep = max(1, len(turns) - 1)

    if not over_threshold:
        return {"applied": False, "summary": "", "recent_turns": turns,
                "original_turns": [], "tokens_before": tokens_before, "tokens_after": tokens_before,
                "trigger_tokens": trigger, "method": "under_threshold", "reason": "under_threshold",
                "compressed_count": 0}

    if len(turns) <= 1:
        # nothing older to summarize even after adjusting; report honestly
        return {"applied": False, "summary": "", "recent_turns": turns,
                "original_turns": [], "tokens_before": tokens_before, "tokens_after": tokens_before,
                "trigger_tokens": trigger, "method": "too_few_turns", "reason": "too_few_turns",
                "compressed_count": 0}

    older, recent = turns[:-effective_keep], turns[-effective_keep:]
    older_text = _render_turns(older)

    try:
        summary, method = _model_summarize(older_text, cfg)
    except Exception:
        summary = _local_summarize(older_text, int(cfg.get("target_summary_tokens", 400)))
        method = "local"

    recent_text = _render_turns(recent)
    # The canonical payload actually sent onward for further processing:
    # the rolling summary followed by the recent verbatim turns.
    compressed_context = (
        "[Summary of earlier conversation]\n" + summary.strip()
        + ("\n\n[Recent turns kept verbatim]\n" + recent_text if recent_text.strip() else "")
    )
    tokens_after = _approx_tokens(compressed_context)      # exact tokens of what we send
    return {
        "applied": True,
        "summary": summary,
        "recent_turns": recent,
        "compressed_context": compressed_context,          # AFTER text (Rule 4) — exactly what is sent
        "summary_tokens": _approx_tokens(summary),
        "recent_tokens": _approx_tokens(recent_text),
        "trigger_tokens": trigger,
        "tokens_before": tokens_before,                    # BEFORE = all previous conversation (Rule 1)
        "tokens_after": tokens_after,                      # AFTER = compressed history (Rule 2)
        "saved_pct": round(100 * (1 - tokens_after / tokens_before), 1) if tokens_before else 0,  # Rule 3
        "method": method,
        "reason": "applied",
        "compressed_count": len(older),
    }
