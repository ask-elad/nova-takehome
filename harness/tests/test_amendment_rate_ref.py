"""Task 07 Part B.2: amendment that hands a lane's rates to an attached doc.

For pickups on/after the effective date on that lane, the rate must come from
the named document. If we don't hold it, the finding is ``cannot_determine``
with ``missing_doc = (name_as_cited, Schedule 1 rates contact)``, never a
fall-back to the MSA rate.
"""
from __future__ import annotations

from decimal import Decimal

from nova.case import Case
from nova.rules.overcharge import run as run_overcharge


MSA_DOC = "batch_01/0001.eml#MSA.pdf"
AMD_DOC = "batch_01/0002.eml#AMD.pdf"
INV_DOC = "batch_01/0003.eml#INV.pdf"
TRACK_DOC = "batch_01/0004.eml#tracking.xlsx"


def _msa() -> dict:
    return {
        "type": "ContractTerms", "doc": MSA_DOC,
        "data": {
            "id": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "kind": "msa", "parties": ["A", "B"],
            "dated": {"value": "2030-12-01", "ref": {"page": 1, "line": 1}},
            "effective_from": {"value": "2031-01-01", "ref": {"page": 1, "line": 1}},
            "end_date": {"value": "2032-12-31", "ref": {"page": 1, "line": 1}},
            "auto_renewal": False,
            "rate_periods": [{"label": "P1", "start": "2031-01-01",
                               "end": "2032-12-31", "ref": {"page": 2, "line": 1}}],
            "rate_rows": [{
                "lane": "L1-L2", "band": "0-99.5 kg",
                "band_min_kg": 0.0, "band_max_kg": 99.5,
                "is_minimum_charge": False,
                "rates": [{"period": "P1", "rate": "5.00"}],
                "ref": {"page": 8, "line": 10},
            }],
            "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
            "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
            "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
            "late_fee_compounding": False,
            "schedule1_rows": [{
                "name": "Rhea Rates", "title": "Rates", "party": "A",
                "email": "rhea@example.com",
                "categories": ["rates"],
                "ref": {"page": 11, "line": 1},
            }],
        },
    }


def _amendment(doc_name_for_rates: str) -> dict:
    return {
        "type": "ContractTerms", "doc": AMD_DOC,
        "data": {
            "id": {"value": "C1-A1", "ref": {"page": 1, "line": 1}},
            "kind": "amendment",
            "amends": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "parties": ["A", "B"],
            "dated": {"value": "2031-01-15", "ref": {"page": 1, "line": 1}},
            "effective_from": {"value": "2031-02-01", "ref": {"page": 1, "line": 1}},
            "end_date": None,
            "auto_renewal": False,
            "rate_periods": [], "rate_rows": [],
            "payment_due_days": {"value": "45", "ref": {"page": 1, "line": 1}},
            "payment_grace_days": {"value": "0", "ref": {"page": 1, "line": 1}},
            "late_fee_rate": {"value": "1.0", "ref": {"page": 1, "line": 1}},
            "late_fee_compounding": False,
            "schedule1_rows": [],
            "amendment_rate_refs": [{
                "lane": "L1-L2",
                "effective_from": "2031-02-01",
                "document_name": doc_name_for_rates,
                "ref": {"page": 2, "line": 3},
            }],
        },
    }


def _invoice(invoice_date: str = "2031-02-15") -> dict:
    return {
        "type": "BillingDoc", "doc": INV_DOC,
        "data": {
            "id": {"value": "INV-1", "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
            "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": invoice_date, "ref": {"page": 1, "line": 1}},
            "total": {"value": "500.00", "ref": {"page": 1, "line": 1}},
            "lines": [{
                "line_no": "1", "awb": "AWB1", "charge_label": "Air freight",
                "lane": "L1-L2", "qty": "50", "unit": "kg", "rate": "10.00",
                "amount": "500.00", "category": "freight",
                "ref": {"page": 1, "line": 10},
            }],
        },
    }


def _tracking(date: str = "2031-02-10") -> dict:
    return {
        "type": "SheetMap", "doc": TRACK_DOC,
        "data": {
            "kind": "tracking_export", "sheet_number": 1,
            "columns": {"awb": "AWB", "event": "Event", "date": "Date"},
            "ref": {"page": 1, "line": 1},
        },
        "rows": [{"awb": "AWB1", "event": "PICKED_UP", "date": date, "_line": 2}],
    }


def test_missing_referenced_doc_yields_cannot_determine():
    records = [_msa(), _amendment("Annex A rev 2"), _invoice(), _tracking()]
    case = Case.from_records(records, as_of="2031-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1, cands
    c = cands[0]
    assert c.class_ == "overcharge"
    assert c.corrects == []
    assert c.missing_doc is not None
    name, holder = c.missing_doc
    assert name == "Annex A rev 2"
    assert holder.get("person") == "Rhea Rates"
    assert "cannot_determine" in (c.note or "")


def test_pickup_before_effective_date_does_not_trigger():
    records = [_msa(), _amendment("Annex A rev 2"),
               _invoice(invoice_date="2031-01-15"),
               _tracking(date="2031-01-14")]
    case = Case.from_records(records, as_of="2031-12-31")
    cands = run_overcharge(case)
    # pickup is before the rate-ref effective_from; the MSA rate still applies.
    # Billed 500 against MSA correct 5.00*50=250 → overcharge, not cannot_determine.
    assert len(cands) == 1
    assert cands[0].missing_doc is None
    assert cands[0].corrects != []
