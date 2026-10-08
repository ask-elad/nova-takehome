"""Overcharge rule: reprice every billed line and compare.

For each invoice, for each line, find the correct amount from the terms in
force on the shipment's pickup date, then sum billed − correct over the
wrong lines. Zero or less is not a finding.

Pricing rules (glossary §Amounts, task 04 §3):
  - freight: lane × band containing the chargeable weight × period rate,
    with the minimum charge replacing freight when rate × weight is lower;
  - fuel: pickup-month fuel % × the correct freight on this line's shipment;
  - accessorials: by basis_kind.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from nova.case import Case, ContractRecord, SourceRef
from nova.money import round_half_up
from nova.rules import Candidate, CorrectAmount
from nova.schemas import RateRow


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
    msa: ContractRecord,
    lane: str,
    weight: Decimal,
    pickup_date: str,
) -> Optional[tuple[Decimal, list[SourceRef]]]:
    period = case.period_for(msa, pickup_date)
    rows = case.rate_rows_for(msa, lane)
    band_row: Optional[RateRow] = None
    min_row: Optional[RateRow] = None
    for r in rows:
        if r.is_minimum_charge:
            min_row = r
        elif _band_contains(r, weight):
            band_row = r
    if band_row is None:
        return None
    rate = _rate_for_period(band_row, period)
    if rate is None:
        return None
    computed = round_half_up(rate * weight, 2)
    srcs = [SourceRef.from_ref(msa.doc, band_row.ref)]
    if min_row is not None:
        min_rate = _rate_for_period(min_row, period)
        if min_rate is not None and computed < min_rate:
            computed = round_half_up(min_rate, 2)
            srcs.append(SourceRef.from_ref(msa.doc, min_row.ref))
    return computed, srcs


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

        # Group lines by AWB so we can price fuel on the correct freight.
        by_awb: dict[Optional[str], list] = {}
        for ln in bd.lines:
            by_awb.setdefault(ln.awb, []).append(ln)

        billed_total = Decimal(0)
        correct_total = Decimal(0)
        evidence: list[SourceRef] = []
        wrong = False
        all_in_force = True
        auth_min = 1

        for awb, lines in by_awb.items():
            # Pickup date for this AWB
            pickup = case.pickup_date(awb) if awb else None
            if pickup is None:
                # Cannot reprice without a pickup date; skip this AWB.
                continue
            pickup_date, pickup_ref = pickup

            # Choose the MSA that is in force on this pickup date and whose
            # Annex A has this lane. The resolve step will pick between
            # multiple sources; here we take the single MSA with the lane.
            msa: Optional[ContractRecord] = None
            lane_hint = next((ln.lane for ln in lines if ln.lane), None)
            for c in case.contracts_in_force(pickup_date):
                if lane_hint is None or any(r.lane == lane_hint for r in c.terms.rate_rows):
                    msa = c
                    break
            if msa is None:
                continue

            freight_line = next((ln for ln in lines if ln.category == "freight"), None)
            fuel_line = next((ln for ln in lines if ln.category == "fuel"), None)

            correct_freight: Optional[Decimal] = None
            for ln in lines:
                billed = Decimal(ln.amount)
                billed_total += billed
                correct_line: Optional[Decimal] = None
                line_evidence: list[SourceRef] = [SourceRef.from_ref(bill.doc, ln.ref)]

                if ln.category == "freight" and ln.lane and ln.qty:
                    weight = Decimal(ln.qty)
                    result = _correct_freight(case, msa, ln.lane, weight, pickup_date)
                    if result is not None:
                        correct_line, srcs = result
                        correct_freight = correct_line
                        line_evidence.extend(srcs)
                elif ln.category == "fuel":
                    # Needs the correct freight on the same AWB and the fuel %.
                    if correct_freight is None and freight_line is not None:
                        # Compute if we skipped above (defensive); shouldn't happen.
                        pass
                    fp = case.fuel_pct(msa, pickup_date[:7])
                    if fp is not None and correct_freight is not None:
                        pct, pct_ref = fp
                        correct_line = round_half_up(correct_freight * pct / Decimal(100), 2)
                        line_evidence.append(pct_ref)
                elif ln.category == "security":
                    acc = case.accessorial_by_label(msa, ln.charge_label)
                    if acc and acc.basis_kind == "per_kg" and ln.qty:
                        rate = Decimal(acc.rate)
                        correct_line = round_half_up(rate * Decimal(ln.qty), 2)
                        line_evidence.append(SourceRef.from_ref(msa.doc, acc.ref))
                elif ln.category == "accessorial":
                    acc = case.accessorial_by_label(msa, ln.charge_label)
                    if acc:
                        if acc.basis_kind == "per_shipment":
                            correct_line = round_half_up(Decimal(acc.rate), 2)
                            line_evidence.append(SourceRef.from_ref(msa.doc, acc.ref))
                        elif acc.basis_kind == "per_kg" and ln.qty:
                            correct_line = round_half_up(Decimal(acc.rate) * Decimal(ln.qty), 2)
                            line_evidence.append(SourceRef.from_ref(msa.doc, acc.ref))

                if correct_line is None:
                    # Cannot reprice this line; count it as billed (no delta).
                    correct_line = billed
                else:
                    if correct_line != billed:
                        wrong = True
                        evidence.extend(line_evidence)
                        evidence.append(pickup_ref)
                correct_total += correct_line

            # Add the pickup ref once if any line produced a delta on this AWB.
            # (Deduped during assembly below.)

        if not wrong:
            continue
        delta = billed_total - correct_total
        if delta <= 0:
            continue

        # Dedupe evidence while preserving order.
        seen: set = set()
        dedup = []
        for e in evidence:
            k = (e.doc, e.page, e.line, e.line_end)
            if k in seen:
                continue
            seen.add(k)
            dedup.append(e)

        out.append(Candidate(
            key=("overcharge", inv_id),
            class_="overcharge",
            billed_amount=billed_total,
            corrects=[CorrectAmount(
                amount=correct_total,
                sources=dedup,
                authority_level=1,
                in_force=True,
            )],
            evidence=dedup,
        ))

    return out
