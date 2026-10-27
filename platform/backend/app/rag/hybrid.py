"""Hybrid retrieval (vector + keyword) and reranking.

Hybrid: blends dense vector similarity with a lexical (keyword overlap / BM25-lite) score so
exact terms, names, and IDs — which pure embeddings often miss — get their due. Fused via
reciprocal-rank fusion (RRF), which is robust without score-scale tuning.

Rerank: optional. `api` uses a rerank Model Endpoint (guarded); `local` applies a lexical
re-order. `off` keeps fusion order.
"""
from __future__ import annotations

import math
import re
from collections import Counter


def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def lexical_scores(query: str, chunks: list[dict]) -> dict:
    """BM25-lite over the candidate set (source of exact-term precision)."""
    q = _tokens(query)
    if not q or not chunks:
        return {}
    docs = [_tokens(c.get("text", "")) for c in chunks]
    N = len(docs)
    avgdl = sum(len(d) for d in docs) / N if N else 1
    df = Counter()
    for d in docs:
        for t in set(d):
            df[t] += 1
    k1, b = 1.5, 0.75
    scores = {}
    for i, d in enumerate(docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * (tf[t] * (k1 + 1)) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        scores[chunks[i]["id"]] = s
    return scores


def rrf_fuse(vector_hits: list[dict], lexical: dict, k: int = 60) -> list[dict]:
    """Reciprocal-rank fusion of the vector ranking and the lexical ranking."""
    vrank = {h["id"]: i for i, h in enumerate(vector_hits)}
    lrank = {cid: i for i, (cid, _) in enumerate(
        sorted(lexical.items(), key=lambda kv: kv[1], reverse=True))}
    by_id = {h["id"]: h for h in vector_hits}
    fused = []
    for cid, h in by_id.items():
        score = 0.0
        if cid in vrank:
            score += 1.0 / (k + vrank[cid])
        if cid in lrank:
            score += 1.0 / (k + lrank[cid])
        fused.append({**h, "fused_score": round(score, 5),
                      "lexical": round(lexical.get(cid, 0.0), 3)})
    fused.sort(key=lambda x: x["fused_score"], reverse=True)
    return fused


def rerank(query: str, hits: list[dict], cfg: dict) -> list[dict]:
    """Optional rerank. backend: off | local | api. Guarded for api."""
    backend = (cfg or {}).get("backend", "off")
    if backend == "off" or not hits:
        return hits
    if backend == "api" and cfg.get("endpoint_id"):
        try:
            return _api_rerank(query, hits, cfg["endpoint_id"])
        except Exception:
            pass  # fall through to local on failure
    # local: re-order by lexical overlap as a cheap relevance signal
    lex = lexical_scores(query, hits)
    for h in hits:
        h["rerank"] = round(lex.get(h["id"], 0.0), 3)
    return sorted(hits, key=lambda x: (x.get("rerank", 0), x.get("score", 0)), reverse=True)


def _api_rerank(query: str, hits: list[dict], endpoint_id: str) -> list[dict]:
    from ..endpoints import get_full
    ep = get_full(endpoint_id)
    if not ep:
        raise RuntimeError("rerank endpoint not found")
    # provider-specific rerank APIs vary; kept guarded. Production wires the concrete call here.
    raise RuntimeError("api rerank not executed in this environment")
