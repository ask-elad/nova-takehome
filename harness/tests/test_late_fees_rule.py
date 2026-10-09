"""Unit tests for late-fee rules (glossary §Late fees).

Covers:
- days_late at 0, 14 and 15 (grace boundary of 14 days)
- simple vs compound fees over multiple months
- late_fee_risk on an INR invoice: converted once via Annex F
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from nova.case import Case
from nova.rules.late_fees import (
    _correct_fee,
    _run_not_owed,
    _run_risk,
)


# ---------------------------------------------------------------------------
# _correct_fee: simple vs compound
# ---------------------------------------------------------------------------

def test_simple_fee_two_months():
    # 2% simple, 1000 principal, 2 months -> 2 * 20.00 = 40.00
    assert _correct_fee(Decimal("1000"), Decimal("2"), 2, compound=False) == Decimal("40.00")


def test_compound_fee_two_months():
    # 2% compound: m1 = 20.00; m2 = round(2% * 1020) = 20.40 -> total 40.40
    assert _correct_fee(Decimal("1000"), Decimal("2"), 2, compound=True) == Decimal("40.40")


def test_zero_months_is_zero():
    assert _correct_fee(Decimal("1000"), Decimal("2"), 0, compound=True) == Decimal("0")


# ---------------------------------------------------------------------------
# days_late window: grace is contract's payment_grace_days.
# With grace=0 the boundary we test is at days_late=0 (no fee) vs days_late=1 (1 month).
# ---------------------------------------------------------------------------

CONTRACT_DOC = "batch_01/0001.eml#MSA.pdf"
INVOICE_DOC = "batch_01/0002.eml#INV.pdf"
REG_DOC = "batch_01/0003.eml#reg.xlsx"


def _msa(grace: str = "0", rate: str = "1.00", compound: bool = False, currency_fx=None) -> dict:
    data = {
        "id": {"value": "C1", "ref": {"page": 1, "line": 1}},
        "kind": "msa", "parties": ["A", "B"],
        "dated": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
        "effective_from": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
        "end_date": {"value": "2033-12-31", "ref": {"page": 1, "line": 1}},
        "auto_renewal": False,
        "rate_periods": [], "rate_rows": [],
        "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
        "payment_grace_days": {"value": grace, "ref": {"page": 3, "line": 1}},
        "late_fee_rate": {"value": rate, "ref": {"page": 3, "line": 1}},
        "late_fee_compounding": compound,
        "schedule1_rows": [],
    }
    if currency_fx:
        data["fx_rows"] = currency_fx
    return {"type": "ContractTerms", "doc": CONTRACT_DOC, "data": data}


def _invoice(fee_lines: list[dict], currency: str = "USD",
             invoice_date: str = "2032-05-01", total: str = "100.00") -> dict:
    return {
        "type": "BillingDoc", "doc": INVOICE_DOC,
        "data": {
            "id": {"value": "INV-X", "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "currency": {"value": currency, "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": invoice_date, "ref": {"page": 1, "line": 1}},
            "due_date": {"value": "2032-06-15", "ref": {"page": 1, "line": 1}},
            "total": {"value": total, "ref": {"page": 1, "line": 10}},
            "lines": fee_lines,
        },
    }


def _late_fee_line(amount: str, refers: str = "INV-TARGET") -> dict:
    return {
        "line_no": "1", "charge_label": f"Late fee on {refers}",
        "refers_to_invoice": refers, "qty": "1", "unit": "month",
        "rate": "1.00", "amount": amount, "category": "late_fee",
        "ref": {"page": 1, "line": 11},
    }


def _register(invoice_id: str, due: str, paid: str, amount: str = "USD 1000.00") -> dict:
    return {
        "type": "SheetMap", "doc": REG_DOC,
        "data": {
            "kind": "payment_register", "sheet_number": 1,
            "columns": {"invoice_id": "Invoice no.", "due_date": "Due date",
                        "paid_date": "Paid date", "status": "Status",
                        "amount": "Amount"},
            "ref": {"page": 1, "line": 1},
        },
        "rows": [{
            "invoice_id": invoice_id, "due_date": f"due {due}",
            "paid_date": paid, "status": "paid", "amount": amount,
            "_page": 1, "_line": 2,
        }],
    }


def test_days_late_zero_bills_nothing_is_fine():
    # paid exactly on due date: 0 days late, correct fee = 0.
    # Billed 0 would be no finding; billed > 0 → finding.
    recs = [_msa(grace="0", rate="1.00"),
            _invoice([_late_fee_line("10.00")]),
            _register("INV-TARGET", "2032-05-01", "2032-05-01")]
    cands = _run_not_owed(Case.from_records(recs, as_of="2032-07-01"))
    assert len(cands) == 1
    assert cands[0].billed_amount == Decimal("10.00")
    assert cands[0].corrects[0].amount == Decimal("0")


def test_days_late_14_within_grace_14():
    recs = [_msa(grace="14", rate="1.00"),
            _invoice([_late_fee_line("10.00")]),
            _register("INV-TARGET", "2032-05-01", "2032-05-15")]  # 14 days
    cands = _run_not_owed(Case.from_records(recs, as_of="2032-07-01"))
    assert len(cands) == 1
    # grace == 14, days_late == 14 → correct = 0 → finding of 10.00
    assert cands[0].corrects[0].amount == Decimal("0")


def test_days_late_15_past_grace_14():
    recs = [_msa(grace="14", rate="1.00"),
            _invoice([_late_fee_line("20.00")]),
            _register("INV-TARGET", "2032-05-01", "2032-05-16")]  # 15 days
    cands = _run_not_owed(Case.from_records(recs, as_of="2032-07-01"))
    # 1 month * 1% * 1000.00 = 10.00; billed 20 → 10.00 overcharge
    assert cands[0].billed_amount - cands[0].corrects[0].amount == Decimal("10.00")


def test_compound_two_months_more_than_simple():
    # 70 days late → ceil(70/30) = 3 months
    recs_c = [_msa(grace="0", rate="2.00", compound=True),
              _invoice([_late_fee_line("0.00")]),
              _register("INV-TARGET", "2032-05-01", "2032-07-10")]
    recs_s = [_msa(grace="0", rate="2.00", compound=False),
              _invoice([_late_fee_line("0.00")]),
              _register("INV-TARGET", "2032-05-01", "2032-07-10")]
    # No overcharge on billed 0.00. We assert the computed correct via _correct_fee direct instead.
    compound = _correct_fee(Decimal("1000"), Decimal("2"), 3, compound=True)
    simple = _correct_fee(Decimal("1000"), Decimal("2"), 3, compound=False)
    assert compound > simple


# ---------------------------------------------------------------------------
# late_fee_risk: INR → USD converted once per finding.
# ---------------------------------------------------------------------------

def _msa_inr(fx_month: str = "2032-05", fx_rate: str = "80.00") -> dict:
    m = _msa(grace="0", rate="2.00", compound=False)
    m["data"]["fx_rows"] = [{"month": fx_month, "rate": fx_rate,
                              "ref": {"page": 11, "line": 1}}]
    return m


def test_late_fee_risk_inr_converted_once():
    # as_of 2032-06-10, due 2032-06-15 → 5 days ahead; fee=2% * 10000 INR = 200 INR
    # Convert: 200 / 80 = 2.50
    recs = [_msa_inr(fx_month="2032-05", fx_rate="80.00"),
            _invoice([], currency="INR", total="10000.00")]
    cands = _run_risk(Case.from_records(recs, as_of="2032-06-10"))
    assert len(cands) == 1
    assert cands[0].billed_amount == Decimal("2.50")
    assert cands[0].deadline == "2032-06-15"


def test_late_fee_risk_not_fired_outside_14_days():
    recs = [_msa(grace="0", rate="2.00"),
            _invoice([], total="1000.00")]
    cands = _run_risk(Case.from_records(recs, as_of="2032-05-01"))
    assert cands == []
