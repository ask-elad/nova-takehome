"""Golden test for the expiry worked example."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova.case import Case
from nova.resolve import resolve
from nova.rules.expiry import run as run_expiry
from nova.textlayer import Mailbox, found as text_found


EXAMPLE = "expiry"
EXAMPLES_DIR = Path("data/examples") / EXAMPLE
FIXTURES_DIR = Path("harness/tests/fixtures/examples") / EXAMPLE


@pytest.fixture(scope="module")
def case():
    records = json.loads((FIXTURES_DIR / "facts.json").read_text())
    mailbox = Mailbox(EXAMPLES_DIR / "docs")
    expected = json.loads((EXAMPLES_DIR / "expected_finding.json").read_text())
    return Case.from_records(records, as_of=expected["as_of"], mailbox=mailbox), mailbox, expected


def test_expiry_golden(case):
    c, mb, expected = case
    items = resolve(run_expiry(c), mb)
    by_id = {it.id: it for it in items}
    for ef in expected["portfolio"]["expiry"]:
        if ef["verdict"] == "finding":
            assert ef["id"] in by_id, f"missing {ef['id']}"
            got = by_id[ef["id"]]
            assert got.deadline == ef["deadline"]
        else:
            assert ef["id"] not in by_id


def test_expiry_quotes_pass_found(case):
    c, mb, _ = case
    items = resolve(run_expiry(c), mb)
    for it in items:
        for ev in it.evidence:
            pages, _ = mb.pages(ev.doc)
            assert text_found(pages, ev.page, ev.quote)
            assert len(ev.quote.replace(" ", "")) >= 12
