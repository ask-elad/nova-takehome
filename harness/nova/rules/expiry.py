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


def run(case: Case) -> list[Candidate]:
    out: list[Candidate] = []
    as_of = _parse(case.as_of)
    for c in case.contracts:
        if c.is_amendment:
            continue
        op = operative_date(c)
        if op is None:
            continue
        days = (_parse(op) - as_of).days
        if not (0 <= days <= 60):
            continue
        # Evidence: the end-date clause, and the auto-renewal/notice clause when relevant.
        evidence = [SourceRef.from_ref(c.doc, c.terms.end_date.ref)]
        if c.terms.auto_renewal and c.terms.renewal_notice_ref:
            evidence.append(SourceRef.from_ref(c.doc, c.terms.renewal_notice_ref))
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
