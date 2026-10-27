"""Persistence layer.

A dependency-free JSON-file repository so the platform runs with zero infra.
The `Repo` interface is the seam: a Firestore or MongoDB adapter implements the
same four methods and is selected via config (Open Decision #2 in the spec).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


class Repo:
    """One JSON file per collection; last-write-wins, process-safe via a lock."""

    def __init__(self, collection: str, id_field: str):
        self.collection = collection
        self.id_field = id_field
        self.path = DATA_DIR / f"{collection}.json"
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.write_text("{}")

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text() or "{}")

    def _write(self, data: dict[str, Any]) -> None:
        # atomic: write to a temp file in the same dir, then replace — a crash
        # mid-write can never corrupt the live file (Phase A durability).
        import os
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent),
                                   prefix=f".{self.collection}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def upsert(self, obj: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            data[obj[self.id_field]] = obj
            self._write(data)
        return obj

    def get(self, key: str) -> dict[str, Any] | None:
        return self._read().get(key)

    def list(self, predicate=None) -> list[dict[str, Any]]:
        items: Iterable[dict[str, Any]] = self._read().values()
        return [i for i in items if (predicate is None or predicate(i))]

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._read()
            existed = data.pop(key, None) is not None
            self._write(data)
        return existed


class PgRepo:
    """PostgreSQL/JSONB implementation of the same Repo contract. One table per collection
    (id TEXT PRIMARY KEY, doc JSONB). Synchronous surface — bridges to asyncpg via db.py so
    all existing call sites stay unchanged."""

    def __init__(self, collection: str, id_field: str):
        self.collection = collection
        self.id_field = id_field

    def upsert(self, obj: dict[str, Any]) -> dict[str, Any]:
        from . import db
        db.doc_upsert(self.collection, obj[self.id_field], obj)
        return obj

    def get(self, key: str) -> dict[str, Any] | None:
        from . import db
        return db.doc_get(self.collection, key)

    def list(self, predicate=None) -> list[dict[str, Any]]:
        from . import db
        items = db.doc_list(self.collection)
        return [i for i in items if (predicate is None or predicate(i))]

    def delete(self, key: str) -> bool:
        from . import db
        return db.doc_delete(self.collection, key)


def make_repo(collection: str, id_field: str):
    """Return the configured repository backend (json | postgres). JSON is the default and the
    safe fallback; Postgres is used only when STORE_BACKEND=postgres."""
    from .config import SETTINGS
    if SETTINGS.get("store_backend") == "postgres":
        return PgRepo(collection, id_field)
    return Repo(collection, id_field)


# collection singletons (backend selected by STORE_BACKEND; JSON default)
agents = make_repo("agent_cards", "agent_id")
tools = make_repo("tool_specs", "id")
workflows = make_repo("workflows", "workflow_id")
runs = make_repo("runs", "run_id")
bundles = make_repo("bundles", "id")
schedules = make_repo("schedules", "id")
