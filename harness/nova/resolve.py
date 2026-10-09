"""Resolve rule candidates into report items.

Minimal scope for Phase 3 overcharge: pick the one authorised in-force
correct amount, apply precedence (highest wins), and emit a `finding` with
the quotes resolved from the source lines.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from nova.case import SourceRef
from nova.rules import Candidate, CorrectAmount
from nova.textlayer import Mailbox


@dataclass
class Evidence:
    doc: str
    page: int
    quote: str


@dataclass
class Item:
    id: str
    class_: str
    invoice_id: Optional[str]
    verdict: str                 # "finding" | "no_finding" | "conflict" | "cannot_determine"
    amount_usd: Optional[str]
    amount_range: Optional[list[str]]
    deadline: Optional[str]
    action: str
    evidence: list[Evidence]
    missing_doc: Optional[dict] = None


# ---------------------------------------------------------------------------
# Quote resolution
# ---------------------------------------------------------------------------

def resolve_quote(mailbox: Mailbox, ref: SourceRef) -> Optional[str]:
    """Return the literal line text (or span of lines) the ref points at.

    Returns None if the page is missing. The quote is the raw line as it
    appears in the extracted text layer, so grader/extract.found() will
    accept it. Must be at least 12 non-space characters per glossary.
    """
    try:
        pages, _ = mailbox.pages(ref.doc)
    except (LookupError, ValueError):
        return None
    if not (1 <= ref.page <= len(pages)):
        return None
    lines = pages[ref.page - 1].splitlines()
    start = ref.line - 1
    end = (ref.line_end or ref.line) - 1
    if not (0 <= start <= end < len(lines)):
        return None
    quote = "\n".join(lines[start : end + 1]).strip()
    if len(quote.replace(" ", "")) < 12:
        return None
    return quote


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------

def resolve(
    candidates: list[Candidate],
    mailbox: Mailbox,
) -> list[Item]:
    items: list[Item] = []
    for cand in candidates:
        corrects = [c for c in cand.corrects if c.in_force]
        if not corrects:
            continue

        # Conflict: two authorised in-force sources with different correct
        # amounts and the precedence clause doesn't rank them.
        distinct = {c.amount for c in corrects}
        if cand.unranked_pair and len(distinct) > 1:
            amounts = sorted(distinct)
            lower, higher = amounts[0], amounts[-1]
            lo = max(Decimal(0), cand.billed_amount - higher)
            hi = cand.billed_amount - lower
            quotes_c: list[Evidence] = []
            seen_c: set = set()
            for ref in cand.evidence:
                q = resolve_quote(mailbox, ref)
                if q is None:
                    continue
                k = (ref.doc, ref.page, q)
                if k in seen_c:
                    continue
                seen_c.add(k)
                quotes_c.append(Evidence(doc=ref.doc, page=ref.page, quote=q))
            items.append(Item(
                id=f"{cand.class_}:{cand.key[1]}",
                class_=cand.class_,
                invoice_id=cand.key[1],
                verdict="conflict",
                amount_usd=None,
                amount_range=[f"{lo.quantize(Decimal('0.01'))}",
                              f"{hi.quantize(Decimal('0.01'))}"],
                deadline=None,
                action="escalate",
                evidence=quotes_c,
            ))
            continue

        # Apply precedence: higher authority wins (lower level number = stronger).
        # When ties on authority, prefer higher rank.
        corrects.sort(key=lambda c: (c.authority_level, -(c.rank or 0)))
        best = corrects[0]

        # Expiry carries no money.
        if cand.class_ == "expiry":
            quotes: list[Evidence] = []
            seen: set = set()
            for ref in cand.evidence:
                q = resolve_quote(mailbox, ref)
                if q is None:
                    continue
                key = (ref.doc, ref.page, q)
                if key in seen:
                    continue
                seen.add(key)
                quotes.append(Evidence(doc=ref.doc, page=ref.page, quote=q))
            items.append(Item(
                id=f"{cand.class_}:{cand.key[1]}",
                class_=cand.class_,
                invoice_id=None,
                verdict="finding",
                amount_usd=None,
                amount_range=None,
                deadline=cand.deadline,
                action="internal:alert",
                evidence=quotes,
            ))
            continue

        delta = cand.billed_amount - best.amount
        if delta <= 0:
            continue

        if cand.class_ == "cashback":
            quotes2: list[Evidence] = []
            seen2: set = set()
            for ref in cand.evidence:
                q = resolve_quote(mailbox, ref)
                if q is None:
                    continue
                key = (ref.doc, ref.page, q)
                if key in seen2:
                    continue
                seen2.add(key)
                quotes2.append(Evidence(doc=ref.doc, page=ref.page, quote=q))
            action = "internal:track_credit" if cand.deadline else "draft:claim_credit"
            items.append(Item(
                id=f"{cand.class_}:{cand.key[1]}",
                class_=cand.class_,
                invoice_id=None,
                verdict="finding",
                amount_usd=f"{delta.quantize(Decimal('0.01'))}",
                amount_range=None,
                deadline=cand.deadline,
                action=action,
                evidence=quotes2,
            ))
            continue

        quotes: list[Evidence] = []
        seen: set = set()
        for ref in cand.evidence:
            q = resolve_quote(mailbox, ref)
            if q is None:
                continue
            key = (ref.doc, ref.page, q)
            if key in seen:
                continue
            seen.add(key)
            quotes.append(Evidence(doc=ref.doc, page=ref.page, quote=q))

        invoice_id = cand.key[1] if cand.class_ in {
            "overcharge", "duplicate", "waived_but_billed",
            "late_fee_not_owed", "late_fee_risk",
        } else None

        items.append(Item(
            id=f"{cand.class_}:{cand.key[1]}",
            class_=cand.class_,
            invoice_id=invoice_id,
            verdict="finding",
            amount_usd=f"{delta.quantize(Decimal('0.01'))}",
            amount_range=None,
            deadline=cand.deadline,
            action="draft:dispute",  # placeholder; Phase 5 sets this.
            evidence=quotes,
        ))
    return items
