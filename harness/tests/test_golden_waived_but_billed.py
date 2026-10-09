"""Golden test for the waived_but_billed worked example."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from nova.case import Case
from nova.resolve import resolve
from nova.rules.waived_but_billed import run as run_waived
from nova.textlayer import Mailbox, found as text_found


EXAMPLE = "waived_but_billed"
EXAMPLES_DIR = Path("data/examples") / EXAMPLE
FIXTURES_DIR = Path("harness/tests/fixtures/examples") / EXAMPLE


@pytest.fixture(scope="module")
def case():
    records = json.loads((FIXTURES_DIR / "facts.json").read_text())
    mailbox = Mailbox(EXAMPLES_DIR / "docs")
    expected = json.loads((EXAMPLES_DIR / "expected_finding.json").read_text())
    return Case.from_records(records, as_of=expected["as_of"], mailbox=mailbox), mailbox, expected


def test_waived_golden(case):
    c, mb, expected = case
    items = resolve(run_waived(c), mb)
    by_id = {it.id: it for it in items}
    for ef in expected["findings"]:
        if ef["class"] != "waived_but_billed":
            continue
        if ef["verdict"] == "finding":
            assert ef["id"] in by_id, f"missing {ef['id']}"
            got = by_id[ef["id"]]
            assert abs(Decimal(got.amount_usd) - Decimal(ef["amount_usd"])) <= Decimal("0.01")
        else:
            assert ef["id"] not in by_id, f"decoy {ef['id']} should not be a finding"


def test_waived_quotes_pass_found(case):
    c, mb, _ = case
    items = resolve(run_waived(c), mb)
    for it in items:
        for ev in it.evidence:
            pages, _ = mb.pages(ev.doc)
            assert text_found(pages, ev.page, ev.quote), (
                f"{it.id}: quote not on {ev.doc}:p{ev.page}: {ev.quote!r}"
            )
            assert len(ev.quote.replace(" ", "")) >= 12
