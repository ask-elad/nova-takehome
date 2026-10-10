"""Late-fee rules (glossary §Late fees).

- `late_fee_not_owed`: for each billed late-fee line that names the invoice
  it is charged on, work out the correct fee from the contract. Days late =
  paid date - due date, where the due date is the extended one if an
  authorised `payment_terms` person extended it. Inside the grace window
  the correct fee is 0. Otherwise ceil(days/30) months at the contract rate,
  simple or compound. Billed minus correct, in the invoice currency,
  converted to USD once per finding.

- `late_fee_risk`: for every unpaid invoice (register not showing paid /
  scheduled) with 0 < due - as_of ≤ 14, emit one month's fee on the open
  amount less the disputed amount, in the invoice's own currency, converted
  once.
"""
from __future__ import annotations

import math
from decimal import Decimal
from datetime import date
from typing import Optional

from nova.case import BillingRecord, Case, ContractRecord, SourceRef, _addr_of
from nova.money import CannotDetermine, inr_to_usd, round_half_up
from nova.rules import Candidate, CorrectAmount
from nova.schemas import Ref


def _parse(d: str) -> date:
    y, m, dd = d.split("-")
    return date(int(y), int(m), int(dd))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _authorised_extension(case: Case, msa: ContractRecord, invoice_id: str) -> Optional[tuple[str, SourceRef]]:
    """Return (new_date, source_ref) if an authorised payment_terms person
    extended the due date for invoice_id. Takes the latest such extension."""
    best: Optional[tuple[str, SourceRef]] = None
    for em in case.emails:
        for ext in (em.email.extensions or []):
            if ext.invoice != invoice_id:
                continue
            addr = em.true_sender()
            if not case.authority_of(addr, msa.id, "payment_terms"):
                continue
            ref = SourceRef.from_ref(em.doc, ext.ref)
            if best is None or ext.new_date > best[0]:
                best = (ext.new_date, ref)
    return best


def _register_lookup(case: Case, invoice_id: str) -> Optional[tuple[dict, SourceRef]]:
    """Latest payment-register row for invoice_id."""
    best: Optional[tuple[dict, SourceRef]] = None
    for s in case.sheets:
        if s.sheet.kind != "payment_register":
            continue
        for row in s.rows:
            if (row.get("invoice_id") or "").strip() != invoice_id:
                continue
            ref = Ref(page=row.get("_page", s.sheet.sheet_number),
                      line=row.get("_line", s.sheet.ref.line))
            sr = SourceRef.from_ref(s.doc, ref)
            # Keep the row with the latest paid_date, or the first open row.
            if best is None:
                best = (row, sr)
            else:
                pb = (best[0].get("paid_date") or "")
                pn = (row.get("paid_date") or "")
                if pn > pb:
                    best = (row, sr)
    return best


def _convert_once(amount: Decimal, bill: BillingRecord, case: Case) -> Optional[Decimal]:
    currency = (bill.bill.currency.value if bill.bill.currency else "USD").upper()
    if currency != "INR":
        return amount
    invoice_date = bill.bill.invoice_date.value if bill.bill.invoice_date else None
    msa = case.contract_for_invoice(bill)
    if invoice_date is None or msa is None:
        return None
    terms = case.terms_on(msa.id, invoice_date)
    fx = {fx.month: Decimal(fx.rate) for fx, _ in (terms.fx_rows if terms else [])}
    try:
        return inr_to_usd(amount, invoice_date, fx)
    except CannotDetermine:
        return None


def _correct_fee(principal: Decimal, rate_pct: Decimal, months: int,
                 compound: bool) -> Decimal:
    """Correct cumulative fee after `months` months at `rate_pct` percent/mo.

    Simple: fee each month = round_half_up(rate/100 * principal, 2).
    Compound: fee each month = round_half_up(rate/100 * (principal + fees_so_far), 2).
    """
    if months <= 0:
        return Decimal(0)
    rate = rate_pct / Decimal(100)
    total = Decimal(0)
    for _ in range(months):
        base = principal + (total if compound else Decimal(0))
        total += round_half_up(rate * base, 2)
    return total


# ---------------------------------------------------------------------------
# late_fee_not_owed
# ---------------------------------------------------------------------------

def _run_not_owed(case: Case) -> list[Candidate]:
    out: list[Candidate] = []
    as_of = _parse(case.as_of)
    for bill in case.billings:
        if bill.bill.kind != "invoice":
            continue
        msa = case.contract_for_invoice(bill)
        if msa is None:
            continue

        late_lines = [ln for ln in bill.bill.lines
                      if ln.category == "late_fee" and ln.refers_to_invoice]
        if not late_lines:
            continue
        rate = Decimal(msa.terms.late_fee_rate.value)
        grace = int(msa.terms.payment_grace_days.value)
        compound = bool(msa.terms.late_fee_compounding)

        billed_total = Decimal(0)
        correct_total = Decimal(0)
        evidence: list[SourceRef] = []
        unresolved = False

        for ln in late_lines:
            target = ln.refers_to_invoice
            # The target invoice's due date and paid date come from the register,
            # or from an in-case BillingDoc for the target.
            reg = _register_lookup(case, target)
            if reg is None:
                unresolved = True
                continue
            row, reg_ref = reg
            due_s = (row.get("due_date") or "").replace("due", "").strip()
            paid_s = (row.get("paid_date") or "").strip()
            principal_s = (row.get("amount") or "").replace("USD", "").replace("INR", "").strip()
            if not due_s or not paid_s or paid_s == "-" or not principal_s:
                unresolved = True
                continue

            # Apply any authorised extension.
            ext = _authorised_extension(case, msa, target)
            if ext is not None:
                due_s = ext[0]
                evidence.append(ext[1])

            principal = Decimal(principal_s)
            days_late = (_parse(paid_s) - _parse(due_s)).days
            if days_late <= grace:
                correct = Decimal(0)
            else:
                months = math.ceil(days_late / 30)
                correct = _correct_fee(principal, rate, months, compound)

            billed_amt = Decimal(ln.amount)
            billed_total += billed_amt
            correct_total += correct
            evidence.append(reg_ref)
            evidence.append(SourceRef.from_ref(bill.doc, ln.ref))

        if unresolved and billed_total - correct_total <= 0:
            continue
        delta = billed_total - correct_total
        if delta <= 0:
            continue
        # Audit minors: convert the delta once (keeps billed and correct
        # in exact lock-step without a 1-cent drift between two
        # independent conversions).
        converted_billed = _convert_once(billed_total, bill, case)
        delta_usd = _convert_once(billed_total - correct_total, bill, case)
        converted_correct = (
            converted_billed - delta_usd
            if converted_billed is not None and delta_usd is not None
            else None
        )
        if converted_billed is None or converted_correct is None:
            out.append(Candidate(
                key=("late_fee_not_owed", bill.bill.id.value),
                class_="late_fee_not_owed",
                billed_amount=billed_total,
                corrects=[],
                evidence=evidence,
                note="cannot_determine",
            ))
            continue
        if converted_billed - converted_correct <= 0:
            continue
        out.append(Candidate(
            key=("late_fee_not_owed", bill.bill.id.value),
            class_="late_fee_not_owed",
            billed_amount=converted_billed,
            corrects=[CorrectAmount(amount=converted_correct, sources=evidence,
                                    authority_level=1, in_force=True)],
            evidence=evidence,
        ))
    return out


# ---------------------------------------------------------------------------
# late_fee_risk
# ---------------------------------------------------------------------------

def _run_risk(case: Case) -> list[Candidate]:
    out: list[Candidate] = []
    as_of = _parse(case.as_of)
    for bill in case.billings:
        if bill.bill.kind != "invoice":
            continue
        if bill.bill.due_date is None:
            continue
        due = _parse(bill.bill.due_date.value)
        days = (due - as_of).days
        if not (0 < days <= 14):
            continue
        # Must be unpaid in the register (open) if a register row exists.
        reg = _register_lookup(case, bill.bill.id.value)
        if reg is not None:
            status = (reg[0].get("status") or "").strip().lower()
            paid = (reg[0].get("paid_date") or "").strip()
            if status in {"paid", "scheduled"} or (paid and paid != "-"):
                continue
        msa = case.contract_for_invoice(bill)
        if msa is None:
            continue
        rate = Decimal(msa.terms.late_fee_rate.value)
        principal = Decimal(bill.bill.total.value)
        # TODO: subtract disputed amounts. Phase 5 wires that.
        fee = round_half_up(rate / Decimal(100) * principal, 2)
        converted = _convert_once(fee, bill, case)
        evidence = [SourceRef.from_ref(bill.doc, bill.bill.total.ref),
                    SourceRef.from_ref(msa.doc, msa.terms.late_fee_rate.ref)]
        if converted is None:
            continue
        out.append(Candidate(
            key=("late_fee_risk", bill.bill.id.value),
            class_="late_fee_risk",
            billed_amount=converted,
            corrects=[CorrectAmount(amount=Decimal(0), sources=evidence,
                                    authority_level=1, in_force=True)],
            evidence=evidence,
            deadline=bill.bill.due_date.value,
        ))
    return out


def run(case: Case) -> list[Candidate]:
    return _run_not_owed(case) + _run_risk(case)
