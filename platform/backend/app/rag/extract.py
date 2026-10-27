"""Per-format extractors → CanonicalDoc. Routes by extension. Applies OCR (with text-layer
detection for PDFs), table extraction, and optional image captioning per the pipeline's
processing config. Everything degrades honestly when heavy deps/engines are absent."""
from __future__ import annotations

import io
import re

from .document import CanonicalDoc
from . import ocr as OCR
from . import tables as TB


def extract(source: str, data: bytes, proc: dict) -> CanonicalDoc:
    doc = CanonicalDoc(source=source)
    lower = source.lower()
    ocr_cfg = proc.get("ocr", {}) or {}
    tables_on = (proc.get("tables", {}) or {}).get("backend", "local") != "off"
    img_cfg = proc.get("images", {}) or {}

    if lower.endswith((".txt", ".md", ".log", ".json")):
        doc.add_text(data.decode("utf-8", "ignore"))
        return doc

    if lower.endswith(".csv"):
        if tables_on:
            for md in TB.csv_tables(data):
                doc.add_table(md)
        else:
            doc.add_text(data.decode("utf-8", "ignore"))
        return doc

    if lower.endswith((".html", ".htm")):
        html = data.decode("utf-8", "ignore")
        if tables_on:
            for md in TB.html_tables(html):
                doc.add_table(md)
        body = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.S | re.I)
        doc.add_text(re.sub(r"<[^>]+>", " ", body))
        return doc

    if lower.endswith(".docx"):
        try:
            from docx import Document
            d = Document(io.BytesIO(data))
            section = ""
            for p in d.paragraphs:
                if (p.style and p.style.name or "").lower().startswith("heading") and p.text.strip():
                    section = p.text.strip()
                doc.add_text(p.text, section=section)
            if tables_on:
                for md in TB.docx_tables(d):
                    doc.add_table(md, section=section)
        except Exception:
            pass
        return doc

    if lower.endswith(".pdf"):
        _extract_pdf(doc, data, ocr_cfg, tables_on)
        return doc

    if lower.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")):
        doc.images += 1
        text, executed = OCR.ocr_image_bytes(data, ocr_cfg)
        if executed and text.strip():
            doc.pages_ocr += 1
            doc.method = "ocr"
            doc.add_text(text)
        else:
            cap, capd = TB.caption_image(data, img_cfg)
            if capd and cap:
                doc.images_captioned += 1
                doc.add_caption(cap)
            else:
                doc.add_text(f"[image: {source} — OCR/caption not available in this environment]")
        return doc

    # unknown → try utf-8
    doc.add_text(data.decode("utf-8", "ignore"))
    return doc


def _extract_pdf(doc: CanonicalDoc, data: bytes, ocr_cfg: dict, tables_on: bool) -> None:
    """Digital text per page; OCR only pages that lack a text layer (fast path preserved)."""
    pages_text: list[str] = []
    pypdf_ok = True
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages_text = [(pg.extract_text() or "") for pg in reader.pages]
    except ImportError:
        pypdf_ok = False
    except Exception:
        pages_text = []
    doc.pages_total = len(pages_text)
    ocr_backend = ocr_cfg.get("backend", "off")

    if not pypdf_ok:
        doc.add_text("[PDF text extraction unavailable: install 'pypdf' in the backend image]")
        doc.meta_note = "pypdf_missing"
        return

    digital_chars = sum(len(t.strip()) for t in pages_text)

    # scanned PDF + API OCR: Document-AI services accept the whole PDF directly (multi-page),
    # so send the PDF bytes once instead of rendering each page.
    if digital_chars < 20 and ocr_backend == "api" and doc.pages_total:
        otext, executed = OCR.ocr_image_bytes(data, ocr_cfg)
        if executed and otext.strip():
            doc.pages_ocr = doc.pages_total or 1
            doc.method = "ocr"
            doc.add_text(otext)
            if tables_on:
                for md in TB.pdf_tables(data):
                    doc.add_table(md)
            return

    for i, ptext in enumerate(pages_text, start=1):
        if OCR.needs_ocr(ptext) and ocr_backend != "off":
            img = _render_pdf_page(data, i - 1)
            if img is not None:
                otext, executed = OCR.ocr_image_bytes(img, ocr_cfg)
                if executed and otext.strip():
                    doc.pages_ocr += 1
                    doc.add_text(otext, page=i)
                    continue
            doc.add_text(f"[page {i}: scanned image — OCR ({ocr_backend}) not executed here]", page=i)
        elif ptext.strip():
            doc.add_text(ptext, page=i)

    # scanned PDF with no text and OCR off → actionable guidance instead of silent failure
    if digital_chars < 20 and ocr_backend == "off" and doc.pages_total:
        doc.add_caption("[This PDF appears to be scanned (no text layer). Enable OCR in the "
                        "pipeline's Processing config — local Tesseract or an OCR endpoint — to "
                        "extract its text.]")

    if tables_on:
        for md in TB.pdf_tables(data):
            doc.add_table(md)
    if doc.pages_ocr and doc.pages_ocr < max(1, doc.pages_total):
        doc.method = "mixed"
    elif doc.pages_ocr:
        doc.method = "ocr"


def _render_pdf_page(data: bytes, index: int):
    """Render a PDF page to PNG bytes for OCR (needs pdf2image/pymupdf). None if unavailable."""
    try:
        import fitz  # PyMuPDF
        d = fitz.open(stream=data, filetype="pdf")
        pix = d.load_page(index).get_pixmap(dpi=200)
        return pix.tobytes("png")
    except Exception:
        return None
