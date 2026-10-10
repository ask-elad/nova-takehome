"""Expiry rule (glossary §Expiry).

For each MSA, compute the operative date: the end date, or end_date minus
`renewal_notice_days` if the contract auto-renews. Emit if
0 ≤ deadline - as_of ≤ 60. The item has no amount; the action is an alert.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from nova.case import Case, ContractRecord, SourceRef
from nova.rules import Candidate, CorrectAmount


def _parse(d: str) -> date:
    y, m, dd = d.split("-")
    return date(int(y), int(m), int(dd))


def operative_date(msa: ContractRecord) -> Optional[str]:
    if not msa.end_date:
        return None
    end = _parse(msa.end_date)
    if msa.terms.auto_renewal and msa.terms.renewal_notice_days:
        end = end - timedelta(days=int(msa.terms.renewal_notice_days))
    return end.isoformat()


def _latest_end_source(case: Case, msa: ContractRecord) -> tuple[ContractRecord, bool]:
    """Return the contract to use for end_date and renewal terms.

    An amendment that restates the end date or renewal terms replaces the MSA
    values on those fields (audit B5). The latest-effective amendment with a
    stated end_date wins; otherwise fall back to the MSA. ``had_amendment``
    is True iff an amendment supplied the end_date.
    """
    best = msa
    best_eff = None
    had_amendment = False
    for c in case.contracts:
        if not c.is_amendment or c.amends != msa.id:
            continue
        if not c.end_date:
            continue
        eff = _parse(c.effective_from)
        if best_eff is None or eff > best_eff:
            best = c
            best_eff = eff
            had_amendment = True
    return best, had_amendment


def run(case: Case) -> list[Candidate]:
    out: list[Candidate] = []
    as_of = _parse(case.as_of)
    for c in case.contracts:
        if c.is_amendment:
            continue
        source, had_amendment = _latest_end_source(case, c)
        op = operative_date(source)
        if op is None:
            continue
        days = (_parse(op) - as_of).days
        if not (0 <= days <= 60):
            continue
        evidence = [SourceRef.from_ref(source.doc, source.terms.end_date.ref)]
        if source.terms.auto_renewal and source.terms.renewal_notice_ref:
            evidence.append(SourceRef.from_ref(source.doc, source.terms.renewal_notice_ref))
        if had_amendment:
            # Cite the MSA's end-date clause too so the evidence shows the
            # thing being replaced.
            if c.terms.end_date:
                evidence.append(SourceRef.from_ref(c.doc, c.terms.end_date.ref))
        out.append(Candidate(
            key=("expiry", c.id),
            class_="expiry",
            billed_amount=Decimal(0),
            corrects=[CorrectAmount(amount=Decimal(0), sources=evidence,
                                    authority_level=1, in_force=True)],
            evidence=evidence,
            deadline=op,
        ))
    return out
