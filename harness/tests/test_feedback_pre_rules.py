"""Task 07 Part D gap: pre-rules feedback facts flow into the Case.

Shape is modelled on data/scenarios/feedback/W1_batch_01.json (close +
rate_accepted) but every id and name is made up — the hidden grader run
has new carriers and lanes.

Covers:
- ``rate_accepted`` admits a notice whose sender isn't on Schedule 1, so
  a later invoice billed at the notice rate stops producing an overcharge.
- The same notice priced into a later invoice at a HIGHER rate still
  produces an overcharge, measured against the notice (with learned_at
  provided by the harness, not under test here).
- ``sender_authority`` grants a person a category: the next waiver that
  person writes becomes a waived_but_billed finding.
"""
from __future__ import annotations

from decimal import Decimal

from nova.case import Case
from nova.rules.overcharge import run as run_overcharge
from nova.rules.waived_but_billed import run as run_waived


MSA_DOC = "batch_01/0001.eml#MSA.pdf"
INV_DOC = "batch_01/0003.eml#INV.pdf"
NOTICE_DOC = "batch_01/0004.eml"
WAIVER_DOC = "batch_01/0007.eml"
TRACK_DOC = "batch_01/0005.eml#tracking.xlsx"


def _msa(rates_sched1_email: str = "rates@tbx.example") -> dict:
    return {
        "type": "ContractTerms", "doc": MSA_DOC,
        "data": {
            "id": {"value": "CDA-01", "ref": {"page": 1, "line": 1}},
            "kind": "msa", "parties": ["TBX", "QMP"],
            "dated": {"value": "2034-12-01", "ref": {"page": 1, "line": 1}},
            "effective_from": {"value": "2035-01-01", "ref": {"page": 1, "line": 1}},
            "end_date": {"value": "2035-12-31", "ref": {"page": 1, "line": 1}},
            "auto_renewal": False,
            "rate_periods": [{"label": "P1", "start": "2035-01-01",
                               "end": "2035-12-31", "ref": {"page": 2, "line": 1}}],
            "rate_rows": [{
                "lane": "LX-LY", "band": "0-199.5 kg",
                "band_min_kg": 0.0, "band_max_kg": 199.5,
                "is_minimum_charge": False,
                "rates": [{"period": "P1", "rate": "5.00"}],
                "ref": {"page": 8, "line": 10},
            }],
            "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
            "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
            "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
            "late_fee_compounding": False,
            "schedule1_rows": [{
                "name": "R Rates", "title": "Rates", "party": "TBX",
                "email": rates_sched1_email,
                "categories": ["rates"],
                "ref": {"page": 11, "line": 1},
            }],
        },
    }


def _rate_notice_email(rate: str = "4.00",
                       sender: str = "Outsider <outsider@tbx.example>") -> dict:
    """A rate notice from someone NOT on Schedule 1."""
    return {
        "type": "EmailFacts", "doc": NOTICE_DOC,
        "data": {
            "received_at": {"value": "2035-03-06", "ref": {"page": 1, "line": 1}},
            "sender": {"value": sender, "ref": {"page": 1, "line": 2}},
            "subject": {"value": "Rate notice LX-LY", "ref": {"page": 1, "line": 3}},
            "kind": "rate_notice",
            "own_lines": [{"ref": {"page": 1, "line": 10, "line_end": 20}}],
            "quoted_lines": [],
            "rate_notice": {
                "reference": {"value": "RN-LX-LY-01", "ref": {"page": 1, "line": 5}},
                "lane": "LX-LY",
                "effective_from": {"value": "2035-03-13",
                                    "ref": {"page": 1, "line": 6}},
                "effective_to": {"value": "2035-09-25",
                                  "ref": {"page": 1, "line": 7}},
                "rows": [{
                    "lane": "LX-LY", "band": "0-199.5 kg",
                    "rate": rate, "currency": "USD",
                    "ref": {"page": 1, "line": 15},
                }],
                "ref": {"page": 1, "line": 15},
            },
        },
    }


def _invoice(invoice_date: str, billed_rate: str, qty: str = "50",
             inv_id: str = "INV-APR") -> dict:
    amount = str(Decimal(billed_rate) * Decimal(qty))
    return {
        "type": "BillingDoc", "doc": INV_DOC,
        "data": {
            "id": {"value": inv_id, "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "TBX", "ref": {"page": 1, "line": 1}},
            "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "CDA-01", "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": invoice_date, "ref": {"page": 1, "line": 1}},
            "total": {"value": amount, "ref": {"page": 1, "line": 1}},
            "lines": [{
                "line_no": "1", "awb": "AWB-APR", "charge_label": "Air freight",
                "lane": "LX-LY", "qty": qty, "unit": "kg", "rate": billed_rate,
                "amount": amount, "category": "freight",
                "ref": {"page": 1, "line": 10},
            }],
        },
    }


def _tracking(date: str) -> dict:
    return {
        "type": "SheetMap", "doc": TRACK_DOC,
        "data": {
            "kind": "tracking_export", "sheet_number": 1,
            "columns": {"awb": "AWB", "event": "Event", "date": "Date"},
            "ref": {"page": 1, "line": 1},
        },
        "rows": [{"awb": "AWB-APR", "event": "PICKED_UP", "date": date,
                  "_line": 2}],
    }


def test_rate_accepted_admits_an_outsider_rate_notice():
    """Without feedback, the outsider notice is ignored and the invoice looks
    like a 5.00→4.00 overcharge. With rate_accepted, the notice is admitted
    and the matched-rate invoice becomes no_finding.
    """
    records = [
        _msa(),
        _rate_notice_email(rate="4.00"),
        _invoice(invoice_date="2035-04-10", billed_rate="4.00"),
        _tracking(date="2035-04-01"),
    ]
    # Without feedback: outsider's notice has no authority → the 4.00 bill
    # is 1.00/kg below the MSA 5.00/kg so it isn't an overcharge anyway.
    base = Case.from_records(records, as_of="2035-10-31")
    base_cands = run_overcharge(base)
    assert base_cands == []

    # With rate_accepted + invoice billed ABOVE the notice: finding at the
    # notice rate; the invoice billed AT the notice is fine.
    high_bill = [
        _msa(),
        _rate_notice_email(rate="4.00"),
        _invoice(invoice_date="2035-04-10", billed_rate="4.50"),
        _tracking(date="2035-04-01"),
    ]
    prf = {"rate_accepted": [{
        "contract_id": "CDA-01", "lane": "LX-LY",
        "sent_by": "Outsider", "sent_on": "2035-03-06",
        "effective_from": "2035-03-13", "effective_to": "2035-09-25",
        "valid_from": "2035-03-13", "valid_to": "2035-09-25",
    }]}
    case_with = Case.from_records(high_bill, as_of="2035-10-31",
                                   pre_rule_facts=prf)
    cands_with = run_overcharge(case_with)
    assert len(cands_with) == 1
    c = cands_with[0]
    # correct against the notice: 4.00 * 50 = 200.00; billed 4.50*50 = 225.00.
    notice_correct = next(x for x in c.corrects if x.source_kind == "rate_notice")
    assert notice_correct.amount == Decimal("200.00")


def test_sender_authority_lets_a_waiver_count():
    """Without feedback, a waiver from an outsider gives no finding. A
    sender_authority grant for ``waivers`` on that contract turns the next
    waiver into a waived_but_billed finding.
    """
    outsider_email = "outsider.waiver@tbx.example"
    waiver_email = {
        "type": "EmailFacts", "doc": WAIVER_DOC,
        "data": {
            "received_at": {"value": "2035-04-05",
                             "ref": {"page": 1, "line": 1}},
            "sender": {"value": f"Outsider <{outsider_email}>",
                        "ref": {"page": 1, "line": 2}},
            "subject": {"value": "Waiver",
                         "ref": {"page": 1, "line": 3}},
            "kind": "waiver",
            "own_lines": [{"ref": {"page": 1, "line": 10,
                                    "line_end": 20}}],
            "quoted_lines": [],
            "waivers": [{
                "charge": "Delivery fee",
                "awb": "AWB-APR", "invoice": None, "month": None,
                "condition": None,
                "ref": {"page": 1, "line": 15},
            }],
        },
    }
    msa_with_charge_code = _msa()
    msa_with_charge_code["data"]["accessorials"] = [{
        "code": "DEL", "label": "Delivery fee",
        "rate": "116.13", "basis": "USD per shipment",
        "basis_kind": "per_shipment",
        "ref": {"page": 7, "line": 1},
    }]
    msa_with_charge_code["data"]["charge_code_aliases"] = [{
        "code": "DEL", "label": "Delivery fee",
        "aliases": ["Delivery fee"], "ref": {"page": 7, "line": 2},
    }]
    invoice_with_delivery = {
        "type": "BillingDoc", "doc": INV_DOC,
        "data": {
            "id": {"value": "INV-APR", "ref": {"page": 1, "line": 1}},
            "kind": "invoice",
            "issuer": {"value": "TBX", "ref": {"page": 1, "line": 1}},
            "currency": {"value": "USD", "ref": {"page": 1, "line": 1}},
            "contract_ref": {"value": "CDA-01", "ref": {"page": 1, "line": 1}},
            "invoice_date": {"value": "2035-04-10",
                              "ref": {"page": 1, "line": 1}},
            "total": {"value": "116.13", "ref": {"page": 1, "line": 1}},
            "lines": [{
                "line_no": "1", "awb": "AWB-APR",
                "charge_label": "Delivery fee",
                "lane": None, "qty": "1", "unit": "shpt", "rate": "116.13",
                "amount": "116.13", "category": "accessorial",
                "ref": {"page": 1, "line": 10},
            }],
        },
    }
    base_records = [msa_with_charge_code, waiver_email, invoice_with_delivery]
    base_case = Case.from_records(base_records, as_of="2035-10-31")
    assert run_waived(base_case) == []

    prf = {"sender_authority": [{
        "email": outsider_email, "contract_id": "CDA-01",
        "categories": ["waivers"],
        "valid_from": "2035-04-01", "valid_to": None,
    }]}
    case_with = Case.from_records(base_records, as_of="2035-10-31",
                                   pre_rule_facts=prf)
    cands = run_waived(case_with)
    assert len(cands) == 1
    assert cands[0].class_ == "waived_but_billed"
    assert cands[0].billed_amount == Decimal("116.13")
