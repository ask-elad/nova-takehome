"""Unit tests for the overcharge rule (glossary §Amounts).

Covers band edges (44 vs 44.5 vs 45), fuel on correct freight, minimum
charge takeover, and no-finding on correct bills.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from nova.case import Case
from nova.rules.overcharge import run as run_overcharge


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

CONTRACT_DOC = "batch_01/0001.eml#MSA.pdf"
INVOICE_DOC = "batch_01/0002.eml#INV.pdf"
TRACKING_DOC = "batch_01/0003.eml#tracking.xlsx"


def _make_contract(rate_rows: list[dict], fuel_rows: list[dict] | None = None,
                   accessorials: list[dict] | None = None) -> dict:
    """Minimal MSA with one period P1 covering all of 2032."""
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
        "rate_rows": rate_rows,
        "fuel_rows": fuel_rows,
        "accessorials": accessorials,
        "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
        "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
        "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
        "late_fee_compounding": False,
        "schedule1_rows": [],
    }
    return {"type": "ContractTerms", "doc": CONTRACT_DOC, "data": data}


def _rate(lane: str, band: str, lo, hi, rate_p1: str, is_min=False, line=10) -> dict:
    return {
        "lane": lane, "band": band,
        "band_min_kg": lo, "band_max_kg": hi,
        "is_minimum_charge": is_min,
        "rates": [{"period": "P1", "rate": rate_p1}],
        "ref": {"page": 8, "line": line},
    }


def _invoice(lines: list[dict], inv_id: str = "INV-1") -> dict:
    data = {
        "id": {"value": inv_id, "ref": {"page": 1, "line": 1}},
        "kind": "invoice",
        "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
        "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
        "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
        "invoice_date": {"value": "2032-02-01", "ref": {"page": 1, "line": 1}},
        "total": {"value": sum_amount(lines), "ref": {"page": 1, "line": 1}},
        "lines": lines,
    }
    return {"type": "BillingDoc", "doc": INVOICE_DOC, "data": data}


def sum_amount(lines: list[dict]) -> str:
    s = sum(Decimal(ln["amount"]) for ln in lines)
    return f"{s:.2f}"


def _freight_line(awb, lane, qty, rate, amount, line=9) -> dict:
    return {
        "line_no": "1", "awb": awb, "pickup_date": "2032-02-10",
        "charge_label": "Air freight", "lane": lane,
        "qty": str(qty), "unit": "kg", "rate": rate, "amount": amount,
        "category": "freight", "ref": {"page": 1, "line": line},
    }


def _fuel_line(awb, base, rate, amount, line=10) -> dict:
    return {
        "line_no": "2", "awb": awb, "pickup_date": "2032-02-10",
        "charge_label": "Fuel surcharge", "lane": "L1-L2",
        "qty": str(base), "unit": "%", "rate": rate, "amount": amount,
        "category": "fuel", "ref": {"page": 1, "line": line},
    }


def _tracking(awb: str, date: str) -> dict:
    return {
        "type": "SheetMap", "doc": TRACKING_DOC,
        "data": {
            "kind": "tracking_export", "sheet_number": 1,
            "columns": {"awb": "AWB", "event": "Event", "date": "Date"},
            "ref": {"page": 1, "line": 1},
        },
        "rows": [{"awb": awb, "event": "PICKED_UP", "date": date, "_line": 2}],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBandEdges:
    """44 kg → band 0-44.5; 44.5 → still 0-44.5; 45 → band 45-99.5."""

    RATES = [
        _rate("L1-L2", "0-44.5 kg", 0.0, 44.5, "10.00"),
        _rate("L1-L2", "45-99.5 kg", 45.0, 99.5, "6.00"),
    ]

    def _run(self, qty: str, billed_rate: str):
        amt = f"{(Decimal(qty) * Decimal(billed_rate)):.2f}"
        records = [
            _make_contract(self.RATES),
            _invoice([_freight_line("AWB1", "L1-L2", qty, billed_rate, amt)]),
            _tracking("AWB1", "2032-02-10"),
        ]
        case = Case.from_records(records, as_of="2032-12-31")
        return run_overcharge(case)

    def test_44_kg_uses_low_band(self):
        # Billed at 10.00 (= correct). No finding.
        cands = self._run("44", "10.00")
        assert cands == []

    def test_44_5_kg_uses_low_band(self):
        # Still inside 0-44.5. 10.00 is correct, so no finding.
        cands = self._run("44.5", "10.00")
        assert cands == []

    def test_45_kg_uses_high_band(self):
        # Billed at 10.00 (low band); correct is 6.00. Overcharge.
        cands = self._run("45", "10.00")
        assert len(cands) == 1
        billed = Decimal("45") * Decimal("10.00")
        correct = Decimal("45") * Decimal("6.00")
        assert cands[0].billed_amount == billed
        assert cands[0].corrects[0].amount == correct


class TestFuelOnCorrectFreight:
    RATES = [_rate("L1-L2", "100-299.5 kg", 100.0, 299.5,
                   rate_p1="6.01")]
    FUEL = [{"month": "2032-02", "rate": "20.00", "ref": {"page": 9, "line": 1}}]

    def test_fuel_applies_to_correct_freight_not_billed(self):
        # Billed freight at 6.69 (wrong), fuel at 20% of billed base.
        # Correct freight: 241 * 6.01 = 1448.41; correct fuel: 20% * 1448.41 = 289.682 -> 289.68.
        records = [
            _make_contract(self.RATES, fuel_rows=self.FUEL),
            _invoice([
                _freight_line("AWB1", "L1-L2", "241", "6.69", "1612.29"),
                _fuel_line("AWB1", "1612.29", "20.00", "322.46"),
            ]),
            _tracking("AWB1", "2032-02-10"),
        ]
        case = Case.from_records(records, as_of="2032-12-31")
        cands = run_overcharge(case)
        assert len(cands) == 1
        billed = Decimal("1612.29") + Decimal("322.46")
        correct = Decimal("1448.41") + Decimal("289.68")
        assert cands[0].billed_amount == billed
        assert cands[0].corrects[0].amount == correct


class TestMinimumCharge:
    """When rate × weight is below the minimum, the minimum applies."""

    RATES = [
        _rate("L1-L2", "minimum charge", None, None, rate_p1="74.00", is_min=True),
        _rate("L1-L2", "0-44.5 kg", 0.0, 44.5, "7.00"),
    ]

    def test_minimum_applies_when_lower(self):
        # 5 kg * 7.00 = 35.00 which is below the 74.00 minimum.
        # Correct = 74.00. Billed 100.00 (made up).
        records = [
            _make_contract(self.RATES),
            _invoice([_freight_line("AWB1", "L1-L2", "5", "20.00", "100.00")]),
            _tracking("AWB1", "2032-02-10"),
        ]
        case = Case.from_records(records, as_of="2032-12-31")
        cands = run_overcharge(case)
        assert len(cands) == 1
        assert cands[0].corrects[0].amount == Decimal("74.00")

    def test_minimum_ignored_when_higher(self):
        # 200 kg * 7.00 = 1400.00 which is above the 74.00 minimum.
        # Correct = 1400.00. Billed 1500.00.
        rates = [
            _rate("L1-L2", "minimum charge", None, None, rate_p1="74.00", is_min=True),
            _rate("L1-L2", "100-299.5 kg", 100.0, 299.5, "7.00"),
        ]
        records = [
            _make_contract(rates),
            _invoice([_freight_line("AWB1", "L1-L2", "200", "7.50", "1500.00")]),
            _tracking("AWB1", "2032-02-10"),
        ]
        case = Case.from_records(records, as_of="2032-12-31")
        cands = run_overcharge(case)
        assert len(cands) == 1
        assert cands[0].corrects[0].amount == Decimal("1400.00")


class TestNoFindingWhenBilledMatches:
    def test_correct_bill_is_no_finding(self):
        rates = [_rate("L1-L2", "0-44.5 kg", 0.0, 44.5, "7.73")]
        records = [
            _make_contract(rates),
            _invoice([_freight_line("AWB1", "L1-L2", "44", "7.73", "340.12")]),
            _tracking("AWB1", "2032-02-10"),
        ]
        case = Case.from_records(records, as_of="2032-12-31")
        assert run_overcharge(case) == []
