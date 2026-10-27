"""Configurable chunking. Structure-aware where possible; fixed/recursive fallback.
Token counts use a simple word-based estimate offline; a real tokenizer can be swapped in."""
from __future__ import annotations

import re


def _approx_tokens(text: str) -> int:
    # ~0.75 words per token heuristic; good enough for stats/budgeting offline
    return max(1, int(len(text.split()) / 0.75))


def _split_sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text.strip())


def chunk_text(text: str, cfg: dict, section: str = "") -> list[dict]:
    """Return a list of {text, tokens, chars, section} chunks per the chunking config."""
    strategy = cfg.get("strategy", "recursive")
    size = int(cfg.get("size", 800))            # target size in tokens
    overlap = int(cfg.get("overlap", 120))
    text = (text or "").strip()
    if not text:
        return []

    if strategy == "by_heading":
        # split on markdown-ish headings, then size-bound each section
        parts = re.split(r"\n(?=#{1,6}\s)", text)
        out: list[dict] = []
        for part in parts:
            head = part.splitlines()[0].lstrip("# ").strip() if part.startswith("#") else section
            out.extend(_size_bound(part, size, overlap, head))
        return out
    if strategy == "fixed":
        return _size_bound(text, size, overlap, section, sentence_aware=False)
    # default: recursive/sentence-aware
    return _size_bound(text, size, overlap, section, sentence_aware=True)


def _size_bound(text: str, size: int, overlap: int, section: str,
                sentence_aware: bool = True) -> list[dict]:
    units = _split_sentences(text) if sentence_aware else text.split()
    joiner = " " if sentence_aware else " "
    chunks: list[dict] = []
    cur: list[str] = []
    cur_tok = 0
    for u in units:
        ut = _approx_tokens(u)
        if cur and cur_tok + ut > size:
            body = joiner.join(cur).strip()
            chunks.append({"text": body, "tokens": _approx_tokens(body),
                           "chars": len(body), "section": section})
            # carry overlap
            if overlap > 0:
                keep, kt = [], 0
                for piece in reversed(cur):
                    pt = _approx_tokens(piece)
                    if kt + pt > overlap:
                        break
                    keep.insert(0, piece); kt += pt
                cur, cur_tok = keep, kt
            else:
                cur, cur_tok = [], 0
        cur.append(u); cur_tok += ut
    if cur:
        body = joiner.join(cur).strip()
        if body:
            chunks.append({"text": body, "tokens": _approx_tokens(body),
                           "chars": len(body), "section": section})
    return chunks


def preview(text: str, cfg: dict) -> dict:
    """For the designer's live preview: chunk a sample and return chunks + summary stats."""
    ch = chunk_text(text, cfg)
    toks = [c["tokens"] for c in ch]
    return {
        "chunks": ch[:20],
        "count": len(ch),
        "avg_tokens": round(sum(toks) / len(toks), 1) if toks else 0,
        "min_tokens": min(toks) if toks else 0,
        "max_tokens": max(toks) if toks else 0,
        "total_tokens": sum(toks),
    }
