"""Model gateway — provider-agnostic, open-source only.

Providers are reached through their **APIs** via LiteLLM (MIT-licensed). There is
NO dependency on the Google Cloud / Vertex *platform* — Gemini is called through
the plain Google AI model API, Mistral through the Mistral API. Keys come from the
environment; nothing else is required.

  MODEL_PROVIDER = mock (default) | gemini | mistral
  GEMINI_API_KEY / MISTRAL_API_KEY   (only needed for the non-mock providers)

`to_litellm_model()` returns the string that both ADK's `LiteLlm` wrapper and a
direct `litellm.acompletion()` call understand, so the same mapping serves the
ADK runtime and the lightweight live runtime.
"""
from __future__ import annotations

import os

PROVIDER = os.getenv("MODEL_PROVIDER", "").lower()  # unset => must use a Model Endpoint


def to_litellm_model(model: str, provider: str | None = None) -> str:
    """Map a bare model name + provider to a LiteLLM model string."""
    p = (provider or PROVIDER).lower()
    if p == "mistral":
        return model if model.startswith("mistral/") else f"mistral/{model or 'mistral-large-latest'}"
    if p == "gemini":
        # AI model API (not Vertex). e.g. gemini/gemini-1.5-flash
        m = model or "gemini-1.5-flash"
        return m if m.startswith("gemini/") else f"gemini/{m}"
    return model


# default model name per provider, used when a card doesn't override
DEFAULTS = {
    "mistral": "mistral-large-latest",
    "gemini": "gemini-1.5-flash",
}
