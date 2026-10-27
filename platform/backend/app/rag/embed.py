"""Embedding backends. Selection is by pipeline config:
  - backend="local": sentence-transformers if installed; else a deterministic hashing
    embedder (offline-safe, lets the whole pipeline run + be tested without heavy deps).
  - backend="api": call a Model Endpoint of type 'embedding' (Azure/OpenAI/etc.) via LiteLLM.
Returns L2-normalized float vectors so cosine == dot product downstream.
"""
from __future__ import annotations

import hashlib
import math


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _hash_embed(text: str, dim: int) -> list[float]:
    """Deterministic bag-of-hashed-tokens embedding — no deps, stable, good enough to prove
    retrieval end-to-end offline. NOT for production quality (use local ST or an API)."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 else -1.0
        vec[idx] += sign
    return _normalize(vec)


_ST_MODEL = None


def _local_embed(texts: list[str], dim: int) -> list[list[float]]:
    global _ST_MODEL
    try:
        from sentence_transformers import SentenceTransformer  # heavy, optional
        if _ST_MODEL is None:
            _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        embs = _ST_MODEL.encode(texts, normalize_embeddings=True)
        return [list(map(float, e)) for e in embs]
    except Exception:
        # offline / not installed → deterministic fallback at the configured dim
        return [_hash_embed(t, dim) for t in texts]


def _api_embed(texts: list[str], endpoint_id: str) -> list[list[float]]:
    from ..endpoints import get_full, litellm_call_args
    ep = get_full(endpoint_id)
    if not ep:
        raise RuntimeError("embedding endpoint not found")
    args = litellm_call_args(ep)
    import litellm
    resp = litellm.embedding(model=args["model"], input=texts, **args.get("params", {}))
    return [_normalize(list(d["embedding"])) for d in resp["data"]]


def embed_texts(texts: list[str], cfg: dict) -> tuple[list[list[float]], str]:
    """Return (vectors, method). method is 'api', 'local-st', or 'local-hash' for transparency."""
    if not texts:
        return [], "none"
    backend = cfg.get("backend", "local")
    dim = int(cfg.get("dim", 384))
    if backend == "api" and cfg.get("endpoint_id"):
        try:
            return _api_embed(texts, cfg["endpoint_id"]), "api"
        except Exception:
            # fail safe to local so ingestion never hard-crashes; surfaced in method
            return _local_embed(texts, dim), "local-fallback"
    vecs = _local_embed(texts, dim)
    method = "local-st" if _ST_MODEL is not None else "local-hash"
    return vecs, method


def embed_query(text: str, cfg: dict) -> list[float]:
    vecs, _ = embed_texts([text], cfg)
    return vecs[0] if vecs else []
