"""Audit B7: a billing document with chargeable lines is an invoice for every
class; summary-only statements of account stay out."""
from __future__ import annotations

from nova.case import Case


def _bill(kind: str, id_: str, line_cats: list[str], asks: bool = True) -> dict:
    lines = []
    for i, cat in enumerate(line_cats, start=1):
        lines.append({
            "charge_label": "Air freight" if cat == "freight" else cat,
            "category": cat,
            "amount": "100.00",
            "ref": {"page": 1, "line": i + 2},
        })
    data = {
        "id": {"value": id_, "ref": {"page": 1, "line": 1}},
        "kind": kind,
        "issuer": {"value": "X", "ref": {"page": 1, "line": 1}},
        "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
        "total": {"value": "100.00", "ref": {"page": 1, "line": 2}},
        "asks_for_payment": asks,
        "lines": lines,
    }
    return {"type": "BillingDoc", "doc": f"batch/{id_}.pdf", "data": data}


def test_billing_statement_with_charges_promotes_to_invoice():
    rec = _bill("statement", "STMT-1", ["freight"])
    case = Case.from_records([rec], as_of="2032-01-31")
    assert case.billings[0].bill.kind == "invoice"


def test_summary_only_statement_stays_a_statement():
    rec = _bill("statement", "SOA-1", ["other"])
    case = Case.from_records([rec], as_of="2032-01-31")
    assert case.billings[0].bill.kind == "statement"


def test_statement_without_ask_for_payment_stays_a_statement():
    rec = _bill("statement", "SOA-2", ["freight"], asks=False)
    case = Case.from_records([rec], as_of="2032-01-31")
    assert case.billings[0].bill.kind == "statement"
