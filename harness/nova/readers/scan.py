"""Scan reader: Claude vision transcribes each page, then billing reader runs on the transcription.

Scans don't appear in the eight worked examples, so this stays a thin wrapper.
It renders each PDF page to PNG with pymupdf, asks main-tier Claude to transcribe
each page to text lines in reading order, then builds a synthetic DocRecord with
the transcribed pages and runs the billing reader on it.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from typing import Optional

from pydantic import BaseModel

from nova.llm import LLMClient
from nova.mailbox import DocRecord
from nova.readers import ReadResult, UNTRUSTED_SYSTEM
from nova.readers import billing as billing_reader

prompt_version = "scan-1"


class _Transcript(BaseModel):
    lines: list[str]


_PAGE_INSTRUCTION = (
    "Transcribe this page to plain text lines in reading order (top to bottom,\n"
    "then left to right within each row). One table row per line, columns\n"
    "separated by two spaces. Preserve numbers, dates and codes exactly as\n"
    "printed. Return the lines in the `lines` field."
)


def _render_page_png(pdf_bytes: bytes, page_index: int) -> bytes:
    import pymupdf
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=180)
        return pix.tobytes("png")


def _transcribe_page(client: LLMClient, doc_id: str, page_png: bytes, page_index: int) -> list[str]:
    schema = _Transcript.model_json_schema()
    b64 = base64.standard_b64encode(page_png).decode()
    content = [
        {"type": "text", "text": f"{_PAGE_INSTRUCTION}\n\n<document doc=\"{doc_id}\" page=\"{page_index+1}\">"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
        {"type": "text", "text": "</document>"},
    ]
    raw = client.call(
        tier="main", purpose="scan_transcribe",
        messages=[{"role": "user", "content": content}],
        schema=schema, prompt_version=prompt_version,
        system=UNTRUSTED_SYSTEM, max_tokens=4096,
    )
    return list(raw.get("lines", []))


def read(client: LLMClient, record: DocRecord, pdf_bytes: Optional[bytes] = None) -> ReadResult:
    """Transcribe the PDF with vision, then run the billing reader on the result."""
    if pdf_bytes is None:
        raise ValueError("scan reader needs the raw PDF bytes")
    import pymupdf
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        n_pages = len(doc)
    transcribed_pages = []
    for i in range(n_pages):
        png = _render_page_png(pdf_bytes, i)
        lines = _transcribe_page(client, record.doc_id, png, i)
        transcribed_pages.append("\n".join(lines))
    synthetic = replace(record, pages=transcribed_pages, is_scan=False)
    return billing_reader.read(client, synthetic)
