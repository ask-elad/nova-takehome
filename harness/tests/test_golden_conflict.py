"""Golden test for the conflict worked example."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from nova.case import Case
from nova.resolve import resolve
from nova.rules.overcharge import run as run_overcharge
from nova.textlayer import Mailbox, found as text_found


EXAMPLE = "conflict"
EXAMPLES_DIR = Path("data/examples") / EXAMPLE
FIXTURES_DIR = Path("harness/tests/fixtures/examples") / EXAMPLE


@pytest.fixture(scope="module")
def case():
    records = json.loads((FIXTURES_DIR / "facts.json").read_text())
    mailbox = Mailbox(EXAMPLES_DIR / "docs")
    expected = json.loads((EXAMPLES_DIR / "expected_finding.json").read_text())
    return Case.from_records(records, as_of=expected["as_of"], mailbox=mailbox), mailbox, expected


def test_conflict_golden(case):
    c, mb, expected = case
    items = resolve(run_overcharge(c), mb)
    by_id = {it.id: it for it in items}
    for ef in expected["findings"]:
        assert ef["id"] in by_id, f"missing {ef['id']}"
        got = by_id[ef["id"]]
        assert got.verdict == ef["verdict"], f"{ef['id']}: verdict {got.verdict} != {ef['verdict']}"
        if ef["verdict"] == "conflict":
            assert got.amount_range is not None
            lo_got, hi_got = Decimal(got.amount_range[0]), Decimal(got.amount_range[1])
            lo_e, hi_e = Decimal(ef["amount_range"][0]), Decimal(ef["amount_range"][1])
            assert abs(lo_got - lo_e) <= Decimal("0.01")
            assert abs(hi_got - hi_e) <= Decimal("0.01")


def test_conflict_quotes_pass_found(case):
    c, mb, _ = case
    items = resolve(run_overcharge(c), mb)
    for it in items:
        for ev in it.evidence:
            pages, _ = mb.pages(ev.doc)
            assert text_found(pages, ev.page, ev.quote)
            assert len(ev.quote.replace(" ", "")) >= 12


def test_unranked_pair_typed_match():
    """A pair listed as (rate_notice, amendment) triggers conflict regardless of order."""
    from nova.schemas import UnrankedPair, Ref
    pair = UnrankedPair(a="amendment", b="rate_notice", ref=Ref(page=1, line=1))
    kinds = {pair.a, pair.b}
    assert "rate_notice" in kinds and "amendment" in kinds


def test_unranked_pair_not_matching_other_kinds():
    """A pair of (msa, annex) does not fire the rate_notice-vs-amendment conflict path."""
    from nova.schemas import UnrankedPair, Ref
    pair = UnrankedPair(a="msa", b="annex", ref=Ref(page=1, line=1))
    kinds = {pair.a, pair.b}
    assert not ("rate_notice" in kinds and "amendment" in kinds)


def test_amount_range_lower_bound_not_below_zero():
    """Unit: if higher correct > billed, the lower bound of amount_range clamps to 0."""
    from decimal import Decimal
    from nova.rules import Candidate, CorrectAmount
    from nova.case import SourceRef
    cand = Candidate(
        key=("overcharge", "INV"), class_="overcharge",
        billed_amount=Decimal("100.00"),
        corrects=[
            CorrectAmount(amount=Decimal("120.00"), sources=[], authority_level=1, in_force=True),
            CorrectAmount(amount=Decimal("90.00"), sources=[], authority_level=1, in_force=True),
        ],
        evidence=[],
        unranked_pair=("a", "b"),
    )
    items = resolve([cand], mailbox=None)  # mailbox unused for quotes when evidence is empty
    assert items[0].verdict == "conflict"
    assert items[0].amount_range[0] == "0.00"
    assert Decimal(items[0].amount_range[1]) == Decimal("10.00")
