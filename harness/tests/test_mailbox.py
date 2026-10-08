"""Mailbox loading, doc-id convention, evidence quotes, received-date filtering, line resolver."""
from __future__ import annotations

import email
import json
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness"))

from nova.mailbox import load_batch, render_pages, resolve_lines, DocRecord
from nova.textlayer import found


def _examples_dir() -> Path:
    return REPO / "data" / "examples"


def _all_example_findings():
    d = _examples_dir()
    if not d.is_dir():
        return []
    return sorted(d.rglob("expected_finding.json"))


@pytest.mark.parametrize("finding_file", _all_example_findings())
def test_evidence_doc_ids_exist_in_mailbox(finding_file: Path):
    """Every evidence doc id in expected_finding.json must appear among the loaded DocRecords."""
    finding = json.loads(finding_file.read_text())
    example_root = finding_file.parent / "docs"
    if not example_root.is_dir():
        pytest.skip(f"no docs/ under {finding_file.parent}")

    all_records: list[DocRecord] = []
    for batch_dir in sorted(example_root.iterdir()):
        if batch_dir.is_dir():
            all_records.extend(load_batch(batch_dir))
    doc_id_set = {r.doc_id for r in all_records}

    all_items = (
        finding.get("findings", [])
        + finding.get("portfolio", {}).get("cashback", [])
        + finding.get("portfolio", {}).get("expiry", [])
        + finding.get("portfolio", {}).get("late_fee_risk", [])
    )
    missing: list[str] = []
    for item in all_items:
        for ev in item.get("evidence", []):
            doc = ev["doc"]
            if doc not in doc_id_set:
                missing.append(doc)
    assert not missing, f"doc ids not found in mailbox records: {missing}"


@pytest.mark.parametrize("finding_file", _all_example_findings())
def test_evidence_quotes_found_on_pages(finding_file: Path):
    """Every non-scan evidence quote must be found on the cited page of the loaded DocRecord."""
    finding = json.loads(finding_file.read_text())
    example_root = finding_file.parent / "docs"
    if not example_root.is_dir():
        pytest.skip(f"no docs/ under {finding_file.parent}")

    record_map: dict[str, DocRecord] = {}
    for batch_dir in sorted(example_root.iterdir()):
        if batch_dir.is_dir():
            for rec in load_batch(batch_dir):
                record_map[rec.doc_id] = rec

    all_items = (
        finding.get("findings", [])
        + finding.get("portfolio", {}).get("cashback", [])
        + finding.get("portfolio", {}).get("expiry", [])
        + finding.get("portfolio", {}).get("late_fee_risk", [])
    )
    failures: list[str] = []
    for item in all_items:
        for ev in item.get("evidence", []):
            doc, page, quote = ev["doc"], ev["page"], ev["quote"]
            rec = record_map.get(doc)
            if rec is None or rec.is_scan:
                continue
            if not found(rec.pages, page, quote):
                failures.append(f"{finding_file.parent.name}: doc={doc} page={page} quote={quote[:60]!r}")
    assert not failures, "\n".join(failures)


def _make_eml(date_str: str, subject: str = "test") -> bytes:
    """Build a minimal valid .eml bytes with the given Date header."""
    return (
        f"From: sender@example.com\r\n"
        f"To: receiver@example.com\r\n"
        f"Date: {date_str}\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"Body text.\r\n"
    ).encode()


def test_received_date_filtering(tmp_path: Path):
    """Documents received after as_of must be excluded when filtered."""
    from nova.state import StateDir
    from datetime import date

    batch_dir = tmp_path / "batch_01"
    batch_dir.mkdir()

    past_eml = _make_eml("Mon, 01 Jan 2030 10:00:00 +0000")
    future_eml = _make_eml("Mon, 01 Jan 2035 10:00:00 +0000")
    (batch_dir / "0001.eml").write_bytes(past_eml)
    (batch_dir / "0002.eml").write_bytes(future_eml)

    state = StateDir(tmp_path / "state")
    state.ensure()
    for rec in load_batch(batch_dir):
        state.save_doc(rec)

    all_docs = state.load_docs()
    assert len(all_docs) == 2

    as_of = date(2032, 6, 1)
    filtered = state.load_docs(as_of=as_of)
    assert len(filtered) == 1
    assert filtered[0].doc_id == "batch_01/0001.eml"


def test_line_resolver_round_trip():
    """resolve_lines returns the exact text of any line; that text is found on its page."""
    pages = ["Line one\nLine two\nLine three", "Page two line one\nPage two line two"]

    for page_idx, page_text in enumerate(pages, 1):
        lines = page_text.split("\n")
        for line_idx, expected_line in enumerate(lines, 1):
            resolved = resolve_lines(pages, page_idx, line_idx)
            assert resolved == expected_line
            assert found(pages, page_idx, resolved)


def test_line_resolver_range():
    pages = ["alpha\nbeta\ngamma\ndelta"]
    result = resolve_lines(pages, 1, 2, 3)
    assert result == "beta\ngamma"
    assert found(pages, 1, "beta")
    assert found(pages, 1, "gamma")


def test_render_pages_labels():
    pages = ["hello\nworld", "page two"]
    rendered = render_pages(pages)
    assert "[p1 L1] hello" in rendered
    assert "[p1 L2] world" in rendered
    assert "[p2 L1] page two" in rendered


def _make_eml_with_attachment(date_str: str, att_name: str, att_data: bytes, att_mime: str = "application/octet-stream") -> bytes:
    """Build an .eml with one attachment."""
    import base64
    encoded = base64.b64encode(att_data).decode()
    boundary = "BOUNDARY123"
    return (
        f"From: sender@example.com\r\n"
        f"To: receiver@example.com\r\n"
        f"Date: {date_str}\r\n"
        f"Subject: test\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/mixed; boundary=\"{boundary}\"\r\n"
        f"\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"Body.\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {att_mime}\r\n"
        f"Content-Disposition: attachment; filename=\"{att_name}\"\r\n"
        f"Content-Transfer-Encoding: base64\r\n"
        f"\r\n"
        f"{encoded}\r\n"
        f"--{boundary}--\r\n"
    ).encode()


def test_unknown_attachment_type_produces_unreadable_record(tmp_path: Path):
    """An attachment with an unknown extension is kept as an unreadable record, not dropped."""
    batch_dir = tmp_path / "batch_01"
    batch_dir.mkdir()

    eml = _make_eml_with_attachment(
        "Mon, 01 Jan 2030 10:00:00 +0000",
        att_name="report.docx",
        att_data=b"fake docx content",
    )
    (batch_dir / "0001.eml").write_bytes(eml)

    records = load_batch(batch_dir)

    att_records = [r for r in records if r.parent_id is not None]
    assert len(att_records) == 1, "attachment record must be present, not dropped"

    rec = att_records[0]
    assert rec.unreadable is True
    assert rec.ext == "docx"
    assert rec.pages == []
    assert rec.is_scan is False


def test_image_attachment_gets_is_scan(tmp_path: Path):
    """An image attachment (png/jpg/etc.) gets is_scan=True."""
    batch_dir = tmp_path / "batch_01"
    batch_dir.mkdir()

    eml = _make_eml_with_attachment(
        "Mon, 01 Jan 2030 10:00:00 +0000",
        att_name="scan.png",
        att_data=b"\x89PNG\r\n\x1a\n",
        att_mime="image/png",
    )
    (batch_dir / "0001.eml").write_bytes(eml)

    records = load_batch(batch_dir)

    att_records = [r for r in records if r.parent_id is not None]
    assert len(att_records) == 1

    rec = att_records[0]
    assert rec.is_scan is True
    assert rec.ext == "png"
    assert rec.pages == []
    assert rec.unreadable is False
