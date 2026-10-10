"""Feedback as scoped facts (GLOSSARY §feedback.json, task 07 Part D).

Feedback items the human sends back after a batch become level-2 facts stored
in ``<state_dir>/feedback.jsonl``. Later report runs load them, filter them to
the keys they apply to and transform the final items accordingly.

Scopes
------
- ``standing`` applies to any later key whose ``applies_to`` filters all match,
  inside ``valid_from`` → ``valid_to``.
- ``one_off`` changes exactly one key (the ``applies_to.invoice_id`` or the
  cashback period). A one-off waiver must never cover another month — that is
  one of the glossary's score-capping mistakes, so the scope check is tight.

Decisions
---------
Only post-rules decisions live here. Pre-rules decisions
(``sender_authority``, ``rate_accepted``, ``resolve_conflict``) are injected
into the Case before rules fire via :func:`apply_pre_rules`.

Post-rules decisions:
- ``reject`` → drop that key.
- ``close`` → drop that key for this batch; a later invoice with the same
  wrong rate (a new key) is still a finding.
- ``one_off_approval`` + ``waiver_scope`` → the waiver covers the named
  months on that key only: the item becomes a ``finding`` (verdict changes
  from ``cannot_determine`` to ``finding``) with ``learned_at``.
- ``override_amount`` → use ``fact.value.amount_usd`` as the amount with
  ``learned_at``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from nova.resolve import Item


@dataclass
class FeedbackItem:
    item_id: str
    batch: Optional[str]
    decision: str                 # confirm | reject | close | override_amount | resolve_conflict | one_off_approval
    fact_type: str                # dispute_closed | waiver_scope | rate_accepted | precedence | sender_authority
    finding_key: dict             # {invoice_id, class} or cashback shape
    fact_value: dict
    scope_kind: str               # standing | one_off
    applies_to: dict
    valid_from: Optional[str]
    valid_to: Optional[str]
    decided_at: Optional[str]
    raw: dict                     # keep the original for forwards-compat

    @classmethod
    def from_envelope(cls, envelope: dict, item: dict) -> "FeedbackItem":
        scope = item.get("scope") or {}
        fact = item.get("fact") or {}
        return cls(
            item_id=item.get("item_id", ""),
            batch=envelope.get("after_batch"),
            decision=item.get("decision", ""),
            fact_type=fact.get("type", ""),
            finding_key=item.get("finding_key") or {},
            fact_value=fact.get("value") or {},
            scope_kind=scope.get("kind", ""),
            applies_to=scope.get("applies_to") or {},
            valid_from=scope.get("valid_from"),
            valid_to=scope.get("valid_to"),
            decided_at=envelope.get("decided_at"),
            raw=item,
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_feedback(state_dir: Path) -> list[FeedbackItem]:
    """Return every feedback item persisted so far, newest last.

    ``state.append_feedback`` stores one envelope per line (an envelope may
    contain the whole payload or a single item — both shapes are tolerated).
    """
    path = Path(state_dir) / "feedback.jsonl"
    if not path.exists():
        return []
    out: list[FeedbackItem] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "items" in obj and isinstance(obj["items"], list):
            for it in obj["items"]:
                out.append(FeedbackItem.from_envelope(obj, it))
        elif "item_id" in obj:
            # the state store wrote a single item without its envelope; keep
            # whatever outer context fields are present.
            out.append(FeedbackItem.from_envelope(obj, obj))
    return out


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _finding_key_matches(fb: FeedbackItem, item: Item) -> bool:
    """Does this feedback item target this result item?"""
    k = fb.finding_key or {}
    want_cls = k.get("class")
    if want_cls and want_cls != item.class_:
        return False
    want_inv = k.get("invoice_id")
    if want_inv and want_inv != (item.invoice_id or ""):
        return False
    # Cashback-shaped key.
    for field_ in ("contract_id", "period", "credit_type"):
        val = k.get(field_)
        if not val:
            continue
        # The resolved item.id is "cashback:<contract>/<period>/<type>".
        if val not in item.id:
            return False
    return True


def _within_dates(fb: FeedbackItem, iso: Optional[str]) -> bool:
    """Check an ISO date against (valid_from, valid_to); open-ended if either side is None."""
    if iso is None:
        return True
    if fb.valid_from and iso < fb.valid_from:
        return False
    if fb.valid_to and iso > fb.valid_to:
        return False
    return True


def _one_off_matches(fb: FeedbackItem, item: Item) -> bool:
    """One-off scope: applies_to.invoice_id or cashback key must be the item's."""
    at = fb.applies_to or {}
    inv = at.get("invoice_id")
    if inv and inv == (item.invoice_id or ""):
        return True
    # Cashback shape.
    if any(at.get(k) for k in ("contract_id", "period", "credit_type")):
        for field_ in ("contract_id", "period", "credit_type"):
            v = at.get(field_)
            if v and v not in item.id:
                return False
        return True
    return False


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _versioned_id(old_id: str, batch: Optional[str]) -> str:
    tag = batch or "fb"
    return f"{old_id}@{tag}"


@dataclass
class _ApplyChange:
    new_item: Optional[Item]      # None = drop; a different Item = change
    learned_at: Optional[dict] = None


def _apply_one(fb: FeedbackItem, item: Item, docs=None) -> Optional[_ApplyChange]:
    """Return the change this feedback item would make to *item*, or None."""
    if not _finding_key_matches(fb, item):
        return None
    if fb.scope_kind == "one_off" and not _one_off_matches(fb, item):
        return None

    if fb.decision == "reject":
        return _ApplyChange(new_item=None,
                            learned_at={"feedback_item_id": fb.item_id,
                                        "batch": fb.batch or ""})
    if fb.decision == "close":
        # The task says "close stops raising that key" — drop it from this report.
        return _ApplyChange(new_item=None,
                            learned_at={"feedback_item_id": fb.item_id,
                                        "batch": fb.batch or ""})
    if fb.decision == "one_off_approval" and fb.fact_type == "waiver_scope":
        months = fb.fact_value.get("months") or []
        # Typed-months guard: if the feedback lists months, and we can derive
        # the item's months from doc dates, require intersection. If we can't
        # derive months, trust the one_off invoice-id lock. Never search quote
        # text (audit B4).
        if months and docs is not None:
            item_months = _item_months_from_docs(item, docs)
            if item_months and not (set(months) & item_months):
                return None
        # The waiver covers that key only: make the key a finding.
        outbound_base = {
            "overcharge": "dispute", "duplicate": "dispute",
            "waived_but_billed": "dispute", "late_fee_not_owed": "dispute",
            "cashback": "claim_credit",
        }.get(item.class_, "dispute")
        action = item.action
        if item.verdict != "finding":
            action = f"draft:{outbound_base}"
        finding = Item(
            id=item.id, class_=item.class_, invoice_id=item.invoice_id,
            verdict="finding",
            amount_usd=item.amount_usd, amount_range=item.amount_range,
            deadline=item.deadline, action=action, evidence=item.evidence,
            missing_doc=None,
        )
        return _ApplyChange(new_item=finding,
                            learned_at={"feedback_item_id": fb.item_id,
                                        "batch": fb.batch or ""})
    if fb.decision == "override_amount":
        amt = fb.fact_value.get("amount_usd")
        if amt is None:
            return None
        new = Item(
            id=item.id, class_=item.class_, invoice_id=item.invoice_id,
            verdict=item.verdict, amount_usd=str(amt),
            amount_range=item.amount_range, deadline=item.deadline,
            action=item.action, evidence=item.evidence,
            missing_doc=item.missing_doc,
        )
        return _ApplyChange(new_item=new,
                            learned_at={"feedback_item_id": fb.item_id,
                                        "batch": fb.batch or ""})
    return None


def _item_months_from_docs(item: Item, docs) -> set[str]:
    """Return the YYYY-MM months the item's evidence docs were received in.

    Used as a typed guard for one_off waiver_scope: the audit (B4) forbids
    searching evidence quote text for a month substring.
    """
    doc_by_id = {d.doc_id: d for d in docs}
    out: set[str] = set()
    for ev in item.evidence:
        d = doc_by_id.get(ev.doc)
        if d is not None:
            out.add(d.received.strftime("%Y-%m"))
    return out


def apply_post_items(
    items: list[Item],
    feedback_items: list[FeedbackItem],
    *,
    report_dir: Optional[Path] = None,
    docs=None,
) -> tuple[list[Item], dict[str, dict]]:
    """Apply feedback to resolved+policy items.

    Returns the modified list and a dict ``item_id → {learned_at, supersedes}``
    that the harness folds into the JSON output.
    """
    annotations: dict[str, dict] = {}
    out: list[Item] = []
    kept_ids = {it.id for it in items}
    for item in items:
        current = item
        changed = False
        learned_at: Optional[dict] = None
        for fb in feedback_items:
            change = _apply_one(fb, current, docs=docs)
            if change is None:
                continue
            changed = True
            learned_at = change.learned_at
            if change.new_item is None:
                current = None  # dropped
                break
            current = change.new_item
        if current is None:
            kept_ids.discard(item.id)
            continue
        out.append(current)
        if changed and learned_at:
            annotations[current.id] = {"learned_at": learned_at}
    # supersedes: compare against the previous report (if any). ``retro`` is
    # annotated by the harness, which can see fact dates (effective_from /
    # invoice_date) that aren't on the DocRecord alone.
    if report_dir is not None:
        prev = _latest_prev_report(report_dir)
        if prev is not None:
            _annotate_supersedes(out, annotations, prev)
    return out, annotations


# ---------------------------------------------------------------------------
# Previous-report diffing: supersedes / retro
# ---------------------------------------------------------------------------

def _latest_prev_report(report_dir: Path) -> Optional[dict]:
    if not report_dir.exists():
        return None
    reports = sorted(report_dir.glob("*.json"))
    if not reports:
        return None
    try:
        return json.loads(reports[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _iter_prev_items(report: dict):
    for f in report.get("findings") or []:
        yield f
    for group in ("cashback", "expiry", "late_fee_risk"):
        for f in (report.get("portfolio") or {}).get(group) or []:
            yield f


def _annotate_supersedes(
    items: list[Item], annotations: dict[str, dict], prev: dict,
) -> None:
    """A key whose verdict, amount or action changed gets a new versioned id
    and ``supersedes`` lists the previous id. Reported in-place in annotations.
    """
    prev_by_key: dict[str, dict] = {}
    for pf in _iter_prev_items(prev):
        prev_by_key[pf["id"].split("@")[0]] = pf
    for item in items:
        base_id = item.id.split("@")[0]
        prev_item = prev_by_key.get(base_id)
        if prev_item is None:
            continue
        changed = (
            prev_item.get("verdict") != item.verdict
            or prev_item.get("amount_usd") != item.amount_usd
            or prev_item.get("action") != item.action
        )
        if not changed:
            continue
        ann = annotations.setdefault(item.id, {})
        ann["supersedes"] = [prev_item["id"]]


# ---------------------------------------------------------------------------
# Pre-rule injection (sender_authority / rate_accepted / resolve_conflict)
# ---------------------------------------------------------------------------

def _emails_for_person(name: str, docs) -> list[str]:
    """Return every DocRecord sender_addr whose display name matches *name*.

    Match is case-insensitive and whitespace-normalised. Deduplicated,
    preserving first-seen order.
    """
    if not name or not docs:
        return []
    want = " ".join(name.split()).lower()
    seen: list[str] = []
    for d in docs:
        got = " ".join((d.sender_name or "").split()).lower()
        if got and got == want and d.sender_addr and d.sender_addr not in seen:
            seen.append(d.sender_addr)
    return seen


def pre_rule_facts(feedback_items: list[FeedbackItem], docs=None) -> dict:
    """Return standing-scope facts the Case consumes:

    - ``sender_authority``: list of ``{email, contract_id, categories, valid_from, valid_to}``
    - ``rate_accepted``: list of ``{contract_id, lane, sent_by, sent_on,
      effective_from, effective_to, valid_from, valid_to}``
    - ``precedence``: list of ``{contract_id, lane, use, valid_from, valid_to}``

    ``close`` + ``rate_accepted`` and ``confirm`` + ``rate_accepted`` both
    produce a standing rate_accepted fact (the ``close`` only decides what to
    do with the historic finding; the standing rate still carries forward).
    """
    out: dict[str, list] = {"sender_authority": [], "rate_accepted": [],
                             "precedence": []}
    for fb in feedback_items:
        if fb.scope_kind != "standing":
            continue
        at = fb.applies_to or {}
        subject = (fb.raw.get("fact") or {}).get("subject") or {}
        if fb.fact_type == "sender_authority":
            # The subject may give a direct email, or just a person name
            # (`subject.person`); resolve the name via held emails' From
            # display names so case.authority_of() can match on the real
            # address. Grant the category on that contract from valid_from.
            cid = at.get("contract_id") or ""
            cats = fb.fact_value.get("categories") or []
            if not cats and at.get("category"):
                cats = [at["category"]]
            emails: list[str] = []
            direct = at.get("email") or subject.get("email")
            if direct:
                emails.append(direct)
            person = subject.get("person") or at.get("person")
            if person:
                emails.extend(_emails_for_person(person, docs))
            # Dedupe preserving order.
            seen: list[str] = []
            for e in emails:
                if e and e not in seen:
                    seen.append(e)
            if cid and cats:
                for e in seen:
                    out["sender_authority"].append({
                        "email": e,
                        "contract_id": cid,
                        "categories": list(cats),
                        "valid_from": fb.valid_from,
                        "valid_to": fb.valid_to,
                    })
        elif fb.fact_type == "rate_accepted":
            cid = at.get("contract_id") or subject.get("contract_id") or ""
            lane = at.get("lane") or subject.get("lane") or ""
            if cid and lane:
                val = fb.fact_value or {}
                out["rate_accepted"].append({
                    "contract_id": cid,
                    "lane": lane,
                    "sent_by": val.get("sent_by"),
                    "sent_on": val.get("sent_on"),
                    "effective_from": val.get("effective_from"),
                    "effective_to": val.get("effective_to"),
                    "valid_from": fb.valid_from,
                    "valid_to": fb.valid_to,
                })
        elif fb.fact_type == "precedence":
            cid = at.get("contract_id") or subject.get("contract_id") or ""
            lane = at.get("lane") or subject.get("lane") or ""
            if cid and lane:
                out["precedence"].append({
                    "contract_id": cid,
                    "lane": lane,
                    "use": (fb.fact_value or {}).get("use"),
                    "valid_from": fb.valid_from,
                    "valid_to": fb.valid_to,
                })
    return out
