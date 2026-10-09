"""Overcharge fixes from task 04a2 review.

Covers:
- fuel priced after freight regardless of line order on the invoice
- Annex E alias mapping (billed label → code → accessorial rate)
- accessorial `months` window
- accessorial condition via Judge (OC-02 DG vs dry-ice)
- INR invoice: compute in INR, convert once at Annex F
- missing FX month → cannot_determine candidate (no CorrectAmount)
"""
from __future__ import annotations

from decimal import Decimal

from nova.case import Case
from nova.rules.overcharge import run as run_overcharge


CONTRACT_DOC = "batch_01/0001.eml#MSA.pdf"
INVOICE_DOC = "batch_01/0002.eml#INV.pdf"
TRACK_DOC = "batch_01/0003.eml#tracking.xlsx"


def _msa(**overrides) -> dict:
    data = {
        "id": {"value": "C1", "ref": {"page": 1, "line": 1}},
        "kind": "msa",
        "parties": ["A", "B"],
        "dated": {"value": "2031-12-01", "ref": {"page": 1, "line": 1}},
        "effective_from": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
        "end_date": {"value": "2032-12-31", "ref": {"page": 1, "line": 1}},
        "auto_renewal": False,
        "rate_periods": [{"label": "P1", "start": "2032-01-01", "end": "2032-12-31",
                          "ref": {"page": 2, "line": 1}}],
        "rate_rows": [{
            "lane": "L1-L2", "band": "0-99.5 kg",
            "band_min_kg": 0.0, "band_max_kg": 99.5,
            "is_minimum_charge": False,
            "rates": [{"period": "P1", "rate": "6.00"}],
            "ref": {"page": 8, "line": 10},
        }],
        "fuel_rows": [{"month": "2032-02", "rate": "20.00",
                       "ref": {"page": 9, "line": 1}}],
        "accessorials": None,
        "charge_code_aliases": None,
        "fx_rows": None,
        "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
        "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
        "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
        "late_fee_compounding": False,
        "schedule1_rows": [],
    }
    data.update(overrides)
    return {"type": "ContractTerms", "doc": CONTRACT_DOC, "data": data}


def _invoice(lines, currency="USD", invoice_date="2032-02-15", contract_ref="C1",
             inv_id="INV-1") -> dict:
    total = sum(Decimal(ln["amount"]) for ln in lines)
    data = {
        "id": {"value": inv_id, "ref": {"page": 1, "line": 1}},
        "kind": "invoice",
        "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
        "currency": {"value": currency, "ref": {"page": 1, "line": 1}},
        "contract_ref": {"value": contract_ref, "ref": {"page": 1, "line": 1}},
        "invoice_date": {"value": invoice_date, "ref": {"page": 1, "line": 1}},
        "total": {"value": f"{total:.2f}", "ref": {"page": 1, "line": 1}},
        "lines": lines,
    }
    return {"type": "BillingDoc", "doc": INVOICE_DOC, "data": data}


def _line(cat, label, amount, awb="AWB1", qty=None, rate=None, lane=None, line_no=1):
    return {
        "line_no": str(line_no), "awb": awb, "charge_label": label,
        "lane": lane, "qty": qty, "unit": "shpt" if cat != "freight" else "kg",
        "rate": rate, "amount": amount, "category": cat,
        "ref": {"page": 1, "line": line_no + 9},
    }


def _tracking(awb="AWB1", date="2032-02-10") -> dict:
    return {
        "type": "SheetMap", "doc": TRACK_DOC,
        "data": {
            "kind": "tracking_export", "sheet_number": 1,
            "columns": {"awb": "AWB", "event": "Event", "date": "Date"},
            "ref": {"page": 1, "line": 1},
        },
        "rows": [{"awb": awb, "event": "PICKED_UP", "date": date, "_line": 2}],
    }


# ---------------------------------------------------------------------------
# Fuel priced after freight regardless of line order
# ---------------------------------------------------------------------------

def test_fuel_priced_on_correct_freight_even_when_fuel_listed_first():
    """Fuel line comes before freight line on the invoice."""
    records = [
        _msa(),
        _invoice([
            _line("fuel", "Fuel surcharge", amount="60.00", qty=None, line_no=1,
                  lane="L1-L2"),
            _line("freight", "Air freight", amount="500.00", qty="50",
                  rate="10.00", lane="L1-L2", line_no=2),
        ]),
        _tracking(),
    ]
    case = Case.from_records(records, as_of="2032-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1
    # Correct freight: 50 * 6.00 = 300.00; fuel: 20% of 300 = 60.00.
    assert cands[0].corrects[0].amount == Decimal("360.00")


# ---------------------------------------------------------------------------
# Annex E alias → accessorial by code
# ---------------------------------------------------------------------------

def test_annex_e_alias_resolves_security_label_to_code():
    """Billed as 'Screening fee', alias maps to Security surcharge code."""
    records = [
        _msa(
            accessorials=[{
                "code": "SEC", "label": "Security surcharge",
                "rate": "0.25", "basis": "USD per kg",
                "basis_kind": "per_kg", "ref": {"page": 7, "line": 2},
            }],
            charge_code_aliases=[{
                "code": "SEC", "label": "Security surcharge",
                "aliases": ["Screening fee"],
                "ref": {"page": 7, "line": 1},
            }],
        ),
        _invoice([
            _line("freight", "Air freight", amount="300.00", qty="50",
                  rate="6.00", lane="L1-L2", line_no=1),
            _line("security", "Screening fee", amount="99.00", qty="50", line_no=2),
        ]),
        _tracking(),
    ]
    case = Case.from_records(records, as_of="2032-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1
    # Correct security: 0.25 * 50 = 12.50. billed 99.00 -> delta 86.50.
    delta = cands[0].billed_amount - cands[0].corrects[0].amount
    assert delta == Decimal("86.50")


# ---------------------------------------------------------------------------
# Accessorial months window
# ---------------------------------------------------------------------------

def test_accessorial_months_window_disallows_outside_months():
    """Peak-season surcharge billed in Feb when it only applies Sep-Nov."""
    records = [
        _msa(
            accessorials=[{
                "code": "PEAK", "label": "Peak surcharge",
                "rate": "100.00", "basis": "USD per shipment",
                "basis_kind": "per_shipment",
                "condition": "for pickups in September to November",
                "months": ["09", "10", "11"],
                "ref": {"page": 7, "line": 2},
            }],
        ),
        _invoice([
            _line("freight", "Air freight", amount="300.00", qty="50",
                  rate="6.00", lane="L1-L2", line_no=1),
            _line("accessorial", "Peak surcharge", amount="100.00", line_no=2),
        ]),
        _tracking(date="2032-02-10"),
    ]
    case = Case.from_records(records, as_of="2032-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1
    # Correct peak = 0 (outside months).
    delta = cands[0].billed_amount - cands[0].corrects[0].amount
    assert delta == Decimal("100.00")


# ---------------------------------------------------------------------------
# Judge-mediated condition: DG fee on refrigerant-only shipment (OC-02)
# ---------------------------------------------------------------------------

def test_dg_fee_zero_when_judge_says_condition_unmet():
    """DG billed; judge rules the DG clause does not apply (dry-ice only)."""
    records = [
        _msa(
            accessorials=[{
                "code": "DG", "label": "Dangerous goods fee",
                "rate": "284.91", "basis": "USD per shipment",
                "basis_kind": "per_shipment",
                "condition": "dangerous goods per IATA DGR, excluding refrigerant-only",
                "ref": {"page": 7, "line": 3},
            }],
        ),
        _invoice([
            _line("freight", "Air freight", amount="300.00", qty="50",
                  rate="6.00", lane="L1-L2", line_no=1),
            _line("accessorial", "Dangerous goods fee", amount="284.91", line_no=2),
        ]),
        _tracking(),
    ]
    answers = {
        "accessorial_condition:DG": {"answer": False, "ref": None},
    }
    from nova.case import fixture_judge
    case = Case.from_records(records, as_of="2032-12-31", judge=fixture_judge(answers))
    cands = run_overcharge(case)
    assert len(cands) == 1
    delta = cands[0].billed_amount - cands[0].corrects[0].amount
    assert delta == Decimal("284.91")


# ---------------------------------------------------------------------------
# INR invoice: convert finding once, at the Annex F rate for the invoice month
# ---------------------------------------------------------------------------

def test_inr_invoice_converts_finding_once_using_annex_f():
    records = [
        _msa(
            fx_rows=[{"month": "2032-02", "rate": "80.00",
                      "ref": {"page": 10, "line": 1}}],
        ),
        _invoice(
            [_line("freight", "Air freight", amount="80000.00",
                   qty="50", rate="1600.00", lane="L1-L2", line_no=1)],
            currency="INR",
            invoice_date="2032-02-15",
        ),
        _tracking(),
    ]
    case = Case.from_records(records, as_of="2032-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1
    # Correct in INR: 50*6.00 = 300; billed INR 80000; USD at 80.00 →
    # billed=1000.00, correct=3.75 → delta 996.25.
    delta = cands[0].billed_amount - cands[0].corrects[0].amount
    assert cands[0].billed_amount == Decimal("1000.00")
    assert cands[0].corrects[0].amount == Decimal("3.75")
    assert delta == Decimal("996.25")


def test_inr_invoice_missing_fx_month_is_cannot_determine():
    records = [
        _msa(fx_rows=[{"month": "2032-01", "rate": "80.00",
                       "ref": {"page": 10, "line": 1}}]),
        _invoice(
            [_line("freight", "Air freight", amount="80000.00",
                   qty="50", rate="1600.00", lane="L1-L2", line_no=1)],
            currency="INR", invoice_date="2032-02-15",
        ),
        _tracking(),
    ]
    case = Case.from_records(records, as_of="2032-12-31")
    cands = run_overcharge(case)
    assert len(cands) == 1
    assert cands[0].corrects == []
    assert "cannot_determine" in cands[0].note
