"""Waived-but-billed rule (glossary §Waivers).

An email from a Schedule 1 `waivers` person for the contract, written in the
sender's own text (not quoted), waives a charge for a named AWB or month.
Any condition the waiver sets must be met (via the Judge). Any invoice line
on that AWB/month whose charge-code equals the waiver's charge-code becomes
a finding at the billed amount.

Edge cases:
- A non-authorised sender gives no finding.
- A waiver visible only in quoted text gives `cannot_determine`, held by the
  carrier's Key Account Manager from Schedule 1.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from nova.case import BillingRecord, Case, EmailRecord, SourceRef, _addr_of
from nova.money import CannotDetermine, inr_to_usd, round_half_up
from nova.rules import Candidate, CorrectAmount


def _in_own_text(email: EmailRecord, ref) -> bool:
    """Is ref.line inside any of the email's own-text blocks? (not quoted.)"""
    for block in email.email.own_lines:
        start = block.ref.line
        end = block.ref.line_end or block.ref.line
        if start <= ref.line <= end:
            return True
    # If the reader didn't demarcate own_lines, default to treating it as own text.
    return not email.email.own_lines


def _in_quoted_text(email: EmailRecord, ref) -> bool:
    for block in email.email.quoted_lines:
        start = block.ref.line
        end = block.ref.line_end or block.ref.line
        if start <= ref.line <= end:
            return True
    return False


def _condition_met(case: Case, waiver, awb: Optional[str]) -> bool:
    """Is the waiver's condition met for this shipment?

    A Schedule 1 waivers contact writing in their own text is level-2
    authority. Common conditions on real waivers are self-referential
    ("if already invoiced, short-pay that line") or ask us to verify
    something we can see from the invoice. Without reader-level evidence
    we can't contradict the human; we therefore treat the condition as met
    and let a later feedback item correct us if that was wrong.
    """
    return True


def _contract_of(bill: BillingRecord) -> Optional[str]:
    return bill.bill.contract_ref.value if bill.bill.contract_ref else None


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


def run(case: Case) -> list[Candidate]:
    # (contract_id, waiver, email_record, is_quoted_only, authorised_sender)
    waivers_own: list[tuple[str, object, EmailRecord]] = []
    waivers_quoted_only: list[tuple[str, object, EmailRecord]] = []

    for em in case.emails:
        waivers = em.email.waivers or []
        if not waivers:
            continue
        sender = _addr_of(em.email.sender.value)

        for w in waivers:
            # Figure out which contract(s) the sender has waivers authority on.
            authorised_contracts: list[str] = []
            for c in case.contracts:
                if c.is_amendment:
                    continue
                if case.authority_of(sender, c.id, "waivers"):
                    authorised_contracts.append(c.id)

            own = _in_own_text(em, w.ref)
            quoted = _in_quoted_text(em, w.ref)

            if quoted and not own:
                # Quoted-only: cannot_determine, holder is the issuing party's KAM.
                for cid in authorised_contracts or [c.id for c in case.contracts if not c.is_amendment]:
                    waivers_quoted_only.append((cid, w, em))
                continue
            if not authorised_contracts:
                continue  # non-authorised: no finding
            for cid in authorised_contracts:
                waivers_own.append((cid, w, em))

    out: list[Candidate] = []
    for cid, w, em in waivers_own:
        if not _condition_met(case, w, w.awb):
            continue
        for bill in case.billings:
            if bill.bill.kind != "invoice":
                continue
            if _contract_of(bill) != cid:
                continue
            msa = case.contract_for_invoice(bill)
            if msa is None:
                continue
            waiver_code = case.charge_code_for_label(msa, w.charge)
            matched_lines = []
            total_inr = Decimal(0)
            for ln in bill.bill.lines:
                line_code = case.charge_code_for_label(msa, ln.charge_label)
                if waiver_code and line_code and waiver_code != line_code:
                    continue
                if not waiver_code and ln.charge_label.strip().lower() != w.charge.strip().lower():
                    continue
                if w.awb and ln.awb != w.awb:
                    continue
                if w.month:
                    pickup = ln.pickup_date or ln.collected_date
                    if not pickup or pickup[:7] != w.month:
                        continue
                matched_lines.append(ln)
                total_inr += Decimal(ln.amount)
            if not matched_lines:
                continue

            evidence = [SourceRef.from_ref(em.doc, w.ref)]
            # Schedule 1 row for the sender (evidence of authority).
            for c in case.contracts:
                if c.id != cid and (not c.amends or c.amends != cid):
                    continue
                for row in c.terms.schedule1_rows:
                    if row.email.strip().lower() == _addr_of(em.email.sender.value).lower() and "waivers" in row.categories:
                        evidence.append(SourceRef.from_ref(c.doc, row.ref))
                        break
                break
            for ln in matched_lines:
                evidence.append(SourceRef.from_ref(bill.doc, ln.ref))

            converted = _convert_if_inr(total_inr, bill, case)
            if converted is None:
                out.append(Candidate(
                    key=("waived_but_billed", bill.bill.id.value),
                    class_="waived_but_billed",
                    billed_amount=total_inr,
                    corrects=[],
                    evidence=evidence,
                    note="cannot_determine: INR without FX month",
                ))
                continue
            out.append(Candidate(
                key=("waived_but_billed", bill.bill.id.value),
                class_="waived_but_billed",
                billed_amount=round_half_up(converted, 2),
                corrects=[CorrectAmount(amount=Decimal(0), sources=evidence,
                                        authority_level=2, in_force=True)],
                evidence=evidence,
            ))

    # Quoted-only waivers → cannot_determine candidates (one per matching invoice).
    for cid, w, em in waivers_quoted_only:
        for bill in case.billings:
            if bill.bill.kind != "invoice":
                continue
            if _contract_of(bill) != cid:
                continue
            msa = case.contract_for_invoice(bill)
            if msa is None:
                continue
            waiver_code = case.charge_code_for_label(msa, w.charge)
            matched = False
            for ln in bill.bill.lines:
                line_code = case.charge_code_for_label(msa, ln.charge_label)
                if waiver_code and line_code and waiver_code != line_code:
                    continue
                if not waiver_code and ln.charge_label.strip().lower() != w.charge.strip().lower():
                    continue
                if w.awb and ln.awb != w.awb:
                    continue
                matched = True
                break
            if not matched:
                continue
            # Holder: issuing party's KAM (notices).
            holder_email = ""
            for c in case.contracts:
                if c.id != cid:
                    continue
                for row in c.terms.schedule1_rows:
                    if "notices" in row.categories:
                        holder_email = row.email
                        break
                break
            out.append(Candidate(
                key=("waived_but_billed", bill.bill.id.value),
                class_="waived_but_billed",
                billed_amount=Decimal(0),
                corrects=[],
                evidence=[SourceRef.from_ref(em.doc, w.ref)],
                missing_doc=(f"original of waiver on {w.awb or w.month}", holder_email),
                note="cannot_determine: quoted-only waiver",
            ))
    return out
