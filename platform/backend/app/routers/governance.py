from __future__ import annotations

from fastapi import APIRouter

from ..governance import audit_log, budget_status, get_settings, update_settings

router = APIRouter(prefix="/api/v1", tags=["governance"])


@router.get("/governance")
def governance():
    return {"settings": get_settings(), "budget": budget_status()}


@router.put("/governance")
def update(patch: dict):
    return update_settings(patch)


@router.get("/platform-settings")
def platform_get():
    """Phase A stability/safety controls (effective values, incl. any env override)."""
    from ..governance import platform_settings, get_settings
    return {"effective": platform_settings(), "stored": get_settings()["platform"]}


@router.put("/platform-settings")
def platform_put(patch: dict):
    """Update stability/safety controls from the UI (Governance -> Platform Settings)."""
    from ..governance import update_settings as _us, platform_settings, audit
    _us({"platform": patch})
    audit("admin", "update", "platform_settings", detail=",".join(patch.keys()))
    return {"effective": platform_settings()}


@router.get("/audit")
def audit(limit: int = 100):
    return audit_log(limit)


@router.get("/observability/status")
def observability_status():
    """Diagnostics: which sink is active, tracking URI, and last logging result."""
    from ..observability import STATUS, _mlflow_enabled
    import importlib.util
    return {**STATUS, "mlflow_enabled_by_env": _mlflow_enabled(),
            "mlflow_installed": importlib.util.find_spec("mlflow") is not None,
            "OBSERVABILITY": __import__("os").getenv("OBSERVABILITY", ""),
            "MLFLOW_TRACKING_URI": __import__("os").getenv("MLFLOW_TRACKING_URI", "")}
