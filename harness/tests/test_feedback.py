"""Task 07 Part D: scoped feedback facts applied to resolved items.

Covers one test per post-rules decision kind plus the "must not spread"
guard that keeps a one-off waiver from leaking to another invoice, another
month or another contract. A one-off waiver that bleeds into a new month is
a score-capping mistake per the glossary.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from nova.feedback import FeedbackItem, apply_post_items, load_feedback, pre_rule_facts
from nova.resolve import Evidence, Item


def _item(cls: str, invoice_id: str, amount: str = "100.00",
          verdict: str = "finding", evidence=None) -> Item:
    return Item(
        id=f"{cls}:{invoice_id}",
        class_=cls, invoice_id=invoice_id, verdict=verdict,
        amount_usd=amount, amount_range=None, deadline=None,
        action="draft:dispute", evidence=evidence or [],
    )


def _envelope(items: list[dict], decided_at: str = "2032-06-01T10:00:00Z",
              after_batch: str = "batch_03") -> dict:
    return {
        "schema_version": "1.0", "world": "W1", "after_batch": after_batch,
        "decided_at": decided_at,
        "decided_by": {"name": "AP", "role": "AP", "entity": "QMP"},
        "items": items,
    }


def _fb(items: list[dict], **kw) -> list[FeedbackItem]:
    env = _envelope(items, **kw)
    return [FeedbackItem.from_envelope(env, it) for it in items]


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------

def test_reject_drops_the_key():
    item = _item("overcharge", "INV-1")
    fb = _fb([{
        "item_id": "fb-01-01", "decision": "reject",
        "finding_key": {"invoice_id": "INV-1", "class": "overcharge"},
        "fact": {"type": "dispute_closed",
                 "subject": {"invoice_id": "INV-1"},
                 "value": {"status": "not a finding"},
                 "evidence": "AP decision"},
        "scope": {"kind": "one_off",
                  "applies_to": {"invoice_id": "INV-1"},
                  "valid_from": "2032-06-01", "valid_to": None},
    }])
    out, ann = apply_post_items([item], fb)
    assert out == []
    assert ann == {}  # dropped items don't need annotations


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

def test_close_drops_the_current_key():
    item = _item("overcharge", "INV-2")
    fb = _fb([{
        "item_id": "fb-01-02", "decision": "close",
        "finding_key": {"invoice_id": "INV-2", "class": "overcharge"},
        "fact": {"type": "dispute_closed",
                 "subject": {"invoice_id": "INV-2"},
                 "value": {"status": "closed"},
                 "evidence": "Carrier agreed"},
        "scope": {"kind": "one_off",
                  "applies_to": {"invoice_id": "INV-2"},
                  "valid_from": "2032-06-01", "valid_to": None},
    }])
    out, _ = apply_post_items([item], fb)
    assert out == []


def test_close_does_not_affect_a_different_invoice():
    """A new invoice with the same wrong rate is still a new finding."""
    closed = _item("overcharge", "INV-2")
    new = _item("overcharge", "INV-99")
    fb = _fb([{
        "item_id": "fb-01-02", "decision": "close",
        "finding_key": {"invoice_id": "INV-2", "class": "overcharge"},
        "fact": {"type": "dispute_closed",
                 "subject": {"invoice_id": "INV-2"},
                 "value": {"status": "closed"},
                 "evidence": "Carrier agreed"},
        "scope": {"kind": "one_off",
                  "applies_to": {"invoice_id": "INV-2"},
                  "valid_from": "2032-06-01", "valid_to": None},
    }])
    out, _ = apply_post_items([closed, new], fb)
    assert [i.id for i in out] == ["overcharge:INV-99"]


# ---------------------------------------------------------------------------
# one_off_approval + waiver_scope (must not spread)
# ---------------------------------------------------------------------------

def test_one_off_approval_makes_the_named_invoice_a_finding_only():
    """Approving a waiver for 2040-03 on INV-3 confirms the key as a finding
    (with learned_at). It must not touch INV-4 in 2040-04 (applies_to is a
    hard lock on invoice_id)."""
    march = _item(
        "waived_but_billed", "INV-3", amount="90.00",
        verdict="cannot_determine",
        evidence=[Evidence(doc="x", page=1, quote="pickup 2040-03-14 AWB1")],
    )
    april = _item(
        "waived_but_billed", "INV-4", amount="90.00",
        evidence=[Evidence(doc="x", page=1, quote="pickup 2040-04-14 AWB2")],
    )
    fb = _fb([{
        "item_id": "fb-02-04", "decision": "one_off_approval",
        "finding_key": {"invoice_id": "INV-3", "class": "waived_but_billed"},
        "fact": {"type": "waiver_scope",
                 "subject": {"person": "Cy", "party": "TBX"},
                 "value": {"months": ["2040-03"]},
                 "evidence": "Confirmed by phone"},
        "scope": {"kind": "one_off",
                  "applies_to": {"invoice_id": "INV-3"},
                  "valid_from": "2040-04-01", "valid_to": None},
    }])
    out, ann = apply_post_items([march, april], fb)
    out_by_id = {i.id: i for i in out}
    assert out_by_id["waived_but_billed:INV-3"].verdict == "finding"
    assert out_by_id["waived_but_billed:INV-3"].action == "draft:dispute"
    assert out_by_id["waived_but_billed:INV-4"].verdict == "finding"
    assert "waived_but_billed:INV-3" in ann
    assert ann["waived_but_billed:INV-3"]["learned_at"]["feedback_item_id"] == "fb-02-04"
    assert "waived_but_billed:INV-4" not in ann


def test_one_off_waiver_does_not_cover_another_month_on_same_invoice():
    """If the invoice's doc date is in a different month than the waiver_scope
    names, the one-off approval does not apply (typed-months guard, audit B4)."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    nov_item = _item(
        "waived_but_billed", "INV-5", amount="200.00",
        verdict="cannot_determine",
        evidence=[Evidence(doc="batch_01/0001.eml", page=1, quote="pickup 2040-11-02 AWB9")],
    )
    docs = [SimpleNamespace(
        doc_id="batch_01/0001.eml",
        received=datetime(2040, 11, 2, tzinfo=timezone.utc),
        sender_name="X", sender_addr="x@y",
    )]
    fb = _fb([{
        "item_id": "fb-02-05", "decision": "one_off_approval",
        "finding_key": {"invoice_id": "INV-5", "class": "waived_but_billed"},
        "fact": {"type": "waiver_scope",
                 "subject": {"person": "Cy", "party": "TBX"},
                 "value": {"months": ["2040-10"]},
                 "evidence": "Confirmed by phone"},
        "scope": {"kind": "one_off",
                  "applies_to": {"invoice_id": "INV-5"},
                  "valid_from": "2040-11-30", "valid_to": None},
    }])
    out, ann = apply_post_items([nov_item], fb, docs=docs)
    # The invoice's doc month is 2040-11, not in [2040-10] → unchanged.
    assert out[0].verdict == "cannot_determine"
    assert "waived_but_billed:INV-5" not in ann


# ---------------------------------------------------------------------------
# override_amount
# ---------------------------------------------------------------------------

def test_override_amount_sets_the_amount_and_carries_learned_at():
    item = _item("overcharge", "INV-6", amount="500.00")
    fb = _fb([{
        "item_id": "fb-07-01", "decision": "override_amount",
        "finding_key": {"invoice_id": "INV-6", "class": "overcharge"},
        "fact": {"type": "dispute_closed",
                 "subject": {"invoice_id": "INV-6"},
                 "value": {"status": "settled", "amount_usd": "212.40"},
                 "evidence": "Settled with the carrier"},
        "scope": {"kind": "one_off",
                  "applies_to": {"invoice_id": "INV-6"},
                  "valid_from": "2040-06-02", "valid_to": None},
    }])
    out, ann = apply_post_items([item], fb)
    assert out[0].amount_usd == "212.40"
    assert ann["overcharge:INV-6"]["learned_at"]["feedback_item_id"] == "fb-07-01"


# ---------------------------------------------------------------------------
# must-not-spread: a different contract never matches
# ---------------------------------------------------------------------------

def test_feedback_item_does_not_affect_other_contracts_cashback():
    """A feedback item scoped to contract C1 doesn't touch C2's cashback."""
    c1 = Item(
        id="cashback:C1/2040-Q1/rebate", class_="cashback",
        invoice_id=None, verdict="finding", amount_usd="10.00",
        amount_range=None, deadline=None, action="draft:claim_credit",
        evidence=[],
    )
    c2 = Item(
        id="cashback:C2/2040-Q1/rebate", class_="cashback",
        invoice_id=None, verdict="finding", amount_usd="20.00",
        amount_range=None, deadline=None, action="draft:claim_credit",
        evidence=[],
    )
    fb = _fb([{
        "item_id": "fb-09-01", "decision": "override_amount",
        "finding_key": {"contract_id": "C1", "period": "2040-Q1",
                        "credit_type": "rebate", "class": "cashback"},
        "fact": {"type": "dispute_closed",
                 "subject": {"contract_id": "C1"},
                 "value": {"amount_usd": "7.50"}, "evidence": "AP"},
        "scope": {"kind": "one_off",
                  "applies_to": {"contract_id": "C1", "period": "2040-Q1",
                                 "credit_type": "rebate"},
                  "valid_from": "2040-04-01", "valid_to": None},
    }])
    out, _ = apply_post_items([c1, c2], fb)
    by_id = {i.id: i for i in out}
    assert by_id["cashback:C1/2040-Q1/rebate"].amount_usd == "7.50"
    assert by_id["cashback:C2/2040-Q1/rebate"].amount_usd == "20.00"


# ---------------------------------------------------------------------------
# load_feedback round-trip through state
# ---------------------------------------------------------------------------

def test_load_feedback_reads_both_envelope_and_bare_items(tmp_path):
    f = tmp_path / "feedback.jsonl"
    envelope = _envelope([{
        "item_id": "env-item",
        "decision": "reject",
        "finding_key": {"invoice_id": "INV-X", "class": "overcharge"},
        "fact": {"type": "dispute_closed", "subject": {}, "value": {},
                 "evidence": ""},
        "scope": {"kind": "one_off", "applies_to": {"invoice_id": "INV-X"},
                  "valid_from": "2040-01-01", "valid_to": None},
    }])
    f.write_text(json.dumps(envelope) + "\n" + json.dumps({
        "item_id": "bare-item",
        "decision": "close",
        "finding_key": {"invoice_id": "INV-Y", "class": "overcharge"},
        "fact": {"type": "dispute_closed", "subject": {}, "value": {},
                 "evidence": ""},
        "scope": {"kind": "one_off", "applies_to": {"invoice_id": "INV-Y"},
                  "valid_from": "2040-01-01", "valid_to": None},
    }) + "\n")
    loaded = load_feedback(tmp_path)
    assert {it.item_id for it in loaded} == {"env-item", "bare-item"}


# ---------------------------------------------------------------------------
# supersedes against a prior report
# ---------------------------------------------------------------------------

def test_supersedes_annotates_changed_items(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    prev = {
        "findings": [{"id": "overcharge:INV-7", "verdict": "finding",
                       "amount_usd": "100.00", "action": "draft:dispute"}],
        "portfolio": {"cashback": [], "expiry": [], "late_fee_risk": []},
    }
    (reports / "2040-05-31_supervised.json").write_text(json.dumps(prev))
    now = _item("overcharge", "INV-7", amount="100.00")
    # override to a new amount
    fb = _fb([{
        "item_id": "fb-s-01", "decision": "override_amount",
        "finding_key": {"invoice_id": "INV-7", "class": "overcharge"},
        "fact": {"type": "dispute_closed", "subject": {},
                 "value": {"amount_usd": "80.00"}, "evidence": ""},
        "scope": {"kind": "one_off", "applies_to": {"invoice_id": "INV-7"},
                  "valid_from": "2040-06-01", "valid_to": None},
    }])
    out, ann = apply_post_items([now], fb, report_dir=reports)
    assert out[0].amount_usd == "80.00"
    assert ann["overcharge:INV-7"]["supersedes"] == ["overcharge:INV-7"]


# ---------------------------------------------------------------------------
# sender_authority: resolve subject.person via held emails' From display names
# ---------------------------------------------------------------------------

def test_sender_authority_resolves_person_name_to_email_via_docs():
    """`confirm + sender_authority` with subject.person (a name) must resolve
    to the sender_addr of every held email whose From display name matches,
    so case.authority_of() can match on the real address (audit B4)."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    docs = [
        SimpleNamespace(doc_id="batch_01/0001.eml",
                        received=datetime(2035, 4, 1, tzinfo=timezone.utc),
                        sender_name="Ada Example",
                        sender_addr="ada@tbx.example"),
        SimpleNamespace(doc_id="batch_01/0002.eml",
                        received=datetime(2035, 4, 2, tzinfo=timezone.utc),
                        sender_name="  ada  example  ",
                        sender_addr="ada.v2@tbx.example"),
        SimpleNamespace(doc_id="batch_01/0003.eml",
                        received=datetime(2035, 4, 3, tzinfo=timezone.utc),
                        sender_name="Other Person",
                        sender_addr="other@tbx.example"),
    ]
    fb = _fb([{
        "item_id": "fb-02-01", "decision": "confirm",
        "finding_key": {"invoice_id": "INV-X", "class": "waived_but_billed"},
        "fact": {"type": "sender_authority",
                 "subject": {"person": "Ada Example", "party": "TBX"},
                 "value": {"categories": ["waivers"]},
                 "evidence": "delegation letter"},
        "scope": {"kind": "standing",
                  "applies_to": {"contract_id": "CDA-01",
                                 "person": "Ada Example",
                                 "category": "waivers"},
                  "valid_from": "2035-04-01", "valid_to": None},
    }])
    prf = pre_rule_facts(fb, docs=docs)
    sa = prf["sender_authority"]
    emails = sorted(x["email"] for x in sa)
    assert emails == ["ada.v2@tbx.example", "ada@tbx.example"]
    for row in sa:
        assert row["contract_id"] == "CDA-01"
        assert row["categories"] == ["waivers"]
        assert row["valid_from"] == "2035-04-01"


def test_learned_at_batch_is_always_a_string(tmp_path):
    """The report schema requires learned_at.batch to be a string. When the
    envelope's after_batch is missing we coerce to '' so JSON validation
    always passes (audit M11)."""
    item = _item("overcharge", "INV-11")
    fb_env = {
        "schema_version": "1.0", "world": "W1",
        "decided_at": "2032-06-01T10:00:00Z",
        "decided_by": {"name": "AP", "role": "AP", "entity": "QMP"},
        "items": [{
            "item_id": "fb-99", "decision": "override_amount",
            "finding_key": {"invoice_id": "INV-11", "class": "overcharge"},
            "fact": {"type": "dispute_closed", "subject": {},
                     "value": {"amount_usd": "7.00"}, "evidence": ""},
            "scope": {"kind": "one_off",
                      "applies_to": {"invoice_id": "INV-11"},
                      "valid_from": "2032-06-01", "valid_to": None},
        }],
    }
    fb = [FeedbackItem.from_envelope(fb_env, fb_env["items"][0])]
    _out, ann = apply_post_items([item], fb)
    assert isinstance(ann["overcharge:INV-11"]["learned_at"]["batch"], str)


def test_sender_authority_without_docs_or_match_emits_nothing():
    """A person-only sender_authority with no matching display name produces
    no authority rows (don't fall back to using the name as an email)."""
    fb = _fb([{
        "item_id": "fb-02-01", "decision": "confirm",
        "finding_key": {"invoice_id": "INV-X", "class": "waived_but_billed"},
        "fact": {"type": "sender_authority",
                 "subject": {"person": "Nobody Here", "party": "TBX"},
                 "value": {"categories": ["waivers"]},
                 "evidence": ""},
        "scope": {"kind": "standing",
                  "applies_to": {"contract_id": "CDA-01",
                                 "category": "waivers"},
                  "valid_from": "2035-04-01", "valid_to": None},
    }])
    assert pre_rule_facts(fb, docs=[])["sender_authority"] == []
