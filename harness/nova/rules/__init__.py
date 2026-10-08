"""Rules engine: one module per class. Each returns a list of candidates."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Optional

from nova.case import SourceRef

Verdict = Literal["finding", "no_finding", "cannot_determine"]


@dataclass
class CorrectAmount:
    """One correct-amount view from one source.

    authority_level: 1 = signed MSA/amendment, 2 = authorised email/feedback,
    3 = records (tracking, AWB, invoices), 4 = other, 5 = quoted/unauthorised.
    """
    amount: Decimal              # the correct TOTAL for the finding (billed minus this = overcharge)
    sources: list[SourceRef]
    authority_level: int
    in_force: bool
    rank: Optional[int] = None   # higher = beats lower in the precedence clause


@dataclass
class Candidate:
    """One candidate finding produced by a rule module."""
    key: tuple                   # e.g. ("overcharge", "TX-US-2032-5394")
    class_: str                  # "overcharge", "duplicate", ...
    billed_amount: Decimal
    corrects: list[CorrectAmount]
    evidence: list[SourceRef]
    missing_doc: Optional[tuple[str, str]] = None  # (name, holder email) if cannot_determine
    deadline: Optional[str] = None
    note: str = ""
