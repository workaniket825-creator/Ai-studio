"""Runtime/config selection."""
from __future__ import annotations

import os


def get_runtime():
    """Real execution only. 'live' = LiteLLM over configured Model Endpoints /
    provider; 'adk' = full Google ADK runtime. No mock/fabricated runtime."""
    choice = os.getenv("RUNTIME", "live").lower()
    if choice == "adk":
        from .runtime.adk import AdkRuntime
        return AdkRuntime()
    from .runtime.live import LiveRuntime
    return LiveRuntime()


SETTINGS = {
    "runtime": os.getenv("RUNTIME", "live"),
    "mlflow_uri": os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"),
    "cors_origins": os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    # Persistence backend: "json" (default, zero-infra) or "postgres".
    "store_backend": os.getenv("STORE_BACKEND", "json").lower(),
    "database_url": os.getenv("DATABASE_URL", ""),
    "db_pool_min": int(os.getenv("DB_POOL_MIN", "1")),
    "db_pool_max": int(os.getenv("DB_POOL_MAX", "10")),
}
