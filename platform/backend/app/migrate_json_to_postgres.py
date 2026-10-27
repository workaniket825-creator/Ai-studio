"""One-time, idempotent migration of the JSON file store into Postgres.

Reads every data/*.json collection and imports its documents into the matching Postgres table
via the same document operations the app uses. Safe to re-run: upserts by id, so re-running
produces no duplicates and no changes for already-migrated docs.

Usage (inside the backend container, with Postgres reachable):
    STORE_BACKEND=postgres DATABASE_URL=postgresql://user:pass@postgres:5432/tcs \\
        python -m app.migrate_json_to_postgres

Singleton-doc collections (governance, model_endpoints, ontology_db) are stored under fixed ids
by the app; this script imports whatever ids exist in the JSON files verbatim, so those map
across unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import db
from .store import DATA_DIR

# collection file (without .json) -> id field used inside each doc
# For plain Repo collections the file is a dict{ id -> doc }; we import values.
KNOWN_ID_FIELDS = {
    "agent_cards": "agent_id",
    "tool_specs": "id",
    "workflows": "workflow_id",
    "runs": "run_id",
    "bundles": "id",
    "schedules": "id",
    "rag_pipelines": "id",
    "rag_documents": "id",
    "chat_conversations": "id",
}


def _iter_docs(payload):
    """JSON store files are dict{id: doc}. Yield (id, doc)."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(v, dict):
                yield k, v


def migrate() -> dict:
    if not db.is_enabled():
        print("STORE_BACKEND is not 'postgres' — nothing to do.", file=sys.stderr)
        return {}
    db.wait_for_db()
    summary = {}
    for path in sorted(Path(DATA_DIR).glob("*.json")):
        collection = path.stem
        try:
            payload = json.loads(path.read_text() or "{}")
        except Exception as e:
            print(f"  ! skip {collection}: unreadable ({e})")
            continue

        count = 0
        # Repo-style file: dict{id: doc}
        if isinstance(payload, dict) and all(isinstance(v, dict) for v in payload.values()) and payload:
            for key, doc in _iter_docs(payload):
                db.doc_upsert(collection, key, doc)
                count += 1
        # Singleton/list-style files handled by the app's own singleton ids:
        #   governance.json / model_endpoints.json / ontology_db.json — these are already
        #   written by the app under fixed ids once it runs on Postgres, but if a legacy raw
        #   file exists we wrap it as a single doc so nothing is lost.
        elif isinstance(payload, (dict, list)) and payload:
            db.doc_upsert(collection, "_legacy_import", {"value": payload})
            count = 1

        summary[collection] = count
        print(f"  migrated {collection}: {count} docs")
    return summary


if __name__ == "__main__":
    s = migrate()
    total = sum(s.values())
    print(f"\nMigration complete: {total} documents across {len(s)} collections.")
