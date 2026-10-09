"""Confidence scoring for report items.

Starts at 0.95 and applies deductions for weaker signals:
  - pickup_date not from tracking export or carrier pickup email: -0.05
  - a value that needed a re-read (tier escalation): -0.05
  - a term below authority level 1 (signed): -0.10
  - a Judge answer in the decision chain: -0.05
  - an INR conversion in the amount: -0.05

Fixed lower values:
  - conflict:           0.60
  - cannot_determine:   0.50
  - no_finding:         0.90

Floor for findings: 0.50

All weights live in the WEIGHTS table so Phase 7 can tune them.
"""
from __future__ import annotations

WEIGHTS = {
    "base":                  0.95,
    "pickup_not_tracking":  -0.05,
    "reread":               -0.05,
    "term_below_level1":    -0.10,
    "judge_in_chain":       -0.05,
    "inr_conversion":       -0.05,
    "floor_finding":         0.50,
    "conflict_fixed":        0.60,
    "cannot_determine_fixed": 0.50,
    "no_finding_fixed":      0.90,
}


def score(
    verdict: str,
    *,
    pickup_from_tracking: bool = True,
    had_reread: bool = False,
    min_term_authority: int = 1,
    judge_used: bool = False,
    inr_converted: bool = False,
) -> float:
    """Return confidence for one item given its evidence quality."""
    if verdict == "conflict":
        return WEIGHTS["conflict_fixed"]
    if verdict == "cannot_determine":
        return WEIGHTS["cannot_determine_fixed"]
    if verdict == "no_finding":
        return WEIGHTS["no_finding_fixed"]

    # finding
    c = WEIGHTS["base"]
    if not pickup_from_tracking:
        c += WEIGHTS["pickup_not_tracking"]
    if had_reread:
        c += WEIGHTS["reread"]
    if min_term_authority > 1:
        c += WEIGHTS["term_below_level1"]
    if judge_used:
        c += WEIGHTS["judge_in_chain"]
    if inr_converted:
        c += WEIGHTS["inr_conversion"]
    return max(c, WEIGHTS["floor_finding"])
