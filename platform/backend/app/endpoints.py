"""Model Endpoints — UI-managed LLM connections (Azure OpenAI, OpenAI, Mistral, Gemini).

Lets users add a model endpoint entirely from the UI (endpoint URL, deployment,
api version, api key), test it, and select it when creating an agent. Credentials
are stored server-side in data/model_endpoints.json and returned MASKED to the UI.

Security note: for production, back this with a secret manager/vault. Keys never
leave the server unmasked; the runtime passes them straight to LiteLLM per call.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .schemas import _id  # id generator
from .store import DATA_DIR, make_repo

_eprepo = make_repo("model_endpoints", "id")


def _load() -> list[dict]:
    doc = _eprepo.get("_all")
    return doc.get("items", []) if doc else []


def _save(items: list[dict]) -> None:
    _eprepo.upsert({"id": "_all", "items": items})


def _mask(ep: dict) -> dict:
    k = ep.get("api_key", "") or ""
    return {**ep, "api_key": (f"••••{k[-4:]}" if len(k) >= 4 else "••••"), "has_key": bool(k)}


def list_endpoints() -> list[dict]:
    return [_mask(e) for e in _load()]


def get_full(eid: str) -> dict | None:
    return next((e for e in _load() if e["id"] == eid), None)


def add_endpoint(data: dict) -> dict:
    items = _load()
    ep = {
        "id": _id("ep"),
        "label": data.get("label") or f"{data.get('provider','model')} · {data.get('model','')}",
        "type": data.get("type", "chat"),      # chat | embedding | multimodal | ocr | rerank
        "provider": data["provider"],          # azure | openai | mistral | gemini
        "model": data["model"],                # deployment name (azure) or model id
        "api_base": data.get("api_base", ""),  # azure endpoint or custom base url
        "api_version": data.get("api_version", ""),  # azure only
        "api_key": data.get("api_key", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items.append(ep)
    _save(items)
    return _mask(ep)


def delete_endpoint(eid: str) -> bool:
    items = _load()
    n = [e for e in items if e["id"] != eid]
    _save(n)
    return len(n) != len(items)


def litellm_call_args(ep: dict) -> dict:
    """Return {model, params} for a LiteLLM/LiteLlm call from an endpoint record."""
    p = ep["provider"].lower()
    m = ep["model"]
    if p == "azure":
        model = m if m.startswith("azure/") else f"azure/{m}"
        params = {"api_key": ep.get("api_key"), "api_base": ep.get("api_base"),
                  "api_version": ep.get("api_version")}
    elif p == "openai":
        model = m if m.startswith("openai/") else f"openai/{m}"
        params = {"api_key": ep.get("api_key")}
        if ep.get("api_base"):
            params["api_base"] = ep["api_base"]
    elif p == "mistral":
        model = m if m.startswith("mistral/") else f"mistral/{m}"
        params = {"api_key": ep.get("api_key")}
    elif p == "gemini":
        model = m if m.startswith("gemini/") else f"gemini/{m}"
        params = {"api_key": ep.get("api_key")}
    else:
        model, params = m, {}
    return {"model": model, "params": {k: v for k, v in params.items() if v}}


def test_endpoint(eid: str) -> dict:
    ep = get_full(eid)
    if not ep:
        return {"ok": False, "detail": "endpoint not found"}
    try:
        import litellm
    except Exception:
        return {"ok": False, "live": False,
                "detail": "Saved. Live test needs the real runtime — install with "
                          "`pip install litellm` and start the backend (RUNTIME=adk)."}
    args = litellm_call_args(ep)
    try:
        litellm.completion(model=args["model"],
                           messages=[{"role": "user", "content": "ping"}],
                           max_tokens=5, **args["params"])
        return {"ok": True, "live": True, "detail": "Live call succeeded — endpoint is reachable."}
    except Exception as e:
        return {"ok": False, "live": True, "detail": str(e)[:400]}
