"""Canonical document model — the normalized representation every extractor produces and every
downstream stage (chunking) consumes. Adding a new file type = writing one extractor that emits
this. Blocks carry provenance (page, section) so citations can be precise.

Block kinds: 'text' (paragraph/section body), 'table' (rows preserved), 'caption' (figure text).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Block:
    kind: str                      # text | table | caption
    text: str                      # rendered text (tables rendered as markdown/CSV)
    section: str = ""              # heading path this block belongs to
    page: int = 0                  # source page (0 if unknown)
    is_table: bool = False
    meta: dict = field(default_factory=dict)


@dataclass
class CanonicalDoc:
    source: str
    blocks: list[Block] = field(default_factory=list)
    # ingestion telemetry surfaced in stats:
    pages_total: int = 0
    pages_ocr: int = 0             # pages that required OCR
    tables: int = 0
    images: int = 0
    images_captioned: int = 0
    method: str = "digital"        # digital | ocr | mixed

    def add_text(self, text: str, section: str = "", page: int = 0):
        if text and text.strip():
            self.blocks.append(Block("text", text.strip(), section, page))

    def add_table(self, rendered: str, section: str = "", page: int = 0):
        if rendered and rendered.strip():
            self.blocks.append(Block("table", rendered.strip(), section, page, is_table=True))
            self.tables += 1

    def add_caption(self, text: str, section: str = "", page: int = 0):
        if text and text.strip():
            self.blocks.append(Block("caption", text.strip(), section, page,
                                     meta={"figure": True}))

    def full_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    def stats(self) -> dict:
        return {"pages_total": self.pages_total, "pages_ocr": self.pages_ocr,
                "tables": self.tables, "images": self.images,
                "images_captioned": self.images_captioned, "method": self.method}
