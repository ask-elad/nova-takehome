"""Task 07 Part B.3: DG fee vs. dry-ice (refrigerant-only) declarations.

A DG fee billed on a shipment whose DG declaration says dry ice only
(UN1845) or ``refrigerant_only=true`` is an overcharge of the full fee
(MSA 5.2/5.3). A mixed shipment (dry ice plus another UN number) takes
the DG fee once.
"""
from __future__ import annotations

from decimal import Decimal

from nova.case import Case
from nova.rules.overcharge import run as run_overcharge


MSA_DOC = "batch_01/0001.eml#MSA.pdf"
INV_DOC = "batch_01/0003.eml#INV.pdf"
DG_DOC = "batch_01/0004.eml#DG.pdf"
TRACK_DOC = "batch_01/0005.eml#tracking.xlsx"


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
            "accessorials": [{
                "code": "DG", "label": "Dangerous goods fee",
                "rate": "284.91", "basis": "USD per shipment",
                "basis_kind": "per_shipment",
                "condition": "dangerous goods per IATA DGR, excluding refrigerant-only",
                "ref": {"page": 7, "line": 3},
            }],
            "charge_code_aliases": [{
                "code": "DG", "label": "Dangerous goods fee",
                "aliases": ["DG fee"],
                "ref": {"page": 7, "line": 1},
            }],
            "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
            "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
            "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
            "late_fee_compounding": False,
            "schedule1_rows": [],
        },
    }


def _invoice() -> dict:
    return {
        "type": "BillingDoc", "doc": INV_DOC,
        "data": {
            "id": {"value": "INV-1", "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
            "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": "2031-02-15", "ref": {"page": 1, "line": 1}},
            "total": {"value": "534.91", "ref": {"page": 1, "line": 1}},
            "lines": [
                {"line_no": "1", "awb": "AWB1", "charge_label": "Air freight",
                 "lane": "L1-L2", "qty": "50", "unit": "kg", "rate": "5.00",
                 "amount": "250.00", "category": "freight",
                 "ref": {"page": 1, "line": 10}},
                {"line_no": "2", "awb": "AWB1", "charge_label": "DG fee",
                 "lane": None, "qty": "1", "unit": "shpt", "rate": "284.91",
                 "amount": "284.91", "category": "accessorial",
                 "ref": {"page": 1, "line": 11}},
            ],
        },
    }


def _dg_dec(un_numbers, refrigerant_only=None) -> dict:
    un_list = [{"value": u, "ref": {"page": 1, "line": 5}} for u in un_numbers]
    return {
        "type": "ShipmentDoc", "doc": DG_DOC,
        "data": {
            "awb": {"value": "AWB1", "ref": {"page": 1, "line": 1}},
            "kind": "dg_declaration",
            "un_numbers": un_list,
            "refrigerant_only": refrigerant_only,
            "refrigerant_only_ref": {"page": 1, "line": 6} if refrigerant_only else None,
        },
    }


def _tracking() -> dict:
    return {
        "type": "SheetMap", "doc": TRACK_DOC,
        "data": {
            "kind": "tracking_export", "sheet_number": 1,
            "columns": {"awb": "AWB", "event": "Event", "date": "Date"},
            "ref": {"page": 1, "line": 1},
        },
        "rows": [{"awb": "AWB1", "event": "PICKED_UP", "date": "2031-02-10",
                  "_line": 2}],
    }


def test_dry_ice_only_un1845_full_dg_fee_is_overcharge():
    records = [_msa(), _invoice(), _dg_dec(["UN1845"]), _tracking()]
    case = Case.from_records(records, as_of="2031-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1
    c = cands[0]
    delta = c.billed_amount - c.corrects[0].amount
    assert delta == Decimal("284.91"), f"expected full DG as overcharge, got {delta}"


def test_refrigerant_only_flag_full_dg_fee_is_overcharge():
    records = [_msa(), _invoice(),
               _dg_dec(["UN1845"], refrigerant_only=True), _tracking()]
    case = Case.from_records(records, as_of="2031-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1
    delta = cands[0].billed_amount - cands[0].corrects[0].amount
    assert delta == Decimal("284.91")


def test_mixed_shipment_dry_ice_plus_other_un_dg_fee_applies():
    records = [_msa(), _invoice(),
               _dg_dec(["UN1845", "UN3480"]), _tracking()]
    case = Case.from_records(records, as_of="2031-12-31")
    cands = run_overcharge(case)
    # Correct DG fee = 284.91 applies once; billed matches → no overcharge.
    assert cands == [], cands
