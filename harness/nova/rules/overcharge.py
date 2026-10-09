"""Overcharge rule: reprice every billed line and compare.

For each invoice, for each line, find the correct amount from the terms in
force on the shipment's pickup date, then sum billed − correct over the
wrong lines. Zero or less is not a finding.

Pricing rules (glossary §Amounts, task 04 §3):
  - freight: lane × band containing the chargeable weight × period rate,
    with the minimum charge replacing freight when rate × weight is lower;
  - fuel: pickup-month fuel % × the correct freight on this line's shipment,
    priced after freight regardless of line order on the invoice;
  - accessorials: by basis_kind, with Annex E alias mapping, months-of-year
    windows, and the Judge for conditional accessorials.

INR invoices: billed − correct is accumulated in INR, then converted once per
finding using Annex F for the invoice-date month. A missing FX month makes
the finding `cannot_determine`.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from nova.case import Case, ContractRecord, SourceRef, Terms, TermSource
from nova.money import CannotDetermine, inr_to_usd, round_half_up
from nova.rules import Candidate, CorrectAmount
from nova.schemas import Accessorial, RateRow


# ---------------------------------------------------------------------------
# Rate lookup
# ---------------------------------------------------------------------------

def _band_contains(row: RateRow, weight: Decimal) -> bool:
    if row.is_minimum_charge:
        return False
    if row.band_min_kg is None:
        return False
    if weight < Decimal(str(row.band_min_kg)):
        return False
    if row.band_max_kg is not None and weight > Decimal(str(row.band_max_kg)):
        return False
    return True


def _rate_for_period(row: RateRow, period: Optional[str]) -> Optional[Decimal]:
    for r in row.rates:
        if r.period == period or r.period is None:
            return Decimal(r.rate)
    return None


def _correct_freight(
    case: Case,
    terms: Terms,
    lane: str,
    weight: Decimal,
    pickup_date: str,
) -> Optional[tuple[Decimal, list[SourceRef]]]:
    period = case.period_for(terms.msa, pickup_date)
    rows = terms.rate_rows_for(lane)
    band_row: Optional[tuple[RateRow, TermSource]] = None
    min_row: Optional[tuple[RateRow, TermSource]] = None
    for r, src in rows:
        if r.is_minimum_charge:
            min_row = (r, src)
        elif _band_contains(r, weight):
            band_row = (r, src)
    if band_row is None:
        return None
    rate = _rate_for_period(band_row[0], period)
    if rate is None:
        return None
    computed = round_half_up(rate * weight, 2)
    srcs = [SourceRef.from_ref(band_row[1].doc, band_row[0].ref)]
    if min_row is not None:
        min_rate = _rate_for_period(min_row[0], period)
        if min_rate is not None and computed < min_rate:
            computed = round_half_up(min_rate, 2)
            srcs.append(SourceRef.from_ref(min_row[1].doc, min_row[0].ref))
    return computed, srcs


# ---------------------------------------------------------------------------
# Accessorials
# ---------------------------------------------------------------------------

def _accessorial_applies(
    case: Case, acc: Accessorial, pickup_date: str, awb: Optional[str],
) -> bool:
    """Does this accessorial's condition fire on this shipment?

    A `months` window applies by calendar month of the pickup date. Any other
    `condition` is passed to the Judge; when no judge is wired the condition
    is treated as unmet (so the correct amount is zero, surfacing an
    overcharge).
    """
    if acc.months:
        if pickup_date[5:7] not in acc.months:
            return False
    if acc.condition:
        try:
            answer, _ref = case.judge(
                f"accessorial_condition:{acc.code}",
                {"awb": awb, "pickup_date": pickup_date, "condition": acc.condition},
            )
            return bool(answer)
        except (NotImplementedError, KeyError):
            return False
    return True


def _correct_accessorial(
    case: Case, terms: Terms, line, pickup_date: str,
) -> Optional[tuple[Decimal, list[SourceRef]]]:
    code = case.charge_code_for_label(terms.msa, line.charge_label)
    if code is None:
        return None
    found = terms.accessorial_by_code(code)
    if found is None:
        return None
    acc, src = found
    if not _accessorial_applies(case, acc, pickup_date, line.awb):
        return Decimal(0), [SourceRef.from_ref(src.doc, acc.ref)]
    rate = Decimal(acc.rate)
    if acc.basis_kind == "per_shipment":
        amt = round_half_up(rate, 2)
    elif acc.basis_kind == "per_kg" and line.qty:
        amt = round_half_up(rate * Decimal(line.qty), 2)
    elif acc.basis_kind == "per_piece" and line.qty:
        amt = round_half_up(rate * Decimal(line.qty), 2)
    else:
        return None
    return amt, [SourceRef.from_ref(src.doc, acc.ref)]


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

def run(case: Case, contract_id: Optional[str] = None) -> list[Candidate]:
    """Return one candidate per invoice that overcharges (billed > correct)."""
    out: list[Candidate] = []

    for bill in case.billings:
        bd = bill.bill
        if bd.kind != "invoice":
            continue
        inv_id = bd.id.value
        currency = bd.currency.value.upper() if bd.currency else "USD"
        invoice_date = bd.invoice_date.value if bd.invoice_date else None

        # Choose the contract by contract_ref, never by lane.
        msa = case.contract_for_invoice(bill)
        if msa is None:
            continue

        # Group lines by AWB; price freight first, then fuel on correct freight.
        by_awb: dict[Optional[str], list] = {}
        for ln in bd.lines:
            by_awb.setdefault(ln.awb, []).append(ln)

        billed_total = Decimal(0)
        correct_total = Decimal(0)
        evidence: list[SourceRef] = []
        wrong = False
        unresolved_fx_month: Optional[str] = None

        for awb, lines in by_awb.items():
            pickup = case.pickup_date(awb) if awb else None
            if pickup is None:
                for ln in lines:
                    billed_total += Decimal(ln.amount)
                    correct_total += Decimal(ln.amount)
                continue
            pickup_date, pickup_ref = pickup

            terms = case.terms_on(msa.id, pickup_date)
            if terms is None:
                for ln in lines:
                    billed_total += Decimal(ln.amount)
                    correct_total += Decimal(ln.amount)
                continue

            correct_by_line: dict[int, tuple[Decimal, list[SourceRef]]] = {}
            correct_freight: Optional[Decimal] = None
            freight_srcs: list[SourceRef] = []

            # Pass 1: freight (and anything not depending on freight).
            for i, ln in enumerate(lines):
                if ln.category == "freight" and ln.lane and ln.qty:
                    result = _correct_freight(case, terms, ln.lane, Decimal(ln.qty), pickup_date)
                    if result is not None:
                        correct_line, srcs = result
                        correct_by_line[i] = (correct_line, srcs)
                        correct_freight = correct_line
                        freight_srcs = srcs

            # Pass 2: fuel (needs correct_freight) and accessorials.
            for i, ln in enumerate(lines):
                if i in correct_by_line:
                    continue
                if ln.category == "fuel":
                    if correct_freight is None:
                        continue
                    fuel = terms.fuel_for_month(pickup_date[:7])
                    if fuel is None:
                        continue
                    fr, src = fuel
                    pct = Decimal(fr.rate)
                    amt = round_half_up(correct_freight * pct / Decimal(100), 2)
                    correct_by_line[i] = (
                        amt,
                        [SourceRef.from_ref(src.doc, fr.ref)] + freight_srcs,
                    )
                elif ln.category in {"security", "accessorial"}:
                    r = _correct_accessorial(case, terms, ln, pickup_date)
                    if r is not None:
                        correct_by_line[i] = r

            # Fold into totals.
            for i, ln in enumerate(lines):
                billed = Decimal(ln.amount)
                billed_total += billed
                if i in correct_by_line:
                    correct_amt, srcs = correct_by_line[i]
                    correct_total += correct_amt
                    if correct_amt != billed:
                        wrong = True
                        evidence.append(SourceRef.from_ref(bill.doc, ln.ref))
                        evidence.extend(srcs)
                        evidence.append(pickup_ref)
                else:
                    # Can't reprice: pass through billed (no delta on this line).
                    correct_total += billed

        if not wrong:
            continue
        delta = billed_total - correct_total
        if delta <= 0:
            continue

        # INR → USD conversion once per finding.
        final_billed = billed_total
        final_correct = correct_total
        if currency == "INR":
            if invoice_date is None:
                unresolved_fx_month = "unknown"
            else:
                fx = {fx_row.month: Decimal(fx_row.rate)
                      for fx_row, _src in (case.terms_on(msa.id, invoice_date).fx_rows
                                            if case.terms_on(msa.id, invoice_date) else [])}
                try:
                    final_billed = inr_to_usd(billed_total, invoice_date, fx)
                    final_correct = inr_to_usd(correct_total, invoice_date, fx)
                except CannotDetermine:
                    unresolved_fx_month = invoice_date[:7]

        # Dedupe evidence while preserving order.
        seen: set = set()
        dedup = []
        for e in evidence:
            k = (e.doc, e.page, e.line, e.line_end)
            if k in seen:
                continue
            seen.add(k)
            dedup.append(e)

        if unresolved_fx_month is not None:
            # cannot_determine: FX month missing; emit a candidate with no
            # resolvable correct amount. The holder is the Schedule 1 rates
            # contact of the invoice issuer, which resolve.py reads from
            # missing_doc. The current resolve step only handles findings; we
            # emit a note so the Phase 5 work can wire the verdict.
            out.append(Candidate(
                key=("overcharge", inv_id),
                class_="overcharge",
                billed_amount=final_billed,
                corrects=[],
                evidence=dedup,
                note=f"cannot_determine: no Annex F row for {unresolved_fx_month}",
            ))
            continue

        out.append(Candidate(
            key=("overcharge", inv_id),
            class_="overcharge",
            billed_amount=final_billed,
            corrects=[CorrectAmount(
                amount=final_correct,
                sources=dedup,
                authority_level=1,
                in_force=True,
            )],
            evidence=dedup,
        ))

    return out
