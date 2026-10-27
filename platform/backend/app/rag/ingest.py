"""Ingestion orchestration: extract -> clean -> chunk -> embed -> index, per document,
with live progress + statistics via the shared jobs registry, and honest OCR guarding.

Sources supported now: direct text and File Storage files (txt/md/html/docx text).
OCR / scanned-PDF / table / image stages are wired as config but Phase 2 completes them;
here they are applied where trivially possible and otherwise noted, never fabricated.
"""
from __future__ import annotations

import hashlib
import re
import asyncio

from ..schemas import _id
from . import pipelines as P
from . import chunk as C
from . import embed as E
from . import vectorstore as V
from ..ontology import jobs   # reuse the progress/cancel job registry


def _clean(text: str, proc: dict) -> str:
    if not text:
        return ""
    if proc.get("dehyphenate", True):
        text = re.sub(r"-\n(\w)", r"\1", text)          # join hyphenated line breaks
    text = re.sub(r"[ \t]+\n", "\n", text)
    if proc.get("strip_boilerplate", True):
        # drop obvious page-number-only lines
        text = "\n".join(l for l in text.splitlines() if not re.fullmatch(r"\s*\d+\s*", l))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_from_storage(path: str) -> tuple[str, dict]:
    """Extract text from a File Storage file. Digital text formats now; scanned/OCR = Phase 2."""
    from .. import filestore
    meta = {"pages_ocr": 0, "tables": 0}
    data = filestore.read_bytes(path)
    lower = path.lower()
    if lower.endswith((".txt", ".md", ".csv", ".log", ".json")):
        return data.decode("utf-8", "ignore"), meta
    if lower.endswith((".html", ".htm")):
        return re.sub(r"<[^>]+>", " ", data.decode("utf-8", "ignore")), meta
    if lower.endswith(".docx"):
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs), meta
        except Exception:
            return "", meta
    if lower.endswith(".pdf"):
        # digital-PDF text extraction; if it yields little text it's likely scanned → OCR (Phase 2)
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            txt = "\n".join((pg.extract_text() or "") for pg in reader.pages)
            return txt, meta
        except Exception:
            return "", meta
    return "", meta


def _extract_canonical(source: str, data: bytes, cfg: dict):
    """Produce a CanonicalDoc via the Phase 2 extractor (OCR/tables/images honored per config)."""
    from . import extract as EX
    return EX.extract(source, data, cfg.get("processing", {}) or {})


def _chunk_canonical(doc, cfg: dict) -> list[dict]:
    """Structure-aware chunking: tables stay as their own chunks; text blocks chunk per config,
    tagged with their section/page so citations are precise."""
    ch_cfg = cfg.get("chunking", {})
    out: list[dict] = []
    for b in doc.blocks:
        if b.is_table:
            # keep a table intact as a single retrievable unit
            out.append({"text": b.text, "tokens": C._approx_tokens(b.text),
                        "chars": len(b.text), "section": b.section,
                        "page": b.page, "is_table": True})
        else:
            for c in C.chunk_text(b.text, ch_cfg, section=b.section):
                c["page"] = b.page
                c["is_table"] = False
                out.append(c)
    return out


def ingest_document(pid: str, source: str, text: str, cfg: dict, job_id: str = "",
                    raw_bytes: int = 0, data: bytes = None) -> dict:
    """Process one document end-to-end via the canonical model. If `data` (raw bytes) is given,
    the full extractor runs (OCR/tables/images); otherwise `text` is treated as a plain block."""
    proc = cfg.get("processing", {})
    if data is not None:
        doc = _extract_canonical(source, data, cfg)
    else:
        from .document import CanonicalDoc
        doc = CanonicalDoc(source=source)
        doc.add_text(_clean(text, proc))
    # clean text blocks (tables left intact)
    for b in doc.blocks:
        if not b.is_table:
            b.text = _clean(b.text, proc)
    chunks = _chunk_canonical(doc, cfg)
    chunks = [c for c in chunks if c.get("text", "").strip()]
    if not chunks:
        return {"chunks": 0, "tokens": 0, "status": "failed", "error": "no extractable text",
                **doc.stats()}

    if job_id:
        jobs.update(job_id, phase=f"embedding {source}", total=len(chunks))

    vectors, method = E.embed_texts([c["text"] for c in chunks], cfg.get("embeddings", {}))
    doc_id = _id("rdoc")
    rows = []
    for i, (c, v) in enumerate(zip(chunks, vectors)):
        rows.append({
            "id": f"{doc_id}:{i}", "pipeline_id": pid, "doc_id": doc_id,
            "text": c["text"], "vector": v,
            "metadata": {"source": source, "section": c.get("section", ""),
                         "page": c.get("page", 0), "is_table": c.get("is_table", False),
                         "chunk_index": i, "tokens": c["tokens"]},
        })
        if job_id and i % 10 == 0:
            jobs.update(job_id, processed=i)
    V.upsert(pid, rows)

    tokens = sum(c["tokens"] for c in chunks)
    dstats = doc.stats()
    rec = {
        "id": doc_id, "pipeline_id": pid, "source": source, "status": "indexed",
        "chunks": len(chunks), "tokens": tokens,
        "bytes": raw_bytes or len(doc.full_text().encode()),
        "avg_chunk_tokens": round(tokens / len(chunks), 1),
        "embed_method": method,
        "pages_ocr": dstats["pages_ocr"], "pages_total": dstats["pages_total"],
        "tables": dstats["tables"], "images": dstats["images"],
        "images_captioned": dstats["images_captioned"], "extract_method": dstats["method"],
        "hash": hashlib.md5(doc.full_text().encode()).hexdigest(),
    }
    P.documents.upsert(rec)
    return rec


async def run_ingest_job(pid: str, items: list[dict], job_id: str) -> dict:
    """items: [{source, text?, path?}]. Processes each with progress; honors cancel."""
    p = P.get_pipeline(pid)
    if not p:
        jobs.finish(job_id, "error", error="pipeline not found")
        return {}
    cfg = p["config"]
    p["status"] = "ingesting"; P.pipelines.upsert(p)

    total_docs = len(items)
    done = 0
    agg = {"documents": 0, "chunks": 0, "tokens": 0, "failed": 0,
           "pages_ocr": 0, "tables": 0, "images": 0}

    async def _process(it: dict):
        nonlocal done
        if jobs.is_cancelled(job_id):
            return
        src = it.get("source") or it.get("path") or "text"
        jobs.update(job_id, phase=f"processing {src}", doc_index=done, doc_total=total_docs)
        try:
            if it.get("path"):
                from .. import filestore
                raw = filestore.read_bytes(it["path"])
                # heavy extraction (OCR/tables/images) runs off the event loop
                rec = await asyncio.to_thread(ingest_document, pid, src, "", cfg,
                                              job_id, len(raw), raw)
            else:
                rec = await asyncio.to_thread(ingest_document, pid, src, it.get("text", ""),
                                              cfg, job_id, 0, None)
            if rec.get("status") == "indexed":
                agg["documents"] += 1; agg["chunks"] += rec["chunks"]; agg["tokens"] += rec["tokens"]
                agg["pages_ocr"] += rec.get("pages_ocr", 0); agg["tables"] += rec.get("tables", 0)
                agg["images"] += rec.get("images", 0)
            else:
                agg["failed"] += 1
                P.documents.upsert({"id": _id("rdoc"), "pipeline_id": pid, "source": src,
                                    "status": "failed", "error": rec.get("error", ""), "chunks": 0})
        except Exception as e:  # pragma: no cover
            agg["failed"] += 1
            P.documents.upsert({"id": _id("rdoc"), "pipeline_id": pid, "source": src,
                                "status": "failed", "error": str(e), "chunks": 0})
        done += 1
        jobs.update(job_id, doc_index=done, entities=agg["chunks"])

    # bounded concurrency — process several docs in parallel without overwhelming OCR/embeddings
    import os
    limit = max(1, int(os.getenv("RAG_INGEST_CONCURRENCY", "3")))
    sem = asyncio.Semaphore(limit)

    async def _guarded(it):
        async with sem:
            await _process(it)

    await asyncio.gather(*[_guarded(it) for it in items])

    stats = P.recompute_stats(pid)
    result = {**agg, "stats": stats, "vector_backend": V.backend_name()}
    jobs.finish(job_id, "cancelled" if jobs.is_cancelled(job_id) else "done", result=result)
    return result


def retrieve(pid: str, query_text: str, top_k: int = 0, min_score: float = None) -> dict:
    """Embed the query and return top-k cited chunks. Supports hybrid (vector+keyword) fusion
    and optional reranking per the pipeline's retrieval config."""
    p = P.get_pipeline(pid)
    if not p:
        return {"error": "pipeline not found", "results": []}
    cfg = p["config"]
    rcfg = cfg.get("retrieval", {})
    k = top_k or int(rcfg.get("top_k", 5))
    ms = rcfg.get("min_score", 0.0) if min_score is None else min_score
    hybrid = rcfg.get("hybrid", True)
    rerank_cfg = rcfg.get("rerank", {}) or {}

    vec = E.embed_query(query_text, cfg.get("embeddings", {}))
    # over-fetch candidates so fusion/rerank have room to reorder
    fetch_k = max(k, k * 4) if (hybrid or rerank_cfg.get("backend", "off") != "off") else k
    hits = V.query(pid, vec, k=fetch_k, min_score=ms)

    method = "vector"
    if hybrid and hits:
        from . import hybrid as H
        lex = H.lexical_scores(query_text, hits)
        hits = H.rrf_fuse(hits, lex)
        method = "hybrid"
    if rerank_cfg.get("backend", "off") != "off" and hits:
        from . import hybrid as H
        hits = H.rerank(query_text, hits, rerank_cfg)
        method += "+rerank"

    hits = hits[:k]
    return {"pipeline": p["name"], "query": query_text, "results": hits,
            "retrieval_method": method, "vector_backend": V.backend_name()}
