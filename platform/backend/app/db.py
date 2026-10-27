"""PostgreSQL connection layer for the JSONB document store.

Design: the rest of the app uses a *synchronous* Repo interface (upsert/get/list/delete),
so we run asyncpg on a dedicated background event loop and bridge sync->async. This keeps all
existing call sites unchanged while using the fast async driver underneath.

If asyncpg isn't installed or DATABASE_URL is unset, this module stays dormant and the app
falls back to the JSON store (see store.py). Nothing here runs unless STORE_BACKEND=postgres.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Optional

from .config import SETTINGS

_POOL: Any = None
_LOOP: Optional[asyncio.AbstractEventLoop] = None
_LOOP_THREAD: Optional[threading.Thread] = None
_LOCK = threading.RLock()
_READY = False


def _start_loop() -> asyncio.AbstractEventLoop:
    """Spin up a dedicated event loop in a background thread for asyncpg."""
    global _LOOP, _LOOP_THREAD
    if _LOOP and _LOOP.is_running():
        return _LOOP
    loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    t = threading.Thread(target=_run, name="pg-eventloop", daemon=True)
    t.start()
    _LOOP, _LOOP_THREAD = loop, t
    return loop


def _run(coro) -> Any:
    """Run a coroutine on the background loop from sync code, blocking for the result."""
    loop = _start_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result()


def is_enabled() -> bool:
    return SETTINGS.get("store_backend") == "postgres"


def wait_for_db(retries: int = 30, delay: float = 1.0) -> bool:
    """Block until Postgres accepts a connection (container startup ordering). Returns True on
    success. Raises if it never comes up so the operator sees a clear failure."""
    if not is_enabled():
        return False
    last = None
    for attempt in range(1, retries + 1):
        try:
            init_pool()
            _run(_ping())
            return True
        except Exception as e:  # pragma: no cover - depends on live DB
            last = e
            time.sleep(delay)
    raise RuntimeError(f"Postgres not reachable after {retries} attempts: {last}")


async def _ping() -> None:
    async with _POOL.acquire() as con:
        await con.execute("SELECT 1")


def init_pool() -> None:
    """Create the asyncpg pool once (idempotent)."""
    global _POOL, _READY
    if _POOL is not None:
        return
    with _LOCK:
        if _POOL is not None:
            return
        url = SETTINGS.get("database_url")
        if not url:
            raise RuntimeError("DATABASE_URL is required when STORE_BACKEND=postgres")
        import asyncpg  # optional dep; only needed for the postgres backend

        async def _mk():
            return await asyncpg.create_pool(
                dsn=url,
                min_size=SETTINGS.get("db_pool_min", 1),
                max_size=SETTINGS.get("db_pool_max", 10),
                command_timeout=30,
            )

        _POOL = _run(_mk())
        _READY = True


def execute(sql: str, *args) -> str:
    return _run(_execute(sql, *args))


async def _execute(sql: str, *args) -> str:
    async with _POOL.acquire() as con:
        return await con.execute(sql, *args)


def fetch(sql: str, *args) -> list[dict]:
    return _run(_fetch(sql, *args))


async def _fetch(sql: str, *args) -> list[dict]:
    async with _POOL.acquire() as con:
        rows = await con.fetch(sql, *args)
        return [dict(r) for r in rows]


def fetchrow(sql: str, *args) -> Optional[dict]:
    return _run(_fetchrow(sql, *args))


async def _fetchrow(sql: str, *args) -> Optional[dict]:
    async with _POOL.acquire() as con:
        r = await con.fetchrow(sql, *args)
        return dict(r) if r else None


def health() -> dict:
    if not is_enabled():
        return {"backend": "json", "ok": True}
    try:
        _run(_ping())
        return {"backend": "postgres", "ok": True}
    except Exception as e:  # pragma: no cover
        return {"backend": "postgres", "ok": False, "detail": str(e)}


def close() -> None:
    global _POOL
    if _POOL is not None:
        try:
            _run(_POOL.close())
        except Exception:
            pass
        _POOL = None


# ---------------------------------------------------------------------------
# Document-level operations (all Postgres SQL lives here; PgRepo just calls these).
# Table shape per collection:  id TEXT PRIMARY KEY, doc JSONB, updated_at timestamptz
# ---------------------------------------------------------------------------
import json as _json

_ENSURED: set[str] = set()


def ensure_table(table: str) -> None:
    if table in _ENSURED:
        return
    execute(
        f'CREATE TABLE IF NOT EXISTS "{table}" ('
        f'  id TEXT PRIMARY KEY,'
        f'  doc JSONB NOT NULL,'
        f'  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()'
        f')'
    )
    execute(f'CREATE INDEX IF NOT EXISTS "{table}_doc_gin" ON "{table}" USING GIN (doc)')
    _ENSURED.add(table)


def doc_upsert(table: str, key: str, obj: dict) -> dict:
    ensure_table(table)
    execute(
        f'INSERT INTO "{table}" (id, doc, updated_at) VALUES ($1, $2::jsonb, now()) '
        f'ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, updated_at = now()',
        key, _json.dumps(obj, default=str),
    )
    return obj


def doc_get(table: str, key: str) -> Optional[dict]:
    ensure_table(table)
    row = fetchrow(f'SELECT doc FROM "{table}" WHERE id = $1', key)
    if not row:
        return None
    d = row["doc"]
    return _json.loads(d) if isinstance(d, str) else d


def doc_list(table: str) -> list[dict]:
    ensure_table(table)
    rows = fetch(f'SELECT doc FROM "{table}"')
    out = []
    for r in rows:
        d = r["doc"]
        out.append(_json.loads(d) if isinstance(d, str) else d)
    return out


def doc_delete(table: str, key: str) -> bool:
    ensure_table(table)
    res = execute(f'DELETE FROM "{table}" WHERE id = $1', key)
    # asyncpg returns e.g. "DELETE 1"
    try:
        return int(str(res).split()[-1]) > 0
    except Exception:  # pragma: no cover
        return False

