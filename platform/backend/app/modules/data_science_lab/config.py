"""Data Science Lab feature flag (spec §1, §15).

Ships DARK: `feature.data_science_lab.enabled` defaults off. Enable globally or
per-tenant from the UI (Governance / the Lab's own settings). Flag off => the module
is inert and the platform behaves exactly as before. Reuses the existing governance
settings store — no new config system.
"""
from __future__ import annotations

from ...governance import get_settings, update_settings

_DEFAULT = {
    "enabled": False,        # system default — ships dark
    "tenants": {},           # tenant -> bool override
}


def _cfg() -> dict:
    s = get_settings()
    d = s.get("data_science_lab") or {}
    return {**_DEFAULT, **d, "tenants": {**(d.get("tenants") or {})}}


def get_config() -> dict:
    return _cfg()


def is_enabled(tenant: str = "default") -> bool:
    c = _cfg()
    if tenant and tenant in c["tenants"]:
        return bool(c["tenants"][tenant])
    return bool(c["enabled"])


def set_enabled(enabled: bool) -> dict:
    c = _cfg()
    c["enabled"] = bool(enabled)
    update_settings({"data_science_lab": c})
    return c


def set_tenant_enabled(tenant: str, enabled: bool) -> dict:
    c = _cfg()
    c["tenants"][tenant] = bool(enabled)
    update_settings({"data_science_lab": c})
    return c
