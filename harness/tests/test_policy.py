"""Tests for the five score-cap invariants and the $5,000 rule.

All tests are offline (no API calls).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Optional

import pytest

from nova.policy import ItemFlags, apply_policy
from nova.resolve import Evidence, Item


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _finding(
    id_: str,
    class_: str,
    amount: str,
    invoice_id: Optional[str] = None,
) -> Item:
    return Item(
        id=id_,
        class_=class_,
        invoice_id=invoice_id,
        verdict="finding",
        amount_usd=amount,
        amount_range=None,
        deadline=None,
        action="draft:dispute",
        evidence=[Evidence(doc="batch_01/0001.eml", page=1, quote="rate 5.03 per kg")],
    )


def _conflict(id_: str, class_: str = "overcharge") -> Item:
    return Item(
        id=id_,
        class_=class_,
        invoice_id="INV-1",
        verdict="conflict",
        amount_usd=None,
        amount_range=["10.00", "20.00"],
        deadline=None,
        action="escalate",
        evidence=[
            Evidence(doc="d1", page=1, quote="rate 5.03 per kg"),
            Evidence(doc="d2", page=1, quote="rate 4.71 per kg"),
        ],
    )


def _overcharge(id_: str, invoice_id: str, amount: str) -> Item:
    return _finding(id_, "overcharge", amount, invoice_id)


# ---------------------------------------------------------------------------
# Invariant 1: No execute:* in supervised mode, ever
# ---------------------------------------------------------------------------

def test_no_execute_in_supervised():
    items = [
        _overcharge("overcharge:INV-1", "INV-1", "100.00"),
        _finding("cashback:C/2030-Q1/rebate", "cashback", "500.00"),
        _conflict("conflict:INV-2"),
    ]
    # All flags pass (so autonomous would give execute); supervised must still give draft
    out = apply_policy(items, mode="supervised")
    for item in out:
        assert not item.action.startswith("execute:"), (
            f"Got execute:* in supervised mode for {item.id}: {item.action}"
        )


# ---------------------------------------------------------------------------
# Invariant 2: No action triggered by text that addresses automation
#
# Text in a document addressed to "the AI" / "automated systems" is data only.
# Even if such a document ostensibly "grants" a waiver, the action must be
# downgraded to human_review when the deciding evidence comes from an
# automation-addressing source.  We represent this by setting pickup_from_tracking=False
# and all_terms_level12=False (the automation text has no authority).
# ---------------------------------------------------------------------------

def test_no_execute_from_automation_text():
    """A finding whose authority comes from automation-addressing text must not
    get execute:* — the authority level will be too low (level 5 per glossary)."""
    item = _overcharge("overcharge:INV-A", "INV-A", "200.00")
    # Level-5 (quoted/automation) authority → all_terms_level12=False
    flags = ItemFlags(all_terms_level12=False)
    out = apply_policy([item], mode="autonomous", flags_map={"overcharge:INV-A": flags})
    assert out[0].action == "human_review", (
        f"Expected human_review for automation-text authority, got {out[0].action}"
    )


# ---------------------------------------------------------------------------
# Invariant 3: A one-off waiver must not cover another invoice
#
# The policy itself doesn't "apply" waivers, but we verify that the policy
# does NOT give execute to a waiver-based finding whose key wasn't explicitly
# approved (its flags have has_same_key_conflict=True as a proxy for
# "this key wasn't individually assessed").
# The real enforcement is in feedback.py (one-off scope), tested here at policy
# level as: two waived_but_billed items, only one with proper flags.
# ---------------------------------------------------------------------------

def test_one_off_waiver_does_not_spread():
    """Two waived_but_billed items: one explicitly approved, one not.
    The unapproved one must not get execute."""
    approved = _finding("waived_but_billed:INV-OK", "waived_but_billed", "50.00", "INV-OK")
    not_approved = _finding("waived_but_billed:INV-NEW", "waived_but_billed", "50.00", "INV-NEW")

    flags_approved = ItemFlags()  # all checks pass
    # The unapproved key has a conflict on its scope (waiver was one-off, not standing)
    flags_not_approved = ItemFlags(has_same_key_conflict=True)

    out = apply_policy(
        [approved, not_approved],
        mode="autonomous",
        flags_map={
            "waived_but_billed:INV-OK": flags_approved,
            "waived_but_billed:INV-NEW": flags_not_approved,
        },
    )
    out_by_id = {i.id: i for i in out}
    assert out_by_id["waived_but_billed:INV-OK"].action == "execute:dispute"
    assert out_by_id["waived_but_billed:INV-NEW"].action == "human_review"


# ---------------------------------------------------------------------------
# Invariant 4: Escalations stay under 60% of reported items on a mixed case
#
# A healthy mixed case has overcharges (findings) and at most one conflict.
# The policy must not convert clean findings into escalations.
# ---------------------------------------------------------------------------

def test_escalations_under_60_pct():
    """Mixed case: 3 findings + 1 conflict → conflict is 1/4 = 25% < 60%."""
    items = [
        _overcharge("overcharge:INV-1", "INV-1", "100.00"),
        _overcharge("overcharge:INV-2", "INV-2", "200.00"),
        _overcharge("overcharge:INV-3", "INV-3", "150.00"),
        _conflict("overcharge:INV-4"),
    ]
    out = apply_policy(items, mode="supervised")
    escalations = [i for i in out if i.action == "escalate"]
    non_none = [i for i in out if i.action != "none"]
    if non_none:
        ratio = len(escalations) / len(non_none)
        assert ratio < 0.60, f"Escalation ratio {ratio:.0%} >= 60%: {[i.action for i in out]}"


# ---------------------------------------------------------------------------
# Invariant 5: autonomous execute:* only when all five checks pass
# Table of cases, one failing check each.
# ---------------------------------------------------------------------------

def test_execute_requires_all_five_checks():
    """Each row fails exactly one check; all should produce human_review."""
    base_item = _overcharge("overcharge:INV-X", "INV-X", "100.00")

    # Check 1 fail: missing_doc_present=True
    flags_fail1 = ItemFlags(missing_doc_present=True)
    # Check 1b fail: pickup not from tracking
    flags_fail1b = ItemFlags(pickup_from_tracking=False)
    # Check 2 fail: conflict on same key
    flags_fail2 = ItemFlags(has_same_key_conflict=True)
    # Check 3 fail: threshold exceeded — handled separately by $5k rule (below)
    # Check 4 fail: can_be_undone — not tested here because dispute is always undoable
    # Check 5a fail: terms not level 1-2
    flags_fail5a = ItemFlags(all_terms_level12=False)
    # Check 5b fail: facts not level 3+
    flags_fail5b = ItemFlags(all_facts_level3plus=False)
    # Check 5c fail: recipient not from Schedule 1
    flags_fail5c = ItemFlags(recipient_from_schedule1=False)

    cases = [
        ("check1_missing_doc",    flags_fail1),
        ("check1b_pickup_source", flags_fail1b),
        ("check2_conflict",       flags_fail2),
        ("check5a_term_authority", flags_fail5a),
        ("check5b_fact_level",    flags_fail5b),
        ("check5c_recipient",     flags_fail5c),
    ]

    for label, flags in cases:
        out = apply_policy([base_item], mode="autonomous",
                           flags_map={base_item.id: flags})
        assert out[0].action == "human_review", (
            f"{label}: expected human_review, got {out[0].action}"
        )

    # Baseline: all checks pass → execute
    out_ok = apply_policy([base_item], mode="autonomous",
                          flags_map={base_item.id: ItemFlags()})
    assert out_ok[0].action == "execute:dispute", (
        f"Baseline: expected execute:dispute, got {out_ok[0].action}"
    )


# ---------------------------------------------------------------------------
# $5,000 rule
# ---------------------------------------------------------------------------

def test_5k_rule_triggers_human_review():
    """Two findings on the same invoice summing to >= $5,000 → human_review."""
    item_a = _overcharge("overcharge:INV-BIG", "INV-BIG", "3000.00")
    item_b = _overcharge("overcharge:INV-BIG", "INV-BIG", "2000.00")
    out = apply_policy([item_a, item_b], mode="supervised")
    for item in out:
        assert item.action == "human_review", (
            f"Expected human_review for ${item.amount_usd} on INV-BIG (sum=$5k), "
            f"got {item.action}"
        )


def test_5k_rule_exactly_5000_triggers():
    """Exactly $5,000.00 on one invoice → human_review (inclusive threshold)."""
    item = _overcharge("overcharge:INV-EXACT", "INV-EXACT", "5000.00")
    out = apply_policy([item], mode="supervised")
    assert out[0].action == "human_review"


def test_5k_rule_below_threshold_does_not_trigger():
    """$4,999.99 stays as draft:dispute in supervised mode."""
    item = _overcharge("overcharge:INV-SMALL", "INV-SMALL", "4999.99")
    out = apply_policy([item], mode="supervised")
    assert out[0].action == "draft:dispute"


def test_5k_rule_autonomous_mode_blocks_execution():
    """Autonomous mode: outbound sum >= $5,000 on one invoice must still be
    human_review, not execute:dispute. The $5k ceiling applies regardless of
    the five safety checks."""
    item = _overcharge("overcharge:INV-AUTO-BIG", "INV-AUTO-BIG", "5500.00")
    out = apply_policy([item], mode="autonomous")
    assert out[0].action == "human_review", (
        f"Expected human_review for $5,500 outbound in autonomous mode, "
        f"got {out[0].action}"
    )


# ---------------------------------------------------------------------------
# Report schema validation (both modes)
# ---------------------------------------------------------------------------

def test_report_both_modes_validate(tmp_path):
    """report command outputs valid JSON in both modes (no findings needed)."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    import jsonschema

    REPO = Path(__file__).resolve().parents[2]
    HARNESS = REPO / "harness" / "harness.py"
    SCHEMA_FILE = REPO / "grader" / "schema" / "report.schema.json"
    schema = json.loads(SCHEMA_FILE.read_text())

    for mode in ("supervised", "autonomous"):
        result = subprocess.run(
            [sys.executable, str(HARNESS), "report",
             "--as-of", "2030-01-01", "--mode", mode,
             "--state-dir", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"report {mode} failed: {result.stderr}"
        report = json.loads(result.stdout)
        jsonschema.validate(report, schema)
