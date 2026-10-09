"""Unit tests for the waived_but_billed rule (glossary §Waivers).

Covers non-authorised senders and quoted-only waivers (cannot_determine).
"""
from __future__ import annotations

from decimal import Decimal

from nova.case import Case
from nova.rules.waived_but_billed import run as run_waived


CONTRACT_DOC = "batch_01/0001.eml#MSA.pdf"
INVOICE_DOC = "batch_01/0002.eml#INV.pdf"
EMAIL_DOC = "batch_01/0003.eml"


def _msa(schedule1: list[dict]) -> dict:
    return {
        "type": "ContractTerms", "doc": CONTRACT_DOC,
        "data": {
            "id": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "kind": "msa", "parties": ["A", "B"],
            "dated": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
            "effective_from": {"value": "2032-01-01", "ref": {"page": 1, "line": 1}},
            "end_date": {"value": "2032-12-31", "ref": {"page": 1, "line": 1}},
            "auto_renewal": False,
            "rate_periods": [], "rate_rows": [],
            "accessorials": [{
                "code": "DLV", "label": "Delivery fee",
                "rate": "100.00", "basis": "USD per shipment",
                "basis_kind": "per_shipment", "ref": {"page": 10, "line": 8},
            }],
            "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
            "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
            "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
            "late_fee_compounding": False,
            "schedule1_rows": schedule1,
        },
    }


def _invoice(line_amount: str = "100.00") -> dict:
    return {
        "type": "BillingDoc", "doc": INVOICE_DOC,
        "data": {
            "id": {"value": "INV-1", "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "A", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "C1", "ref": {"page": 1, "line": 1}},
            "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": "2032-02-01", "ref": {"page": 1, "line": 1}},
            "total": {"value": line_amount, "ref": {"page": 1, "line": 10}},
            "lines": [{
                "line_no": "1", "awb": "AWB-X", "charge_label": "Delivery fee",
                "lane": "L", "qty": "1", "unit": "shpt", "rate": line_amount,
                "amount": line_amount, "category": "accessorial",
                "ref": {"page": 1, "line": 9},
            }],
        },
    }


def _email(sender_email: str, own_lines: list[int], quoted_lines: list[int],
           waiver_line: int, awb: str = "AWB-X") -> dict:
    return {
        "type": "EmailFacts", "doc": EMAIL_DOC,
        "data": {
            "kind": "waiver",
            "sender": {"value": f"X <{sender_email}>", "ref": {"page": 1, "line": 1}},
            "own_lines": [{"ref": {"page": 1, "line": n}} for n in own_lines],
            "quoted_lines": [{"ref": {"page": 1, "line": n}} for n in quoted_lines],
            "waivers": [{"charge": "Delivery fee", "awb": awb,
                         "ref": {"page": 1, "line": waiver_line}}],
        },
    }


AUTH = [{"name": "Pat", "title": "Lead", "party": "A",
         "categories": ["waivers"],
         "email": "pat@carrier.example", "ref": {"page": 11, "line": 7}}]
AUTH_WITH_KAM = AUTH + [{"name": "Kam", "title": "KAM", "party": "A",
                         "categories": ["notices"],
                         "email": "kam@carrier.example", "ref": {"page": 11, "line": 5}}]


def test_non_authorised_sender_gives_no_finding():
    recs = [_msa(AUTH), _invoice(),
            _email("random@elsewhere.example", own_lines=[8], quoted_lines=[],
                   waiver_line=8)]
    cands = run_waived(Case.from_records(recs, as_of="2032-03-01"))
    assert cands == []


def test_authorised_sender_gives_finding():
    recs = [_msa(AUTH), _invoice(),
            _email("pat@carrier.example", own_lines=[8], quoted_lines=[],
                   waiver_line=8)]
    cands = run_waived(Case.from_records(recs, as_of="2032-03-01"))
    assert len(cands) == 1
    assert cands[0].class_ == "waived_but_billed"
    assert cands[0].billed_amount == Decimal("100.00")


def test_quoted_only_waiver_is_cannot_determine():
    recs = [_msa(AUTH_WITH_KAM), _invoice(),
            _email("pat@carrier.example", own_lines=[6], quoted_lines=[20],
                   waiver_line=20)]
    cands = run_waived(Case.from_records(recs, as_of="2032-03-01"))
    assert len(cands) == 1
    c = cands[0]
    assert c.corrects == []
    assert c.missing_doc is not None
    assert c.missing_doc[1].get("person") == "Kam"
    assert "cannot_determine" in c.note
