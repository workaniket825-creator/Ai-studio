"""Table extraction (preserve tables as Markdown so they chunk/retrieve as structured units)
and image handling (extract + optional multimodal captioning). Offline-verifiable for CSV/HTML/
DOCX tables; PDF tables use pdfplumber when present, else are skipped honestly."""
from __future__ import annotations

import csv as _csv
import io
import re


def rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    rows = [[(c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head = rows[0]
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def csv_tables(data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8", "ignore")
        rows = list(_csv.reader(io.StringIO(text)))
        md = rows_to_markdown(rows)
        return [md] if md else []
    except Exception:
        return []


def html_tables(html: str) -> list[str]:
    """Extract <table> blocks as Markdown without a heavy parser."""
    tables = []
    for tbl in re.findall(r"<table.*?>(.*?)</table>", html, re.S | re.I):
        rows = []
        for tr in re.findall(r"<tr.*?>(.*?)</tr>", tbl, re.S | re.I):
            cells = re.findall(r"<t[dh].*?>(.*?)</t[dh]>", tr, re.S | re.I)
            rows.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
        md = rows_to_markdown(rows)
        if md:
            tables.append(md)
    return tables


def docx_tables(doc) -> list[str]:
    out = []
    for t in getattr(doc, "tables", []):
        rows = [[c.text for c in row.cells] for row in t.rows]
        md = rows_to_markdown(rows)
        if md:
            out.append(md)
    return out


def pdf_tables(data: bytes) -> list[str]:
    """PDF table extraction via pdfplumber when available; otherwise none (honest)."""
    try:
        import pdfplumber
        out = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                for tbl in page.extract_tables() or []:
                    md = rows_to_markdown(tbl)
                    if md:
                        out.append(md)
        return out
    except Exception:
        return []


def caption_image(img_bytes: bytes, cfg: dict) -> tuple[str, bool]:
    """Caption a figure via a multimodal Model Endpoint. Guarded: (caption, executed)."""
    if cfg.get("backend") != "api" or not cfg.get("endpoint_id"):
        return "", False
    try:
        import base64
        from ..endpoints import get_full, litellm_call_args
        ep = get_full(cfg["endpoint_id"])
        if not ep:
            return "", False
        args = litellm_call_args(ep)
        import litellm
        b64 = base64.b64encode(img_bytes).decode()
        resp = litellm.completion(model=args["model"], messages=[{"role": "user", "content": [
            {"type": "text", "text": "Describe this figure for search indexing in one sentence."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}], **args.get("params", {}))
        return (resp["choices"][0]["message"]["content"] or ""), True
    except Exception:
        return "", False
