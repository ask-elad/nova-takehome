"""Golden tests for the duplicate worked examples."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from nova.case import Case
from nova.resolve import resolve
from nova.rules.duplicate import run as run_duplicate
from nova.textlayer import Mailbox, found as text_found


EXAMPLES = ["duplicate", "duplicate_rebilled_4_months"]


@pytest.fixture(scope="module", params=EXAMPLES)
def case(request):
    name = request.param
    examples_dir = Path("data/examples") / name
    fixtures_dir = Path("harness/tests/fixtures/examples") / name
    records = json.loads((fixtures_dir / "facts.json").read_text())
    mailbox = Mailbox(examples_dir / "docs")
    expected = json.loads((examples_dir / "expected_finding.json").read_text())
    c = Case.from_records(records, as_of=expected["as_of"], mailbox=mailbox)
    return c, mailbox, expected, name


def test_duplicate_golden(case):
    c, mb, expected, name = case
    items = resolve(run_duplicate(c), mb)
    by_id = {it.id: it for it in items}
    for ef in expected["findings"]:
        if ef["class"] != "duplicate":
            continue
        if ef["verdict"] == "finding":
            assert ef["id"] in by_id, f"{name}: missing {ef['id']}"
            got = by_id[ef["id"]]
            assert got.verdict == "finding"
            got_amt = Decimal(got.amount_usd)
            want_amt = Decimal(ef["amount_usd"])
            assert abs(got_amt - want_amt) <= Decimal("0.01"), (
                f"{name} {ef['id']}: expected {want_amt} got {got_amt}"
            )
        else:
            assert ef["id"] not in by_id, f"{name}: decoy {ef['id']} should not be a finding"


def test_duplicate_quotes_pass_found(case):
    c, mb, _, name = case
    items = resolve(run_duplicate(c), mb)
    for it in items:
        for ev in it.evidence:
            pages, _ = mb.pages(ev.doc)
            assert text_found(pages, ev.page, ev.quote), (
                f"{name} {it.id}: quote not on {ev.doc}:p{ev.page}: {ev.quote!r}"
            )
            assert len(ev.quote.replace(" ", "")) >= 12
