"""Unit tests for cashback rule.

Covers:
- whole vs marginal tier arithmetic
- an unclosed quarter yields no finding
- INR invoice converted per invoice month
- a rebate credit already issued is subtracted
- a credit issued early that covers the owed amount leaves nothing
- draft:claim_credit vs internal:track_credit around the due date
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from nova.case import Case
from nova.resolve import resolve
from nova.rules.cashback import _rebate_amount, run as run_cashback
from nova.textlayer import Mailbox


CONTRACT_DOC = "batch_01/0001.eml#MSA.pdf"


TIERS = [
    {"threshold": "10000.00", "rate": "5", "ref": {"page": 4, "line": 1}},
    {"threshold": "20000.00", "rate": "10", "ref": {"page": 4, "line": 1}},
]


def test_whole_tier_rate_applies_to_all_qs():
    assert _rebate_amount(Decimal("15000"), [type("T", (), t)() for t in TIERS], "whole") == Decimal("750.00")


def test_marginal_tier_pays_per_increment():
    # 15000: 5000 above tier1 threshold at 5% = 250.00
    tiers = [type("T", (), t)() for t in TIERS]
    assert _rebate_amount(Decimal("15000"), tiers, "marginal") == Decimal("250.00")
    # 25000: 10000 at 5% + 5000 at 10% = 500 + 500 = 1000.00
    assert _rebate_amount(Decimal("25000"), tiers, "marginal") == Decimal("1000.00")


# ---------------------------------------------------------------------------
# Full-rule fixtures
# ---------------------------------------------------------------------------

def _msa(due_days: str = "0", rebate_tiers=TIERS, fx_rows=None,
         promised_credits=None) -> dict:
    data = {
        "id": {"value": "C1", "ref": {"page": 1, "line": 1}},
        "kind": "msa", "parties": ["A", "B"],
        "dated": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
        "effective_from": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
        "end_date": {"value": "2034-12-31", "ref": {"page": 1, "line": 1}},
        "auto_renewal": False,
        "rate_periods": [], "rate_rows": [],
        "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
        "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
        "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
        "late_fee_compounding": False,
        "schedule1_rows": [],
        "rebate_tiers": rebate_tiers,
        "rebate_tier_rule": "whole",
        "rebate_period": "quarter",
        "rebate_due_days": {"value": due_days, "ref": {"page": 4, "line": 14}},
        "qs_includes": ["freight", "fuel", "security", "accessorial"],
        "qs_excludes": ["tax", "duty", "disbursement", "late_fee", "credit"],
    }
    if fx_rows:
        data["fx_rows"] = fx_rows
    if promised_credits:
        data["promised_credits"] = promised_credits
    return {"type": "ContractTerms", "doc": CONTRACT_DOC, "data": data}


def _invoice(id_: str, date: str, total: str, currency: str = "USD",
             excluded: list[dict] | None = None) -> dict:
    lines = [{
        "line_no": "1", "awb": "AWB1", "charge_label": "Air freight",
        "lane": "L", "qty": "1", "unit": "kg", "rate": total,
        "amount": total, "category": "freight",
        "ref": {"page": 1, "line": 9},
    }]
    if excluded:
        lines.extend(excluded)
    return {
        "type": "BillingDoc", "doc": f"batch_01/0003.eml#{id_}.pdf",
        "data": {
            "id": {"value": id_, "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "currency": {"value": currency, "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": date, "ref": {"page": 1, "line": 1}},
            "total": {"value": total, "ref": {"page": 1, "line": 10}},
            "lines": lines,
        },
    }


def _credit_note(id_: str, date: str, total: str, credit_type: str,
                 period_label: str) -> dict:
    return {
        "type": "BillingDoc", "doc": f"batch_01/0005.eml#{id_}.pdf",
        "data": {
            "id": {"value": id_, "ref": {"page": 1, "line": 1}},
            "kind": "credit_note",
            "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": date, "ref": {"page": 1, "line": 1}},
            "credit_type": credit_type,
            "credit_period": {"value": period_label, "ref": {"page": 1, "line": 1}},
            "total": {"value": total, "ref": {"page": 1, "line": 10}},
            "lines": [{"line_no": "1", "charge_label": "Rebate credit",
                       "amount": total, "category": "credit",
                       "ref": {"page": 1, "line": 9}}],
        },
    }


def test_unclosed_quarter_yields_no_finding():
    # as_of inside Q2
    recs = [_msa(), _invoice("I1", "2032-05-01", "20000.00")]
    assert run_cashback(Case.from_records(recs, as_of="2032-06-15")) == []


def test_closed_quarter_yields_finding():
    recs = [_msa(), _invoice("I1", "2032-05-01", "20000.00")]
    cands = run_cashback(Case.from_records(recs, as_of="2032-10-01"))
    assert len(cands) == 1
    assert cands[0].billed_amount == Decimal("2000.00")  # 10% of 20000


def test_rebate_credit_already_issued_subtracts():
    recs = [_msa(),
            _invoice("I1", "2032-05-01", "20000.00"),
            _credit_note("CN1", "2032-07-01", "500.00", "rebate", "2032-Q2")]
    cands = run_cashback(Case.from_records(recs, as_of="2032-10-01"))
    assert cands[0].billed_amount == Decimal("1500.00")


def test_credit_covering_earned_leaves_no_finding():
    recs = [_msa(),
            _invoice("I1", "2032-05-01", "20000.00"),
            _credit_note("CN1", "2032-07-01", "2000.00", "rebate", "2032-Q2")]
    assert run_cashback(Case.from_records(recs, as_of="2032-10-01")) == []


def test_inr_invoice_converted_per_month():
    # One INR invoice of 1,600,000.00 in May 2032; FX = 80 → USD 20000.
    fx = [{"month": "2032-05", "rate": "80.00", "ref": {"page": 11, "line": 1}}]
    recs = [_msa(fx_rows=fx),
            _invoice("I1", "2032-05-01", "1600000.00", currency="INR")]
    cands = run_cashback(Case.from_records(recs, as_of="2032-10-01"))
    assert cands[0].billed_amount == Decimal("2000.00")


def test_action_track_vs_claim_credit_around_due_date():
    # due_days = 45 → due 2032-08-14 for 2032-Q2 (end 2032-06-30)
    # before due: track; after: claim.
    recs = [_msa(due_days="45"),
            _invoice("I1", "2032-05-01", "20000.00")]
    mb = Mailbox.__new__(Mailbox)
    mb.root = None
    mb._by_name = {}
    mb._pages = {}

    before = run_cashback(Case.from_records(recs, as_of="2032-08-01"))
    assert before[0].deadline == "2032-08-14"
    after = run_cashback(Case.from_records(recs, as_of="2032-09-01"))
    assert after[0].deadline is None
