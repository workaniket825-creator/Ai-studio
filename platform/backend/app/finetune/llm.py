"""Model calls for the fine-tuning planner/reporter handlers.

Resolution mirrors LiveRuntime._resolve_model: the agent card's Model Endpoint, else the env
provider. If the card has no endpoint (e.g. it was seeded before any endpoint existed) the
first chat endpoint is used, and that is reported. Every call is wrapped in an MLflow GenAI span
like any other agent call.
"""
from __future__ import annotations

import asyncio
import json
import re


class NoModel(RuntimeError):
    pass


def resolve(card: dict) -> tuple[str, dict, str]:
    """(litellm model, params, note). Raises NoModel when nothing is configured."""
    from ..endpoints import get_full, list_endpoints, litellm_call_args
    from ..models import PROVIDER, to_litellm_model
    mc = (card or {}).get("model_config") or {}
    eid, note = mc.get("endpoint_id"), ""
    if not eid and not PROVIDER:
        chats = [e for e in list_endpoints() if (e.get("type") or "chat") == "chat"]
        if chats:
            eid = chats[0]["id"]
            note = (f"agent has no Model Endpoint - used "
                    f"'{chats[0].get('label') or chats[0].get('name') or eid}'")
    if eid:
        ep = get_full(eid)
        if ep:
            a = litellm_call_args(ep)
            return a["model"], a["params"], note
    if PROVIDER:   # env-based provider fallback, exactly like LiveRuntime._resolve_model
        return to_litellm_model(mc.get("model") or "", mc.get("provider") or PROVIDER), {}, note
    raise NoModel("no Model Endpoint is configured for this agent (Model Endpoints screen)")


async def complete(card: dict, system: str, user: str, run_id: str, agent: str,
                   max_tokens: int = 1500) -> tuple[str, int, int, str]:
    """Return (text, in_tokens, out_tokens, note)."""
    import litellm
    from .. import tracing
    from ..governance import platform_settings
    model, params, note = resolve(card)
    params = {**params}
    params.setdefault("temperature", ((card or {}).get("model_config") or {}).get("temperature", 0.1))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ps = platform_settings()
    attempts = max(1, int(ps.get("retry_attempts", 2)) + 1)
    backoff = float(ps.get("retry_backoff_seconds", 2))
    with tracing.span(f"agent:{agent}", inputs={"messages": messages},
                      attributes={"model": str(model), "run_id": run_id, "agent": agent}) as sp:
        last = None
        for i in range(attempts):
            try:
                resp = await litellm.acompletion(model=model, messages=messages,
                                                 max_tokens=max_tokens, **params)
                break
            except Exception as e:
                last = e
                if i < attempts - 1:
                    await asyncio.sleep(backoff * (i + 1))
        else:
            raise last
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        u = getattr(resp, "usage", None)
        tin = getattr(u, "prompt_tokens", 0) or 0
        tout = getattr(u, "completion_tokens", 0) or 0
        tracing.set_outputs(sp, {"output": text, "in_tokens": tin, "out_tokens": tout})
    return text, tin, tout, note


def parse_json(text: str) -> dict | None:
    """First JSON object in a model reply (tolerates ```json fences and prose around it)."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cands = [m.group(1)] if m else []
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    cands.append(text[start:i + 1])
                    break
    for c in cands:
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v
        except Exception:
            continue
    return None
