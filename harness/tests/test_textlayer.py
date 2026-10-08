"""textlayer output must be identical to grader/extract.py for every document in the mailboxes."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness"))
sys.path.insert(0, str(REPO / "grader"))

import extract as grader_extract
from nova import textlayer


def _all_emls(*roots: Path):
    for root in roots:
        yield from sorted(root.rglob("*.eml"))


def _docs_for_mailbox(mailbox_root: Path):
    """Yield (data_bytes, ext) for every email and its attachments under mailbox_root."""
    for eml_path in sorted(mailbox_root.rglob("*.eml")):
        data = eml_path.read_bytes()
        yield data, "eml"
        for name, att_data in grader_extract.attachments(data):
            if not name:
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in ("pdf", "xlsx"):
                yield att_data, ext


def _mailbox_roots():
    roots = []
    for name in ("examples", "scenarios", "exam"):
        r = REPO / "data" / name
        if r.is_dir():
            roots.append(r)
    return roots


@pytest.mark.parametrize("mailbox_root", _mailbox_roots())
def test_textlayer_identical_to_grader(mailbox_root: Path):
    """pages_of() output from textlayer must equal grader extract.pages_of() for every doc."""
    mismatches: list[str] = []
    for data, ext in _docs_for_mailbox(mailbox_root):
        try:
            expected = grader_extract.pages_of(data, ext)
            actual = textlayer.pages_of(data, ext)
        except Exception as e:
            mismatches.append(f"error reading .{ext}: {e}")
            continue
        if expected != actual:
            mismatches.append(f".{ext}: pages differ (got {len(actual)} vs expected {len(expected)})")
    assert not mismatches, "\n".join(mismatches)


def test_found_matches_grader():
    """textlayer.found() and grader found() must agree on every example evidence quote."""
    examples_dir = REPO / "data" / "examples"
    if not examples_dir.is_dir():
        pytest.skip("no examples dir")
    import json
    for finding_file in sorted(examples_dir.rglob("expected_finding.json")):
        finding = json.loads(finding_file.read_text())
        example_root = finding_file.parent / "docs"
        if not example_root.is_dir():
            continue
        mb = grader_extract.Mailbox(example_root)
        for item_list in [finding.get("findings", []),
                          finding.get("portfolio", {}).get("cashback", []),
                          finding.get("portfolio", {}).get("expiry", []),
                          finding.get("portfolio", {}).get("late_fee_risk", [])]:
            for item in item_list:
                for ev in item.get("evidence", []):
                    doc, page, quote = ev["doc"], ev["page"], ev["quote"]
                    try:
                        pages, is_scan = mb.pages(doc)
                    except LookupError:
                        continue
                    if is_scan:
                        continue
                    grader_found = grader_extract.found(pages, page, quote)
                    nova_found = textlayer.found(pages, page, quote)
                    assert grader_found == nova_found, (
                        f"{finding_file.parent.name}: doc={doc} page={page}: "
                        f"grader_found={grader_found} nova_found={nova_found}"
                    )
