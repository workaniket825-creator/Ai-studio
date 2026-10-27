from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import SETTINGS
from .routers import (agents, bundles, chat, connectors, dsl, files, governance, insights, model_endpoints,
                     monitoring, mcp, ontology, rag, runs, schedules, tools, workflows)
from .seed import seed

app = FastAPI(
    title="TCS AI Studio",
    version="1.0",
    description="TCS AI Studio — build, run and observe agentic workflows.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS["cors_origins"] + ["*"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)


@app.middleware("http")
async def _limit_request_size(request: Request, call_next):
    # Phase A: reject oversized payloads (cap is UI-configurable in Platform Settings).
    # File uploads and document ingestion are exempt — they carry large bodies by design and
    # enforce their own size limits (filestore max_file_kb, RAG ingestion). Applying the small
    # JSON-request cap to them would (and did) block legitimate >512KB uploads.
    path = request.url.path
    upload_exempt = (
        path.endswith("/upload")
        or "/files/" in path
        or "/rag/" in path and ("ingest" in path or "documents" in path)
        or "/extract/file" in path
        or "/ssh-key" in path
        or "/import" in path
        or ("/dsl/runtimes/" in path and "/lab/" in path)   # JupyterLab proxy (notebook saves)
    )
    cl = request.headers.get("content-length")
    if not upload_exempt and cl and cl.isdigit():
        try:
            from .governance import platform_settings
            max_kb = int(platform_settings().get("max_request_kb", 512))
        except Exception:
            max_kb = 512
        if int(cl) > max_kb * 1024:
            return JSONResponse(status_code=413,
                                content={"detail": f"request too large (limit {max_kb} KB)"})
    return await call_next(request)

app.include_router(agents.router)
app.include_router(tools.router)
app.include_router(workflows.router)
app.include_router(runs.router)
app.include_router(monitoring.router)
app.include_router(bundles.router)
app.include_router(schedules.router)
app.include_router(governance.router)
app.include_router(insights.router)
app.include_router(connectors.router)
app.include_router(model_endpoints.router)
app.include_router(ontology.router)
app.include_router(mcp.router)
app.include_router(dsl.router)
app.include_router(files.router)
app.include_router(chat.router)
app.include_router(rag.router)


@app.on_event("startup")
async def _startup():
    # If configured for Postgres, wait for it to accept connections before seeding.
    try:
        from . import db
        if db.is_enabled():
            db.wait_for_db()
    except Exception as e:
        import logging
        logging.getLogger("startup").error("Postgres not ready: %s", e)
        raise
    seed()
    # Phase A: fail any runs left 'running' by a previous crash/restart
    try:
        from .executor import recover_orphans
        recover_orphans()
    except Exception:
        pass
    import asyncio
    from .routers.schedules import scheduler_loop
    asyncio.create_task(scheduler_loop())


@app.on_event("shutdown")
async def _shutdown():
    # graceful: mark still-running work as interrupted so nothing is left dangling
    try:
        from .executor import recover_orphans
        recover_orphans()
    except Exception:
        pass
    try:
        from .modules.data_science_lab.session import close_all_labs
        close_all_labs()
    except Exception:
        pass
    try:
        from . import db
        db.close()
    except Exception:
        pass


@app.get("/api/v1/health")
def health():
    from . import db
    return {"status": "ok", "runtime": SETTINGS["runtime"], "phase": "1",
            "store": db.health()}
