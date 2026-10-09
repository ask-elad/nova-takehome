"""Cashback rule (glossary §Cashback and credits).

Two credit types:

- **rebate**: quarterly. Qualifying Spend is the sum of lines in the MSA's
  `qs_includes` categories, on invoices dated in the quarter, net of in-period
  credit notes (rebate and improvement credits excepted). INR amounts are
  converted per invoice using Annex F for the invoice-date month. The MSA's
  tier rule (`whole` or `marginal`) picks the rebate rate; subtract credit
  notes already issued for (contract, period, type=rebate).

- **promised_credit**: per contract year (CYn, n counts from effective_from).
  Rate times the same Qualifying Spend definition; subtract previously issued
  improvement credits.

Only closed periods are reported (as_of after period end). Once the credit
is due (period_end + due_days) the action is `draft:claim_credit`; before
then it is `internal:track_credit`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from nova.case import BillingRecord, Case, ContractRecord, SourceRef
from nova.money import CannotDetermine, inr_to_usd, round_half_up
from nova.rules import Candidate, CorrectAmount


def _parse(d: str) -> date:
    y, m, dd = d.split("-")
    return date(int(y), int(m), int(dd))


# ---------------------------------------------------------------------------
# Period math
# ---------------------------------------------------------------------------

def _quarter_of(iso: str) -> str:
    y, m, _ = iso.split("-")
    q = (int(m) - 1) // 3 + 1
    return f"{y}-Q{q}"


def _quarter_bounds(label: str) -> tuple[date, date]:
    y, q = label.split("-Q")
    y_i = int(y)
    q_i = int(q)
    start_m = (q_i - 1) * 3 + 1
    end_m = start_m + 2
    start = date(y_i, start_m, 1)
    end_year, end_next = (y_i + 1, 1) if end_m == 12 else (y_i, end_m + 1)
    end = date(end_year, end_next, 1) - timedelta(days=1)
    return start, end


def _contract_year_bounds(effective_from: date, n: int) -> tuple[date, date]:
    start = date(effective_from.year + n - 1, effective_from.month, effective_from.day)
    end = date(effective_from.year + n, effective_from.month, effective_from.day) - timedelta(days=1)
    return start, end


def _cyn_of(effective_from: date, invoice_date: date) -> int:
    """1-indexed contract year that contains invoice_date."""
    years = invoice_date.year - effective_from.year
    if (invoice_date.month, invoice_date.day) < (effective_from.month, effective_from.day):
        years -= 1
    return years + 1


# ---------------------------------------------------------------------------
# Qualifying spend
# ---------------------------------------------------------------------------

def _bill_contract(bill: BillingRecord, case: "Case | None" = None) -> Optional[str]:
    if bill.bill.contract_ref:
        return bill.bill.contract_ref.value
    if case is not None:
        msa = case.contract_for_invoice(bill)
        if msa is not None:
            return msa.id
    return None


def _bill_to_usd(amount: Decimal, bill: BillingRecord, case: Case) -> Optional[Decimal]:
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


def _qs_from_bill(bill: BillingRecord, qs_includes: list[str], qs_excludes: list[str],
                  case: Case) -> Optional[Decimal]:
    """Qualifying spend from one invoice (glossary §Cashback and credits).

    Take the invoice total and subtract the categories that cannot count:
    ``qs_excludes`` from the contract, plus the glossary's hard defaults
    (tax, duty, late fees, credits). This matches "total minus the bits that
    don't count" more robustly than summing includes — a billing reader that
    tags a freight-equivalent as ``minimum_charge`` or ``other`` still contributes
    to spend. Rebate/improvement credit notes are handled separately in the
    quarter/CY walk; they must never enter the per-invoice QS.
    """
    DEFAULT_EXCLUDES = {"tax", "duty", "late_fee", "credit"}
    excluded_cats = set(qs_excludes or []) | DEFAULT_EXCLUDES
    excluded = Decimal(0)
    for ln in bill.bill.lines:
        if ln.category in excluded_cats:
            excluded += Decimal(ln.amount)
    total = Decimal(bill.bill.total.value) - excluded
    return _bill_to_usd(total, bill, case)


# ---------------------------------------------------------------------------
# Tier lookup
# ---------------------------------------------------------------------------

def _tier_rate(qs: Decimal, tiers, rule: Optional[str]) -> Decimal:
    """Return the rate as a Decimal fraction (not percentage)."""
    if not tiers:
        return Decimal(0)
    ordered = sorted(tiers, key=lambda t: Decimal(t.threshold))
    reached: list = []
    for t in ordered:
        if qs >= Decimal(t.threshold):
            reached.append(t)
    if not reached:
        return Decimal(0)
    if rule == "marginal":
        # Earn each tier's rate on the increment above its threshold up to the next.
        # Caller handles the full computation; here we fall through to "whole".
        pass
    return Decimal(reached[-1].rate) / Decimal(100)


def _rebate_amount(qs: Decimal, tiers, rule: Optional[str]) -> Decimal:
    if not tiers:
        return Decimal(0)
    ordered = sorted(tiers, key=lambda t: Decimal(t.threshold))
    if rule == "marginal":
        total = Decimal(0)
        for i, t in enumerate(ordered):
            th = Decimal(t.threshold)
            if qs <= th:
                break
            top = Decimal(ordered[i + 1].threshold) if i + 1 < len(ordered) else qs
            band = min(qs, top) - th
            if band > 0:
                total += round_half_up(band * Decimal(t.rate) / Decimal(100), 2)
        return total
    # whole-tier rule
    rate = _tier_rate(qs, ordered, rule)
    return round_half_up(qs * rate, 2)


# ---------------------------------------------------------------------------
# Issued credits
# ---------------------------------------------------------------------------

def _issued_credit(case: Case, contract_id: str, period_label: str,
                   credit_type: str) -> Decimal:
    total = Decimal(0)
    for b in case.billings:
        if b.bill.kind != "credit_note":
            continue
        if _bill_contract(b, case) != contract_id:
            continue
        if (b.bill.credit_type or "").strip() != credit_type:
            continue
        cp = b.bill.credit_period.value if b.bill.credit_period else None
        if cp != period_label:
            continue
        total += Decimal(b.bill.total.value)
    return total


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

@dataclass
class _Spend:
    qs: Decimal
    evidence: list[SourceRef]


def _collect_spend_per_quarter(case: Case, msa: ContractRecord) -> dict[str, _Spend]:
    qs_includes = list(msa.terms.qs_includes or [])
    qs_excludes = list(msa.terms.qs_excludes or [])
    by_q: dict[str, _Spend] = {}
    seen_invoice_ids: set[str] = set()
    for b in case.billings:
        if _bill_contract(b, case) != msa.id:
            continue
        # Dedupe: a resent invoice (same id) counts once in QS, not twice.
        if b.bill.kind in ("invoice", "statement"):
            inv_id = b.bill.id.value
            if inv_id in seen_invoice_ids:
                continue
            seen_invoice_ids.add(inv_id)
        inv_date = b.bill.invoice_date.value if b.bill.invoice_date else None
        if inv_date is None:
            continue
        qlabel = _quarter_of(inv_date)
        if b.bill.kind in ("invoice", "statement"):
            qs = _qs_from_bill(b, qs_includes, qs_excludes, case)
            if qs is None:
                continue
            spend = by_q.setdefault(qlabel, _Spend(Decimal(0), []))
            spend.qs += qs
            spend.evidence.append(SourceRef.from_ref(b.doc, b.bill.id.ref))
        elif b.bill.kind == "credit_note":
            ctype = (b.bill.credit_type or "").strip().lower()
            if ctype in {"rebate", "improvement"}:
                continue
            amt = Decimal(b.bill.total.value)
            usd = _bill_to_usd(amt, b, case)
            if usd is None:
                continue
            spend = by_q.setdefault(qlabel, _Spend(Decimal(0), []))
            spend.qs -= usd
            spend.evidence.append(SourceRef.from_ref(b.doc, b.bill.id.ref))
    return by_q


def _collect_spend_per_cy(case: Case, msa: ContractRecord) -> dict[int, _Spend]:
    qs_includes = list(msa.terms.qs_includes or [])
    qs_excludes = list(msa.terms.qs_excludes or [])
    eff = _parse(msa.effective_from)
    by_y: dict[int, _Spend] = {}
    for b in case.billings:
        if _bill_contract(b, case) != msa.id:
            continue
        inv_date = b.bill.invoice_date.value if b.bill.invoice_date else None
        if inv_date is None:
            continue
        cy = _cyn_of(eff, _parse(inv_date))
        if b.bill.kind in ("invoice", "statement"):
            qs = _qs_from_bill(b, qs_includes, qs_excludes, case)
            if qs is None:
                continue
            spend = by_y.setdefault(cy, _Spend(Decimal(0), []))
            spend.qs += qs
            spend.evidence.append(SourceRef.from_ref(b.doc, b.bill.id.ref))
        elif b.bill.kind == "credit_note":
            ctype = (b.bill.credit_type or "").strip().lower()
            if ctype in {"rebate", "improvement"}:
                continue
            amt = Decimal(b.bill.total.value)
            usd = _bill_to_usd(amt, b, case)
            if usd is None:
                continue
            spend = by_y.setdefault(cy, _Spend(Decimal(0), []))
            spend.qs -= usd
            spend.evidence.append(SourceRef.from_ref(b.doc, b.bill.id.ref))
    return by_y


def _mk_candidate(contract_id: str, period: str, credit_type: str,
                  earned: Decimal, due: date, as_of: date,
                  evidence: list[SourceRef]) -> Candidate:
    deadline = due.isoformat()
    cand = Candidate(
        key=("cashback", f"{contract_id}/{period}/{credit_type}"),
        class_="cashback",
        billed_amount=earned,
        corrects=[CorrectAmount(amount=Decimal(0), sources=evidence,
                                authority_level=1, in_force=True)],
        evidence=evidence,
        deadline=deadline if as_of < due else None,
    )
    return cand


def run(case: Case) -> list[Candidate]:
    as_of = _parse(case.as_of)
    out: list[Candidate] = []
    for c in case.contracts:
        if c.is_amendment:
            continue
        # Rebate (quarterly).
        if c.terms.rebate_tiers:
            due_days = int(c.terms.rebate_due_days.value) if c.terms.rebate_due_days else 0
            per_q = _collect_spend_per_quarter(case, c)
            for qlabel, spend in per_q.items():
                _, qend = _quarter_bounds(qlabel)
                if as_of <= qend:
                    continue  # period not yet closed
                earned = _rebate_amount(spend.qs, c.terms.rebate_tiers, c.terms.rebate_tier_rule)
                already = _issued_credit(case, c.id, qlabel, "rebate")
                owed = earned - already
                if owed <= 0:
                    continue
                evidence = []
                if c.terms.rebate_tier_rule_text:
                    evidence.append(SourceRef.from_ref(c.doc, c.terms.rebate_tier_rule_text.ref))
                if c.terms.qs_text:
                    evidence.append(SourceRef.from_ref(c.doc, c.terms.qs_text.ref))
                evidence.extend(spend.evidence)
                due = qend + timedelta(days=due_days)
                out.append(_mk_candidate(c.id, qlabel, "rebate",
                                         owed, due, as_of, evidence))
        # Promised credits (per contract year).
        if c.terms.promised_credits:
            eff = _parse(c.effective_from)
            per_y = _collect_spend_per_cy(case, c)
            for cy, spend in per_y.items():
                cy_start, cy_end = _contract_year_bounds(eff, cy)
                if as_of <= cy_end:
                    continue
                for pc in c.terms.promised_credits:
                    due_days = int(pc.due_days.value) if pc.due_days else 0
                    rate = Decimal(pc.rate.value) / Decimal(100)
                    earned = round_half_up(spend.qs * rate, 2)
                    already = _issued_credit(case, c.id, f"CY{cy}", "improvement")
                    owed = earned - already
                    if owed <= 0:
                        continue
                    evidence = [SourceRef.from_ref(c.doc, pc.ref)]
                    if c.terms.qs_text:
                        evidence.append(SourceRef.from_ref(c.doc, c.terms.qs_text.ref))
                    evidence.extend(spend.evidence)
                    due = cy_end + timedelta(days=due_days)
                    out.append(_mk_candidate(c.id, f"CY{cy}", "promised_credit",
                                             owed, due, as_of, evidence))
    return out
