"""Reads a batch folder into document records."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Optional

from nova.textlayer import pages_of, pdf_is_image_only, parse_eml, attachments

_IMAGE_EXTS = {"png", "jpg", "jpeg", "tif", "tiff"}
_READABLE_EXTS = {"pdf", "xlsx"}


@dataclass
class DocRecord:
    doc_id: str           # e.g. "batch_01/0003.eml" or "batch_01/0003.eml#INV-1.pdf"
    received: datetime    # UTC
    sender_addr: str
    sender_name: str
    subject: str
    pages: list[str]
    is_scan: bool
    parent_id: Optional[str] = None  # email doc_id for attachments; None for emails
    ext: str = ""
    unreadable: bool = False

    def to_dict(self) -> dict:
        d = {
            "doc_id": self.doc_id,
            "received": self.received.isoformat(),
            "sender_addr": self.sender_addr,
            "sender_name": self.sender_name,
            "subject": self.subject,
            "pages": self.pages,
            "is_scan": self.is_scan,
            "parent_id": self.parent_id,
            "ext": self.ext,
            "unreadable": self.unreadable,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DocRecord":
        received = datetime.fromisoformat(d["received"])
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        return cls(
            doc_id=d["doc_id"],
            received=received,
            sender_addr=d["sender_addr"],
            sender_name=d["sender_name"],
            subject=d["subject"],
            pages=d["pages"],
            is_scan=d["is_scan"],
            parent_id=d.get("parent_id"),
            ext=d.get("ext", ""),
            unreadable=d.get("unreadable", False),
        )


def _parse_received(msg) -> datetime:
    dt = parsedate_to_datetime(str(msg["Date"]))
    return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)


def load_batch(batch_dir: Path) -> list[DocRecord]:
    """Read all .eml files in batch_dir and return a flat list of DocRecords (email + attachments)."""
    batch_dir = Path(batch_dir)
    batch_name = batch_dir.name  # "batch_01"
    records: list[DocRecord] = []

    for eml_file in sorted(batch_dir.glob("*.eml")):
        rel = f"{batch_name}/{eml_file.name}"
        data = eml_file.read_bytes()
        msg = parse_eml(data)

        received = _parse_received(msg)
        sender_name, sender_addr = parseaddr(str(msg["From"]))
        subject = str(msg["Subject"])

        eml_pages = pages_of(data, "eml")
        records.append(DocRecord(
            doc_id=rel,
            received=received,
            sender_addr=sender_addr,
            sender_name=sender_name,
            subject=subject,
            pages=eml_pages,
            is_scan=False,
            parent_id=None,
            ext="eml",
        ))

        for att_name, att_data in attachments(data):
            if not att_name:
                continue
            ext = att_name.rsplit(".", 1)[-1].lower() if "." in att_name else ""
            att_id = f"{rel}#{att_name}"

            if ext in _IMAGE_EXTS:
                records.append(DocRecord(
                    doc_id=att_id,
                    received=received,
                    sender_addr=sender_addr,
                    sender_name=sender_name,
                    subject=subject,
                    pages=[],
                    is_scan=True,
                    parent_id=rel,
                    ext=ext,
                ))
                continue

            if ext not in _READABLE_EXTS:
                print(f"unreadable attachment: {att_id} (ext={ext!r})", file=sys.stderr)
                records.append(DocRecord(
                    doc_id=att_id,
                    received=received,
                    sender_addr=sender_addr,
                    sender_name=sender_name,
                    subject=subject,
                    pages=[],
                    is_scan=False,
                    parent_id=rel,
                    ext=ext,
                    unreadable=True,
                ))
                continue

            try:
                att_pages = pages_of(att_data, ext)
                is_scan = ext == "pdf" and pdf_is_image_only(att_data)
            except Exception as exc:
                print(f"unreadable attachment: {att_id} ({exc})", file=sys.stderr)
                records.append(DocRecord(
                    doc_id=att_id,
                    received=received,
                    sender_addr=sender_addr,
                    sender_name=sender_name,
                    subject=subject,
                    pages=[],
                    is_scan=False,
                    parent_id=rel,
                    ext=ext,
                    unreadable=True,
                ))
                continue

            records.append(DocRecord(
                doc_id=att_id,
                received=received,
                sender_addr=sender_addr,
                sender_name=sender_name,
                subject=subject,
                pages=att_pages,
                is_scan=is_scan,
                parent_id=rel,
                ext=ext,
            ))

    return records


def render_pages(pages: list[str]) -> str:
    """Render pages with per-line labels for use in prompts, e.g. '[p1 L7] some text'."""
    out: list[str] = []
    for pi, page in enumerate(pages, 1):
        for li, line in enumerate(page.split("\n"), 1):
            out.append(f"[p{pi} L{li}] {line}")
    return "\n".join(out)


def resolve_lines(
    pages: list[str],
    page: int,
    start_line: int,
    end_line: Optional[int] = None,
) -> str:
    """Return exact text of a line or a range from pages (1-indexed page and line numbers)."""
    if page < 1 or page > len(pages):
        raise IndexError(f"page {page} out of range (1–{len(pages)})")
    page_lines = pages[page - 1].split("\n")
    if start_line < 1 or start_line > len(page_lines):
        raise IndexError(f"line {start_line} out of range on page {page} (1–{len(page_lines)})")
    if end_line is None:
        return page_lines[start_line - 1]
    if end_line < start_line or end_line > len(page_lines):
        raise IndexError(f"end_line {end_line} out of range on page {page}")
    return "\n".join(page_lines[start_line - 1:end_line])
