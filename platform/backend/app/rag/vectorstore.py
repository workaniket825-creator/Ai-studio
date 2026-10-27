"""Vector store abstraction.
  - pgvector (Postgres) when psycopg + a DATABASE_URL are available (production).
  - local JSON-backed store otherwise (offline-safe; brute-force cosine).
Same interface either way: upsert(pid, chunks), query(pid, vec, k), drop(pid), stats(pid).
Each chunk: {id, pipeline_id, doc_id, text, vector, metadata}.
"""
from __future__ import annotations

import json
import math
import os

from ..store import DATA_DIR

_LOCAL_DIR = DATA_DIR / "rag_vectors"
_LOCAL_DIR.mkdir(exist_ok=True)


def _pg_available() -> bool:
    if not os.getenv("DATABASE_URL"):
        return False
    try:
        import psycopg  # noqa: F401
        return True
    except Exception:
        return False


# --------------------------- local JSON backend (offline-safe) ---------------------------
def _local_path(pid: str):
    return _LOCAL_DIR / f"{pid}.json"


def _local_load(pid: str) -> list[dict]:
    p = _local_path(pid)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _local_save(pid: str, rows: list[dict]) -> None:
    _local_path(pid).write_text(json.dumps(rows))


def _cosine(a: list[float], b: list[float]) -> float:
    # vectors are pre-normalized → dot product == cosine
    return sum(x * y for x, y in zip(a, b))


def _local_upsert(pid: str, chunks: list[dict]) -> int:
    rows = _local_load(pid)
    rows.extend(chunks)
    _local_save(pid, rows)
    return len(chunks)


def _local_query(pid: str, vec: list[float], k: int, min_score: float) -> list[dict]:
    rows = _local_load(pid)
    scored = []
    for r in rows:
        s = _cosine(vec, r.get("vector", []))
        if s >= min_score:
            scored.append({**{kk: vv for kk, vv in r.items() if kk != "vector"}, "score": round(s, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]


def _local_drop(pid: str) -> None:
    p = _local_path(pid)
    if p.exists():
        p.unlink()


def _local_stats(pid: str) -> dict:
    rows = _local_load(pid)
    return {"vectors": len(rows), "backend": "local-json",
            "bytes": _local_path(pid).stat().st_size if _local_path(pid).exists() else 0}


# --------------------------- pgvector backend (production) ---------------------------
def _pg_conn():
    import psycopg
    return psycopg.connect(os.getenv("DATABASE_URL"))


def _vec_literal(vec: list[float]) -> str:
    """pgvector accepts a text literal like '[0.1,0.2,...]' cast to ::vector — this avoids
    needing numpy or the pgvector python adapter, and never hits list-adaptation errors."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _pg_ensure_schema(conn) -> None:
    # The vector type must be enabled per-database before a vector column can be created.
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute("""CREATE TABLE IF NOT EXISTS rag_chunks (
        id text PRIMARY KEY, pipeline_id text, doc_id text, text text,
        metadata jsonb, embedding vector)""")
    conn.execute("CREATE INDEX IF NOT EXISTS rag_chunks_pipe ON rag_chunks(pipeline_id)")


def _pg_upsert(pid: str, chunks: list[dict]) -> int:
    with _pg_conn() as conn:
        _pg_ensure_schema(conn)
        with conn.cursor() as cur:
            for c in chunks:
                vec = c.get("vector") or []
                if not vec:
                    continue
                cur.execute(
                    "INSERT INTO rag_chunks (id,pipeline_id,doc_id,text,metadata,embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s::vector) "
                    "ON CONFLICT (id) DO UPDATE SET embedding=EXCLUDED.embedding, "
                    "text=EXCLUDED.text, metadata=EXCLUDED.metadata",
                    (c["id"], pid, c.get("doc_id"), c["text"],
                     json.dumps(c.get("metadata", {})), _vec_literal(vec)))
        conn.commit()
    return len([c for c in chunks if c.get("vector")])


def _pg_query(pid: str, vec: list[float], k: int, min_score: float) -> list[dict]:
    lit = _vec_literal(vec)
    with _pg_conn() as conn:
        _pg_ensure_schema(conn)
        rows = conn.execute(
            "SELECT id, doc_id, text, metadata, 1-(embedding <=> %s::vector) AS score "
            "FROM rag_chunks WHERE pipeline_id=%s ORDER BY embedding <=> %s::vector LIMIT %s",
            (lit, pid, lit, k)).fetchall()
    out = []
    for r in rows:
        if r[4] is not None and r[4] >= min_score:
            out.append({"id": r[0], "doc_id": r[1], "text": r[2],
                        "metadata": r[3], "score": round(float(r[4]), 4)})
    return out


# --------------------------- unified interface ---------------------------
def upsert(pid: str, chunks: list[dict]) -> int:
    return _pg_upsert(pid, chunks) if _pg_available() else _local_upsert(pid, chunks)


def query(pid: str, vec: list[float], k: int = 5, min_score: float = 0.0) -> list[dict]:
    return _pg_query(pid, vec, k, min_score) if _pg_available() else _local_query(pid, vec, k, min_score)


def drop(pid: str) -> None:
    if _pg_available():
        try:
            with _pg_conn() as conn:
                conn.execute("DELETE FROM rag_chunks WHERE pipeline_id=%s", (pid,))
                conn.commit()
        except Exception:
            pass
    _local_drop(pid)


def stats(pid: str) -> dict:
    if _pg_available():
        try:
            with _pg_conn() as conn:
                n = conn.execute("SELECT count(*) FROM rag_chunks WHERE pipeline_id=%s", (pid,)).fetchone()[0]
            return {"vectors": n, "backend": "pgvector"}
        except Exception:
            pass
    return _local_stats(pid)


def backend_name() -> str:
    return "pgvector" if _pg_available() else "local-json"
