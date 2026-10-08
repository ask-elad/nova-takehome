"""Golden test for the overcharge worked example.

Builds the case from the fixture, runs the overcharge rule and resolve,
and compares the single expected item (key, verdict, amount, quotes).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from nova.case import Case
from nova.resolve import resolve
from nova.rules.overcharge import run as run_overcharge
from nova.textlayer import Mailbox, found as text_found, norm


EXAMPLE = "overcharge"
EXAMPLES_DIR = Path("data/examples") / EXAMPLE
FIXTURES_DIR = Path("harness/tests/fixtures/examples") / EXAMPLE


def _load_tracking_rows(mailbox: Mailbox, doc: str) -> list[dict]:
    """Parse the tracking export so Case can resolve pickup dates by AWB."""
    pages, _ = mailbox.pages(doc)
    header = pages[0].splitlines()[0]
    cols = [c.strip() for c in header.split("|")]
    key_of = {name: i for i, name in enumerate(cols)}
    out = []
    for i, raw in enumerate(pages[0].splitlines()[1:], start=2):
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < len(cols):
            continue
        row = {
            "awb": parts[key_of["AWB"]],
            "event": parts[key_of["Event"]],
            "date": parts[key_of["Date"]],
            "_line": i,
        }
        out.append(row)
    return out


@pytest.fixture(scope="module")
def case():
    records = json.loads((FIXTURES_DIR / "facts.json").read_text())
    mailbox = Mailbox(EXAMPLES_DIR / "docs")
    # Attach tracking rows so pickup_date() can resolve PICKED_UP.
    for e in records:
        if e["type"] == "SheetMap" and e["data"]["kind"] == "tracking_export":
            e["rows"] = _load_tracking_rows(mailbox, e["doc"])
    expected = json.loads((EXAMPLES_DIR / "expected_finding.json").read_text())
    return Case.from_records(records, as_of=expected["as_of"]), mailbox, expected


def test_overcharge_golden(case):
    c, mb, expected = case
    cands = run_overcharge(c)
    items = resolve(cands, mb)
    by_id = {it.id: it for it in items}

    for ef in expected["findings"]:
        if ef["verdict"] == "finding":
            assert ef["id"] in by_id, f"missing expected finding {ef['id']}"
            got = by_id[ef["id"]]
            assert got.verdict == "finding"
            got_amt = Decimal(got.amount_usd)
            want_amt = Decimal(ef["amount_usd"])
            assert abs(got_amt - want_amt) <= Decimal("0.01"), (
                f"{ef['id']}: expected {want_amt} got {got_amt}"
            )
        else:
            # Decoys: must be absent from findings (we don't emit no_finding).
            assert ef["id"] not in by_id, f"decoy {ef['id']} should not be a finding"


def test_overcharge_quotes_pass_found(case):
    """Every emitted quote must be found by the textlayer's found()."""
    c, mb, _ = case
    items = resolve(run_overcharge(c), mb)
    for it in items:
        for ev in it.evidence:
            pages, _ = mb.pages(ev.doc)
            assert text_found(pages, ev.page, ev.quote), (
                f"{it.id}: quote not found on {ev.doc}:p{ev.page}: {ev.quote!r}"
            )
            # At least 12 non-space characters.
            assert len(ev.quote.replace(" ", "")) >= 12
