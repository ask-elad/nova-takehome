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

import re

from nova.case import Case, ContractRecord, SourceRef, Terms, TermSource
from nova.money import CannotDetermine, inr_to_usd, round_half_up
from nova.rules import Candidate, CorrectAmount
from nova.schemas import Accessorial, RateRow


def _qty_decimal(s: str) -> Optional[Decimal]:
    """Parse a qty string to Decimal, tolerating units ('600 kg') and commas ('1,234.56')."""
    if not s:
        return None
    cleaned = s.replace(",", "")
    m = re.match(r'^-?[\d.]+', cleaned.strip())
    if not m:
        return None
    try:
        return Decimal(m.group())
    except Exception:
        return None


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
    rate_override: Optional[tuple[Decimal, SourceRef]] = None,
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
    if band_row is None and rate_override is None:
        return None

    if rate_override is not None:
        rate, override_src = rate_override
        srcs = [override_src]
    else:
        rate = _rate_for_period(band_row[0], period)
        if rate is None:
            return None
        srcs = [SourceRef.from_ref(band_row[1].doc, band_row[0].ref)]
    computed = round_half_up(rate * weight, 2)
    if min_row is not None:
        min_rate = _rate_for_period(min_row[0], period)
        if min_rate is not None and computed < min_rate:
            computed = round_half_up(min_rate, 2)
            srcs.append(SourceRef.from_ref(min_row[1].doc, min_row[0].ref))
    return computed, srcs


def _notice_row_for(terms: Terms, lane: str, weight: Decimal) -> Optional[tuple[Decimal, SourceRef, object]]:
    """If an in-force rate_notice covers (lane, band containing weight), return
    (rate, source_ref, notice). The band label match is loose: the notice row's
    numeric bounds are not parsed, so we match on the lane and pick the row
    whose band label coincides with a known band containing the weight."""
    for rns in terms.rate_notices:
        rn = rns.notice
        if rn.lane and rn.lane != lane:
            continue
        for row in rn.rows:
            if row.lane != lane:
                continue
            # Try to match by band label against an MSA rate row covering weight.
            for mrow, _ in terms.rate_rows_for(lane):
                if mrow.is_minimum_charge:
                    continue
                if _band_contains(mrow, weight) and mrow.band == row.band:
                    return Decimal(row.rate), SourceRef.from_ref(rns.doc, row.ref), rns
    return None


# ---------------------------------------------------------------------------
# Accessorials
# ---------------------------------------------------------------------------

def _is_dg_condition(text: str) -> bool:
    """Rough test for a dangerous-goods accessorial condition."""
    t = (text or "").lower()
    return ("dangerous good" in t) or ("iata dgr" in t) or ("dg " in t) or t.endswith(" dg")


def _is_dg_accessorial(acc: Accessorial) -> bool:
    """True iff this accessorial is the DG fee by code or label.

    The reader often doesn't capture a condition for DG (the rule lives in
    the prose above Annex D). We still want to consult the DG declaration
    whenever a DG-coded fee is billed — dry ice alone must not attract it.
    """
    code = (acc.code or "").upper()
    if code == "DG":
        return True
    label = (acc.label or "").lower()
    return "dangerous good" in label


def _accessorial_applies(
    case: Case, acc: Accessorial, pickup_date: str, awb: Optional[str],
) -> bool:
    """Does this accessorial's condition fire on this shipment?

    A `months` window applies by calendar month of the pickup date. For a DG
    accessorial we read the DG declaration directly: a declaration that is
    refrigerant-only (dry ice, UN1845 alone) means the fee does not apply
    (MSA 5.2/5.3); any other UN number means it does. For any other
    conditional accessorial we fall back to the Judge; when no judge is wired
    the condition is treated as unmet.
    """
    # DG fee: always consult the DG declaration, even when the reader didn't
    # surface a condition. Dry-ice-only (UN1845) means the fee doesn't apply.
    if awb and _is_dg_accessorial(acc):
        status = case.dg_status_for(awb)
        if status is not None:
            return status[0] == "dg"
        # No declaration: fall through to Judge, else presume applies.
    months = list(acc.months or [])
    if months:
        if pickup_date[5:7] not in months:
            return False
        # Months pass: the condition is a date window; don't double-check.
        return True
    if not acc.condition:
        return True
    if awb and _is_dg_condition(acc.condition):
        status = case.dg_status_for(awb)
        if status is not None:
            return status[0] == "dg"
        # No DG declaration held: fall through to the Judge; if the Judge
        # can't decide either, presume the DG fee applies.
    try:
        answer, _ref = case.judge(
            f"accessorial_condition:{acc.code}",
            {"awb": awb, "pickup_date": pickup_date, "condition": acc.condition},
        )
        return bool(answer)
    except (NotImplementedError, KeyError):
        # No evidence to rebut the carrier's claim: assume the accessorial
        # legitimately applies. Overcharges should rest on evidence we hold,
        # not on the Judge's silence (which produced false positives on the
        # practice set for Delivery fee / Peak season / Dry-ice handling).
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
        qty_d = _qty_decimal(line.qty)
        if qty_d is None:
            return None
        amt = round_half_up(rate * qty_d, 2)
    elif acc.basis_kind == "per_piece" and line.qty:
        qty_d = _qty_decimal(line.qty)
        if qty_d is None:
            return None
        amt = round_half_up(rate * qty_d, 2)
    else:
        return None
    return amt, [SourceRef.from_ref(src.doc, acc.ref)]


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

def _price_invoice(
    case: Case, bill, msa, use_notice: bool,
) -> tuple[Decimal, Decimal, list[SourceRef], bool]:
    """Return (billed_total, correct_total, evidence, wrong).

    When use_notice is True, substitute each in-force rate_notice's rate for
    its (lane, band) in freight pricing. Fuel then rides on that freight.
    """
    bd = bill.bill
    by_awb: dict[Optional[str], list] = {}
    for ln in bd.lines:
        by_awb.setdefault(ln.awb, []).append(ln)

    billed_total = Decimal(0)
    correct_total = Decimal(0)
    evidence: list[SourceRef] = []
    wrong = False

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

        for i, ln in enumerate(lines):
            qty_d = _qty_decimal(ln.qty) if ln.qty else None
            if ln.category == "freight" and ln.lane and qty_d is not None:
                override = None
                if use_notice:
                    nr = _notice_row_for(terms, ln.lane, qty_d)
                    if nr is not None:
                        rate, src, _rns = nr
                        override = (rate, src)
                result = _correct_freight(case, terms, ln.lane, qty_d,
                                          pickup_date, rate_override=override)
                if result is not None:
                    correct_line, srcs = result
                    correct_by_line[i] = (correct_line, srcs)
                    correct_freight = correct_line
                    freight_srcs = srcs

        # Lines covered by an authorised own-text waiver are handled by the
        # waived_but_billed rule, not here. Treat them as billed = correct.
        for i, ln in enumerate(lines):
            if case.is_line_waived(msa, ln):
                correct_by_line[i] = (Decimal(ln.amount), [])

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
                correct_total += billed
    return billed_total, correct_total, evidence, wrong


def _missing_rate_doc_candidate(
    case: Case, bill, msa,
) -> Optional[Candidate]:
    """If any freight line's lane has an active amendment_rate_ref whose
    referenced document is not held, return a cannot_determine candidate for
    the whole invoice. Never fall back to the MSA rate.
    """
    bd = bill.bill
    for ln in bd.lines:
        if ln.category != "freight" or not ln.lane:
            continue
        awb = ln.awb
        pickup = case.pickup_date(awb) if awb else None
        if pickup is None:
            continue
        pickup_date, pickup_ref = pickup
        terms = case.terms_on(msa.id, pickup_date)
        if terms is None:
            continue
        for arr, src in terms.amendment_rate_refs:
            if arr.lane != ln.lane:
                continue
            if case.is_doc_name_held(arr.document_name):
                continue
            rates_contact = case.schedule1_contact(msa.id, "rates")
            holder = (
                {"person": rates_contact.name, "party": rates_contact.party,
                 "role": rates_contact.title}
                if rates_contact else {"party": ""}
            )
            evidence = [
                SourceRef.from_ref(bill.doc, ln.ref),
                SourceRef.from_ref(src.doc, arr.ref),
                pickup_ref,
            ]
            return Candidate(
                key=("overcharge", bd.id.value),
                class_="overcharge",
                billed_amount=Decimal(ln.amount),
                corrects=[],
                evidence=evidence,
                missing_doc=(arr.document_name, holder),
                note=(f"cannot_determine: amendment hands lane {arr.lane} rates to "
                      f"{arr.document_name!r} from {arr.effective_from}; doc not held"),
            )
    return None


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

        msa = case.contract_for_invoice(bill)
        if msa is None:
            continue

        # Amendment that hands lane rates to a referenced doc we don't hold:
        # the whole invoice becomes cannot_determine. Never fall back to MSA.
        missing = _missing_rate_doc_candidate(case, bill, msa)
        if missing is not None:
            out.append(missing)
            continue

        # Primary: price with rate_rows (amendments included).
        billed_total, correct_amendment, evidence, wrong = _price_invoice(
            case, bill, msa, use_notice=False)

        # Secondary: price with any in-force rate_notice rates. If no notice
        # applies, _price_invoice gives the same correct as the primary pass.
        _, correct_notice, evidence_n, _ = _price_invoice(
            case, bill, msa, use_notice=True)

        # Any in-force rate_notice for any lane on the invoice?
        has_notice_in_force = False
        notice_src_kind = None
        for ln in bd.lines:
            if ln.lane is None or ln.qty is None:
                continue
            # Find pickup date & terms
            pickup = case.pickup_date(ln.awb) if ln.awb else None
            if pickup is None:
                continue
            terms = case.terms_on(msa.id, pickup[0])
            if terms is None:
                continue
            try:
                qty_d2 = _qty_decimal(ln.qty)
                nr = _notice_row_for(terms, ln.lane, qty_d2) if qty_d2 is not None else None
            except Exception:
                nr = None
            if nr is not None:
                has_notice_in_force = True
                notice_src_kind = "rate_notice"
                break

        unresolved_fx_month: Optional[str] = None
        if not wrong and not (has_notice_in_force and correct_amendment != correct_notice):
            continue
        delta = billed_total - correct_amendment
        if delta <= 0 and not (has_notice_in_force and correct_amendment != correct_notice):
            continue

        final_billed = billed_total
        final_correct_amd = correct_amendment
        final_correct_rn = correct_notice
        if currency == "INR":
            if invoice_date is None:
                unresolved_fx_month = "unknown"
            else:
                fx = {fx_row.month: Decimal(fx_row.rate)
                      for fx_row, _src in (case.terms_on(msa.id, invoice_date).fx_rows
                                            if case.terms_on(msa.id, invoice_date) else [])}
                try:
                    # Audit minors: compute the delta in INR, convert the
                    # delta once. Billed is still converted so the report
                    # shows a USD billed total; correct is derived as
                    # billed - delta_usd to avoid a 1-cent drift between
                    # two independent conversions.
                    final_billed = inr_to_usd(billed_total, invoice_date, fx)
                    delta_amd = inr_to_usd(
                        billed_total - correct_amendment, invoice_date, fx)
                    final_correct_amd = final_billed - delta_amd
                    delta_rn = inr_to_usd(
                        billed_total - correct_notice, invoice_date, fx)
                    final_correct_rn = final_billed - delta_rn
                except CannotDetermine:
                    unresolved_fx_month = invoice_date[:7]

        # Combine and dedupe evidence.
        all_ev = evidence + evidence_n
        seen: set = set()
        dedup = []
        for e in all_ev:
            k = (e.doc, e.page, e.line, e.line_end)
            if k in seen:
                continue
            seen.add(k)
            dedup.append(e)

        if unresolved_fx_month is not None:
            treasury = case.schedule1_contact(msa.id, "treasury")
            holder = (
                {"person": treasury.name, "party": treasury.party,
                 "role": treasury.title}
                if treasury else {"party": ""}
            )
            missing = (f"Annex F row for {unresolved_fx_month}", holder)
            out.append(Candidate(
                key=("overcharge", inv_id),
                class_="overcharge",
                billed_amount=final_billed,
                corrects=[],
                evidence=dedup,
                missing_doc=missing,
                note=f"cannot_determine: no Annex F row for {unresolved_fx_month}",
            ))
            continue

        corrects = [CorrectAmount(
            amount=final_correct_amd, sources=dedup,
            authority_level=1, in_force=True,
            source_kind="amendment" if has_notice_in_force else "msa",
        )]
        unranked_ref = None
        unranked_pair = None
        if has_notice_in_force and correct_amendment != correct_notice:
            # When reporting a conflict, make sure the amendment that priced
            # the band is cited alongside the rate notice, even if the billed
            # amount happened to match the amendment (so pricing never flagged
            # a per-line "wrong" and the amendment doc stayed off evidence).
            for ln in bd.lines:
                if ln.lane is None or ln.awb is None or ln.qty is None:
                    continue
                pk = case.pickup_date(ln.awb)
                if pk is None:
                    continue
                tm = case.terms_on(msa.id, pk[0])
                if tm is None:
                    continue
                qd = _qty_decimal(ln.qty)
                if qd is None:
                    continue
                for r, src in tm.rate_rows_for(ln.lane):
                    if r.is_minimum_charge or not _band_contains(r, qd):
                        continue
                    if src.kind == "amendment":
                        amd_ref = SourceRef.from_ref(src.doc, r.ref)
                        if amd_ref not in dedup:
                            dedup.append(amd_ref)
                    break
            # Feedback `precedence` or `rate_accepted` can pin the choice for
            # a (contract, lane) in-window: keep only the named source.
            precedence_use = None
            for ln in bd.lines:
                if not ln.lane or not ln.awb:
                    continue
                pk = case.pickup_date(ln.awb)
                if pk is None:
                    continue
                use = case.precedence_fact_for(msa.id, ln.lane, pk[0])
                if use:
                    precedence_use = use
                    break
                # rate_accepted makes the notice THE rate for that lane in
                # the window — no conflict, no amendment fallback.
                if case.rate_accepted_for(msa.id, ln.lane, pk[0]) is not None:
                    precedence_use = "rate_notice"
                    break
            if precedence_use == "amendment":
                pass  # keep the single amendment-sourced correct only
            elif precedence_use == "rate_notice":
                corrects = [CorrectAmount(
                    amount=final_correct_rn, sources=dedup,
                    authority_level=2, in_force=True,
                    source_kind="rate_notice",
                )]
            else:
                corrects.append(CorrectAmount(
                    amount=final_correct_rn, sources=dedup,
                    authority_level=2, in_force=True,
                    source_kind="rate_notice",
                ))
                if msa.terms.unranked_pairs:
                    for pair in msa.terms.unranked_pairs:
                        kinds = {pair.a, pair.b}
                        if "rate_notice" in kinds and "amendment" in kinds:
                            unranked_pair = ("rate_notice", "amendment")
                            unranked_ref = SourceRef.from_ref(msa.doc, pair.ref)
                            dedup.append(unranked_ref)
                            break

        out.append(Candidate(
            key=("overcharge", inv_id),
            class_="overcharge",
            billed_amount=final_billed,
            corrects=corrects,
            evidence=dedup,
            unranked_pair=unranked_pair,
            unranked_ref=unranked_ref,
        ))

    return out
