"""Unit tests for cannot_determine in resolve."""
from __future__ import annotations

from decimal import Decimal

from nova.case import SourceRef
from nova.resolve import resolve
from nova.rules import Candidate, CorrectAmount


def test_candidate_with_missing_doc_becomes_cannot_determine():
    cand = Candidate(
        key=("overcharge", "INV-1"),
        class_="overcharge",
        billed_amount=Decimal("100.00"),
        corrects=[],
        evidence=[],
        missing_doc=("Annex F row for 2033-05", "treasury@carrier.example"),
        note="cannot_determine: no Annex F row for 2033-05",
    )
    items = resolve([cand], mailbox=None)
    assert len(items) == 1
    assert items[0].verdict == "cannot_determine"
    assert items[0].missing_doc == {
        "name": "Annex F row for 2033-05",
        "holder": {"person": "treasury@carrier.example"},
    }


def test_missing_doc_that_cannot_change_answer_is_not_cannot_determine():
    """When the rule has a correct amount in hand (nothing missing to decide
    the answer), it must NOT emit a cannot_determine candidate — resolve
    then produces a finding or no_finding as usual."""
    cand = Candidate(
        key=("overcharge", "INV-2"),
        class_="overcharge",
        billed_amount=Decimal("100.00"),
        corrects=[CorrectAmount(amount=Decimal("90.00"), sources=[],
                                authority_level=1, in_force=True)],
        evidence=[],
    )
    items = resolve([cand], mailbox=None)
    assert len(items) == 1
    assert items[0].verdict == "finding"
    assert items[0].amount_usd == "10.00"
