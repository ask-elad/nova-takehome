"""Regression tests for the duplicate rule's AWB match (task 07 Part B.1).

A shared master-AWB prefix must never make two shipment lines look like the
same shipment. Duplicate detection compares the whole AWB string: a master
with ``-H1`` and ``-H2`` house suffixes are two different shipments. This is
glossary decoy DU-05.
"""
from __future__ import annotations

from decimal import Decimal

from nova.case import Case
from nova.rules.duplicate import run as run_duplicate


CONTRACT_DOC = "batch_01/0001.eml#MSA.pdf"
INV_A = "batch_01/0002.eml#INVA.pdf"
INV_B = "batch_01/0003.eml#INVB.pdf"
INV_SAME = "batch_01/0003.eml#INV_SAME_AWB.pdf"


def _msa() -> dict:
    return {
        "type": "ContractTerms", "doc": CONTRACT_DOC,
        "data": {
            "id": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "kind": "msa", "parties": ["A", "B"],
            "dated": {"value": "2031-12-01", "ref": {"page": 1, "line": 1}},
            "effective_from": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
            "end_date": {"value": "2032-12-31", "ref": {"page": 1, "line": 1}},
            "auto_renewal": False,
            "rate_periods": [{"label": "P1", "start": "2032-01-01",
                               "end": "2032-12-31", "ref": {"page": 2, "line": 1}}],
            "rate_rows": [{
                "lane": "L1-L2", "band": "0-99.5 kg",
                "band_min_kg": 0.0, "band_max_kg": 99.5,
                "is_minimum_charge": False,
                "rates": [{"period": "P1", "rate": "6.00"}],
                "ref": {"page": 8, "line": 10},
            }],
            "fuel_rows": [{"month": "2032-02", "rate": "20.00",
                            "ref": {"page": 9, "line": 1}}],
            "accessorials": [{
                "code": "FRT", "label": "Air freight",
                "rate": "0.00", "basis": "USD per shipment",
                "basis_kind": "per_shipment",
                "ref": {"page": 7, "line": 1},
            }],
            "charge_code_aliases": [{
                "code": "FRT", "label": "Air freight",
                "aliases": ["Air freight"],
                "ref": {"page": 7, "line": 2},
            }], "fx_rows": None,
            "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
            "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
            "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
            "late_fee_compounding": False,
            "schedule1_rows": [],
        },
    }


def _invoice(doc: str, inv_id: str, awb: str, amount: str = "100.00",
             invoice_date: str = "2032-02-15") -> dict:
    return {
        "type": "BillingDoc", "doc": doc,
        "data": {
            "id": {"value": inv_id, "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
            "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": invoice_date, "ref": {"page": 1, "line": 1}},
            "total": {"value": amount, "ref": {"page": 1, "line": 1}},
            "lines": [{
                "line_no": "1", "awb": awb, "charge_label": "Air freight",
                "lane": "L1-L2", "qty": "50", "unit": "kg", "rate": "2.00",
                "amount": amount, "category": "freight",
                "ref": {"page": 1, "line": 10},
            }],
        },
    }


def test_house_suffix_disambiguates_two_shipments():
    """Lines sharing a master AWB with different house suffixes are not duplicates."""
    records = [
        _msa(),
        _invoice(INV_A, "INV-A", awb="CA12345678-H1", invoice_date="2032-02-10"),
        _invoice(INV_B, "INV-B", awb="CA12345678-H2", invoice_date="2032-02-15"),
    ]
    case = Case.from_records(records, as_of="2032-12-31")
    cands = run_duplicate(case)
    assert cands == [], (
        f"Different house suffixes under the same master AWB must not match: "
        f"{[c.key for c in cands]}"
    )


def test_same_full_awb_still_matches():
    """Sanity: identical full AWBs on two invoices still produce a duplicate."""
    records = [
        _msa(),
        _invoice(INV_A, "INV-A", awb="CA12345678-H1", invoice_date="2032-02-10"),
        _invoice(INV_SAME, "INV-B", awb="CA12345678-H1", invoice_date="2032-02-15"),
    ]
    case = Case.from_records(records, as_of="2032-12-31")
    cands = run_duplicate(case)
    assert len(cands) == 1, cands
    assert cands[0].class_ == "duplicate"
    assert cands[0].key[1] == "INV-B"
    assert cands[0].billed_amount == Decimal("100.00")
