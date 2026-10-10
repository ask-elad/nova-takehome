"""Policy layer: actions, modes, $5,000 rule, and the five unattended-action checks.

Translates resolved Items into report-ready items with correct actions and
confidence scores. Applies:
  - Per-verdict/class action table (GLOSSARY.md §Actions)
  - Supervised mode: outbound actions become draft:*; never execute:*
  - Autonomous mode: execute:* only when all five checks pass; else human_review
  - $5,000 rule: any invoice/cashback key whose outbound sum >= $5,000 → human_review
  - Conflict always → escalate (both modes)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from nova.resolve import Item


# ---------------------------------------------------------------------------
# Outbound action bases (without draft:/execute: prefix)
# ---------------------------------------------------------------------------
_OUTBOUND_BASE: dict[str, str] = {
    "overcharge":         "dispute",
    "duplicate":          "dispute",
    "waived_but_billed":  "dispute",
    "late_fee_not_owed":  "dispute",
    "cashback":           "claim_credit",
    "cannot_determine":   "request_document",
}

# Classes that produce internal-only actions (never outbound)
_INTERNAL_ONLY = {"expiry", "late_fee_risk"}

THRESHOLD = Decimal("5000.00")


# ---------------------------------------------------------------------------
# Per-item flags that control autonomous checks
# ---------------------------------------------------------------------------

@dataclass
class ItemFlags:
    """Policy-relevant metadata attached to a resolved item."""
    # Check 1: evidence complete
    missing_doc_present: bool = False
    pickup_from_tracking: bool = True   # True = tracking or carrier email
    # Check 2: no open conflict on same contract/lane
    has_same_key_conflict: bool = False
    # Check 3: under $5k — computed by apply_policy from all items
    # Check 4: can_be_undone — always true for dispute/claim_credit/request_document
    # Check 5: authority levels
    all_terms_level12: bool = True      # all deciding terms at level 1 or 2
    all_facts_level3plus: bool = True   # all facts at level 3 or better
    recipient_from_schedule1: bool = True


# Default flags (all checks pass unless overridden)
DEFAULT_FLAGS = ItemFlags()


# ---------------------------------------------------------------------------
# Internal action for a class (never executed autonomously)
# ---------------------------------------------------------------------------

def _internal_action(class_: str, deadline: Optional[str]) -> str:
    if class_ == "expiry":
        return "internal:alert"
    if class_ == "late_fee_risk":
        return "internal:payment_reminder"
    if class_ == "cashback":
        return "internal:track_credit" if deadline else "draft:claim_credit"
    return "none"


# ---------------------------------------------------------------------------
# Five unattended-action checks
# ---------------------------------------------------------------------------

def _all_checks_pass(item: Item, flags: ItemFlags) -> bool:
    """Return True iff all five unattended-action checks pass for this item."""
    # Check 1: evidence complete. For a cannot_determine item, the outbound
    # action is request_document — the whole point is that a doc is missing,
    # so missing_doc_present must not block that specific flow.
    if item.verdict != "cannot_determine" and flags.missing_doc_present:
        return False
    if not flags.pickup_from_tracking:
        return False
    # Check 2: no open conflict on same key/contract/lane
    if flags.has_same_key_conflict:
        return False
    # Check 3: under threshold — handled by the $5k rule before this call
    # (item.action is already human_review if over threshold, so we won't reach here)
    # Check 4: can be undone (dispute, claim_credit, request_document all can)
    base = _OUTBOUND_BASE.get(item.class_, "")
    if base not in {"dispute", "claim_credit", "request_document"}:
        return False
    # Check 5: enough authority
    if not flags.all_terms_level12:
        return False
    if not flags.all_facts_level3plus:
        return False
    if not flags.recipient_from_schedule1:
        return False
    return True


# ---------------------------------------------------------------------------
# Main policy function
# ---------------------------------------------------------------------------

def apply_policy(
    items: list[Item],
    mode: str,
    flags_map: dict[str, ItemFlags] | None = None,
) -> list[Item]:
    """Apply policy to a list of resolved items.

    mode: "supervised" | "autonomous"
    flags_map: item.id → ItemFlags (defaults to DEFAULT_FLAGS for missing keys)

    Returns new Item objects with action set correctly. Does NOT mutate the
    originals.
    """
    if flags_map is None:
        flags_map = {}

    # $5k rule: group outbound items by invoice_id or cashback key and sum amounts.
    # "Outbound" means the item would produce a draft:/execute: action.
    outbound_sum: dict[str, Decimal] = {}
    for item in items:
        if item.verdict not in ("finding",):
            continue
        if item.class_ in _INTERNAL_ONLY:
            continue
        key = _group_key(item)
        if key is None:
            continue
        try:
            amt = Decimal(item.amount_usd) if item.amount_usd else Decimal(0)
        except Exception:
            amt = Decimal(0)
        outbound_sum[key] = outbound_sum.get(key, Decimal(0)) + amt

    result: list[Item] = []
    for item in items:
        action = _compute_action(item, mode, flags_map.get(item.id, DEFAULT_FLAGS), outbound_sum)
        # Build a new Item with the updated action (Item is a dataclass, copy it)
        from dataclasses import replace as _replace
        result.append(_replace(item, action=action))
    return result


def _group_key(item: Item) -> Optional[str]:
    """The $5k grouping key for an item (invoice_id or cashback key)."""
    if item.invoice_id:
        return item.invoice_id
    # cashback id = "cashback:contract/period/type"
    if item.class_ == "cashback" and ":" in item.id:
        return item.id.split(":", 1)[1]
    return None


def _compute_action(
    item: Item,
    mode: str,
    flags: ItemFlags,
    outbound_sum: dict[str, Decimal],
) -> str:
    verdict = item.verdict

    if verdict == "no_finding":
        return "none"

    if verdict == "conflict":
        return "escalate"

    if verdict == "cannot_determine":
        # Outbound request; both modes draft first, autonomous can execute
        if mode == "supervised":
            return "draft:request_document"
        flags_ok = _all_checks_pass(item, flags)
        key = _group_key(item)
        over_threshold = key is not None and outbound_sum.get(key, Decimal(0)) >= THRESHOLD
        if flags_ok and not over_threshold:
            return "execute:request_document"
        return "human_review"

    # verdict == "finding"
    class_ = item.class_

    # Internal-only classes
    if class_ in _INTERNAL_ONLY:
        return _internal_action(class_, item.deadline)

    if class_ == "cashback":
        internal = _internal_action(class_, item.deadline)
        # Autonomous: once due, draft:claim_credit can execute when all five
        # unattended-action checks pass. internal:track_credit (before due)
        # and human_review (over $5k) stay.
        if internal != "draft:claim_credit" or mode == "supervised":
            return internal
        key = _group_key(item)
        over_threshold = key is not None and outbound_sum.get(key, Decimal(0)) >= THRESHOLD
        if over_threshold:
            return "human_review"
        if _all_checks_pass(item, flags):
            return "execute:claim_credit"
        return "human_review"

    # Outbound classes
    base = _OUTBOUND_BASE.get(class_, "dispute")

    # $5k rule
    key = _group_key(item)
    over_threshold = key is not None and outbound_sum.get(key, Decimal(0)) >= THRESHOLD

    if over_threshold:
        return "human_review"

    if mode == "supervised":
        return f"draft:{base}"

    # Autonomous mode: execute only if all 5 checks pass
    if _all_checks_pass(item, flags):
        return f"execute:{base}"
    return "human_review"
