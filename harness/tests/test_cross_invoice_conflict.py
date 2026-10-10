"""Audit B1 (finish): an open conflict on another invoice's lane makes a
clean dispute on the same (contract, lane, period) escalate to human
review in autonomous mode."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "harness.py"
sys.path.insert(0, str(HARNESS.parent))
harness = importlib.import_module("harness")


class _Line:
    def __init__(self, awb, lane):
        self.awb = awb
        self.lane = lane


class _Bill:
    def __init__(self, invoice_id, lines, contract_ref):
        class _V:
            def __init__(self, v): self.value = v
        self.id = _V(invoice_id)
        self.lines = lines
        self.contract_ref = _V(contract_ref)


class _BillingRecord:
    def __init__(self, invoice_id, lane, contract):
        self.bill = _Bill(invoice_id, [_Line("AWB-"+invoice_id, lane)], contract)


class _Sheet:
    kind = "tracking_export"
    rows = []


class _SheetRec:
    sheet = _Sheet()


class _Case:
    billings = []
    sheets = []
    shipments = []
    contracts = []

    def contract_for_invoice(self, b):
        return None

    def msa_for(self, cid):
        return None

    def pickup_date(self, awb):
        return None

    def period_for(self, msa, d):
        return None


class _Item:
    def __init__(self, id_, cls, verdict, invoice_id):
        self.id = id_
        self.class_ = cls
        self.verdict = verdict
        self.invoice_id = invoice_id
        self.missing_doc = None


def test_conflict_on_other_invoice_blocks_autonomous():
    case = _Case()
    case.billings = [
        _BillingRecord("INV-A", "USX1-USX2", "C1"),
        _BillingRecord("INV-B", "USX1-USX2", "C1"),
    ]
    items = [
        _Item("overcharge:INV-A", "overcharge", "conflict", "INV-A"),
        _Item("overcharge:INV-B", "overcharge", "finding", "INV-B"),
    ]
    flags = harness._flags_from_case(items, case, feedback_items=[])
    # INV-B's dispute must now carry the same-key-conflict flag, forcing
    # human_review in autonomous mode.
    assert flags["overcharge:INV-B"].has_same_key_conflict is True


def test_conflict_on_different_lane_does_not_block():
    case = _Case()
    case.billings = [
        _BillingRecord("INV-A", "USX1-USX2", "C1"),
        _BillingRecord("INV-B", "USX1-INX3", "C1"),
    ]
    items = [
        _Item("overcharge:INV-A", "overcharge", "conflict", "INV-A"),
        _Item("overcharge:INV-B", "overcharge", "finding", "INV-B"),
    ]
    flags = harness._flags_from_case(items, case, feedback_items=[])
    assert flags["overcharge:INV-B"].has_same_key_conflict is False
