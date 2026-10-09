"""Duplicate rule (glossary §Duplicates).

Two patterns:

- **Same invoice number resent**: a BillingDoc with the same invoice id
  appears more than once. If the payment-register row for that id shows the
  first copy paid or scheduled and the resend still asks for payment (not a
  copy / reminder / for-your-records), flag as a finding on the resend. The
  amount is the invoice total.

- **Same AWB + charge code billed on two invoices**: match billing lines by
  (awb, resolved Annex-E charge code) across different invoices on the same
  contract. The later invoice carries the finding, for the sum of the
  duplicated lines on that invoice only. Credit notes that cover the same
  (awb, code) are subtracted (overlap minus the credit).

The rule returns one Candidate per flagged invoice. INR invoices convert
once per finding using Annex F for the invoice-date month.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from nova.case import BillingRecord, Case, SourceRef
from nova.money import CannotDetermine, inr_to_usd, round_half_up
from nova.rules import Candidate, CorrectAmount
from nova.schemas import Ref


def _received_key(bill: BillingRecord) -> tuple:
    """Sort key: received_at (fallback to invoice_date, else empty)."""
    rec = bill.received_at.isoformat() if bill.received_at else ""
    inv_d = bill.bill.invoice_date.value if bill.bill.invoice_date else ""
    return (rec or inv_d, inv_d, bill.doc)


def _asks_for_payment(bill: BillingRecord) -> bool:
    bd = bill.bill
    if bd.is_copy or bd.is_reminder or bd.is_for_your_records:
        return False
    return bd.asks_for_payment


def _register_rows(case: Case) -> list[tuple[str, SourceRef, dict]]:
    """Return (invoice_id, source_ref, row) for every payment-register row."""
    out: list[tuple[str, SourceRef, dict]] = []
    for s in case.sheets:
        if s.sheet.kind != "payment_register":
            continue
        for row in s.rows:
            inv = row.get("invoice_id", "").strip()
            if not inv:
                continue
            ref = Ref(page=row.get("_page", s.sheet.sheet_number),
                      line=row.get("_line", s.sheet.ref.line))
            out.append((inv, SourceRef.from_ref(s.doc, ref), row))
    return out


def _convert_if_inr(amount: Decimal, bill: BillingRecord, case: Case) -> Optional[Decimal]:
    currency = (bill.bill.currency.value if bill.bill.currency else "USD").upper()
    if currency != "INR":
        return amount
    invoice_date = bill.bill.invoice_date.value if bill.bill.invoice_date else None
    msa = case.contract_for_invoice(bill)
    if invoice_date is None or msa is None:
        return None
    terms = case.terms_on(msa.id, invoice_date)
    fx = {fx_row.month: Decimal(fx_row.rate) for fx_row, _ in (terms.fx_rows if terms else [])}
    try:
        return inr_to_usd(amount, invoice_date, fx)
    except CannotDetermine:
        return None


# ---------------------------------------------------------------------------
# Same-invoice-number resend
# ---------------------------------------------------------------------------

def _run_same_number(case: Case) -> list[Candidate]:
    by_id: dict[str, list[BillingRecord]] = {}
    for b in case.billings:
        if b.bill.kind != "invoice":
            continue
        by_id.setdefault(b.bill.id.value, []).append(b)

    reg_rows = _register_rows(case)
    reg_by_id: dict[str, list[tuple[SourceRef, dict]]] = {}
    for inv, src, row in reg_rows:
        reg_by_id.setdefault(inv, []).append((src, row))

    out: list[Candidate] = []
    for inv_id, bills in by_id.items():
        if len(bills) < 2:
            continue
        bills_sorted = sorted(bills, key=_received_key)
        first = bills_sorted[0]
        # Pick a resend that still asks for payment.
        resend: Optional[BillingRecord] = None
        for later in bills_sorted[1:]:
            if _asks_for_payment(later):
                resend = later
                break
        if resend is None:
            continue
        # Register must show the first copy paid or scheduled.
        reg = reg_by_id.get(inv_id, [])
        if not reg:
            continue
        reg_src, reg_row = reg[0]
        status = (reg_row.get("status") or "").strip().lower()
        paid = (reg_row.get("paid_date") or "").strip()
        if status not in {"paid", "scheduled"} and not paid:
            continue

        total = Decimal(resend.bill.total.value)
        converted = _convert_if_inr(total, resend, case)
        evidence = [reg_src, SourceRef.from_ref(resend.doc, resend.bill.total.ref)]

        if converted is None:
            out.append(Candidate(
                key=("duplicate", inv_id),
                class_="duplicate",
                billed_amount=total,
                corrects=[],
                evidence=evidence,
                note="cannot_determine: INR without FX month",
            ))
            continue
        out.append(Candidate(
            key=("duplicate", inv_id),
            class_="duplicate",
            billed_amount=converted,
            corrects=[CorrectAmount(amount=Decimal(0), sources=evidence,
                                    authority_level=3, in_force=True)],
            evidence=evidence,
        ))
    return out


# ---------------------------------------------------------------------------
# Different-invoice, same (AWB, charge-code) duplicate
# ---------------------------------------------------------------------------

def _line_code(case: Case, bill: BillingRecord, line) -> Optional[str]:
    msa = case.contract_for_invoice(bill)
    if msa is None:
        return None
    code = case.charge_code_for_label(msa, line.charge_label)
    if code:
        return code
    # Fallback: category is a crude code when no alias/annex D row exists.
    return None


def _run_awb_code(case: Case) -> list[Candidate]:
    invoices = [b for b in case.billings if b.bill.kind == "invoice"]
    credit_notes = [b for b in case.billings if b.bill.kind == "credit_note"]

    # Build (awb, code) → list of (bill, line_idx, amount) for invoices.
    inv_lines: list[tuple[BillingRecord, int, str, str, Decimal]] = []
    for b in invoices:
        for i, ln in enumerate(b.bill.lines):
            if not ln.awb:
                continue
            code = _line_code(case, b, ln)
            if code is None:
                continue
            inv_lines.append((b, i, ln.awb, code, Decimal(ln.amount)))

    # Group pairs with same contract, same (awb, code), same amount.
    out: list[Candidate] = []
    # For each candidate "later" invoice, we'll collect lines duplicated by
    # some earlier invoice on the same contract.
    for later_bill, i, awb, code, amt in inv_lines:
        later_date = later_bill.bill.invoice_date.value if later_bill.bill.invoice_date else ""
        later_contract = (later_bill.bill.contract_ref.value if later_bill.bill.contract_ref else None)
        for earlier_bill, j, awb2, code2, amt2 in inv_lines:
            if earlier_bill is later_bill:
                continue
            if awb != awb2 or code != code2 or amt != amt2:
                continue
            earlier_contract = (earlier_bill.bill.contract_ref.value if earlier_bill.bill.contract_ref else None)
            if later_contract != earlier_contract:
                continue
            earlier_date = earlier_bill.bill.invoice_date.value if earlier_bill.bill.invoice_date else ""
            if not (earlier_date and later_date and earlier_date < later_date):
                continue
            if later_bill.bill.id.value == earlier_bill.bill.id.value:
                continue  # that's the same-number pattern

            # Credit notes against (awb, code) on this contract.
            credited = Decimal(0)
            for cn in credit_notes:
                if (cn.bill.contract_ref.value if cn.bill.contract_ref else None) != later_contract:
                    continue
                for cl in cn.bill.lines:
                    if cl.awb == awb and _line_code(case, cn, cl) == code:
                        credited += Decimal(cl.amount)
            overlap = amt - credited
            if overlap <= 0:
                continue

            later_line = later_bill.bill.lines[i]
            earlier_line = earlier_bill.bill.lines[j]
            # Resolve MSA for Annex E alias evidence.
            msa = case.contract_for_invoice(later_bill)
            evidence = [
                SourceRef.from_ref(earlier_bill.doc, earlier_line.ref),
                SourceRef.from_ref(later_bill.doc, later_line.ref),
            ]
            if msa is not None:
                for alias in (msa.terms.charge_code_aliases or []):
                    if alias.code == code:
                        evidence.append(SourceRef.from_ref(msa.doc, alias.ref))
                        break

            converted = _convert_if_inr(overlap, later_bill, case)
            if converted is None:
                out.append(Candidate(
                    key=("duplicate", later_bill.bill.id.value),
                    class_="duplicate",
                    billed_amount=overlap,
                    corrects=[],
                    evidence=evidence,
                    note="cannot_determine: INR without FX month",
                ))
            else:
                out.append(Candidate(
                    key=("duplicate", later_bill.bill.id.value),
                    class_="duplicate",
                    billed_amount=round_half_up(converted, 2),
                    corrects=[CorrectAmount(amount=Decimal(0), sources=evidence,
                                            authority_level=3, in_force=True)],
                    evidence=evidence,
                ))
            break  # one earlier match per later line is enough
    # Merge candidates for the same later invoice.
    merged: dict[str, Candidate] = {}
    for c in out:
        key = c.key[1]
        if key in merged:
            m = merged[key]
            m.billed_amount += c.billed_amount
            if m.corrects and c.corrects:
                m.corrects[0].amount = Decimal(0)
                m.corrects[0].sources = m.corrects[0].sources + c.corrects[0].sources
            m.evidence.extend(c.evidence)
        else:
            merged[key] = c
    return list(merged.values())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(case: Case) -> list[Candidate]:
    same = _run_same_number(case)
    awb_code = _run_awb_code(case)
    # If both patterns fire on the same invoice, prefer the same-number result.
    seen = {c.key[1] for c in same}
    return same + [c for c in awb_code if c.key[1] not in seen]
