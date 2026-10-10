"""Your harness. The grader calls exactly these three commands, in a fresh process each time:

    python harness.py ingest <batch_dir> --state-dir <dir>
    python harness.py report --as-of YYYY-MM-DD [--mode supervised|autonomous] [--state-dir <dir>] > report.json
    python harness.py feedback <feedback.json> --state-dir <dir>

- ingest: read every .eml in <batch_dir> (attachments inside) and store what you learn under --state-dir. The process
  is restarted between batches, so everything you need later must be on disk.
- report: print one report.json (grader/schema/report.schema.json) to stdout. Only documents received on or before
  --as-of count. --mode defaults to supervised.
- feedback: take in a person's decisions on what you escalated (feedback.json) and let them change later reports.

The environment gives ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL. Keep the argument names as they are: grader/validate.py
checks them. Replace the NotImplementedError bodies with your code.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

DEFAULT_STATE = ".state"

# Ensure harness/nova is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load optional repo-local settings (cache dir, max_paid_tokens, model overrides).
# Env vars already set win over the file; missing file is a no-op.
from nova.local_settings import apply as _apply_local_settings
_apply_local_settings()


# ---------------------------------------------------------------------------
# Reader dispatch
# ---------------------------------------------------------------------------

def _dispatch_kind(kind: str | None) -> str | None:
    """Map a classification kind to the reader to use."""
    if kind in ("contract", "amendment"):
        return "contract"
    if kind in ("invoice", "credit_note", "statement"):
        return "billing"
    if kind in ("awb", "dg_declaration"):
        return "shipment"
    if kind in ("tracking_export", "payment_register"):
        return "sheet"
    if kind == "email":
        return "email"
    return None   # "other" and unrecognised kinds are skipped


def _read_record(client, record):
    """Classify and read one record. Returns (type_, data) or None to skip."""
    from nova.readers import classify as classify_mod
    from nova.readers import billing as billing_mod
    from nova.readers import contract as contract_mod
    from nova.readers import email_doc as email_mod
    from nova.readers import sheet as sheet_mod
    from nova.readers import shipment as shipment_mod
    from nova.readers import scan as scan_mod

    # Emails: always read as email
    if record.ext == "eml":
        result = email_mod.read(client, record)
        if result.instance is None:
            return None
        return ("EmailFacts", result.data)

    # Image-only PDFs: scan reader (needs the raw PDF bytes).
    if record.is_scan:
        if record.ext != "pdf" or not getattr(record, "raw_bytes", None):
            return None
        result = scan_mod.read(client, record, pdf_bytes=record.raw_bytes)
        if result.instance is None:
            return None
        return ("BillingDoc", result.data)

    # Skip unreadable
    if record.unreadable or not record.pages:
        return None

    # Classify
    cls = classify_mod.read(client, record)
    if cls is None:
        return None

    reader_name = _dispatch_kind(cls.kind)
    if reader_name is None:
        return None

    READER_MAP = {
        "contract": contract_mod,
        "billing": billing_mod,
        "shipment": shipment_mod,
        "sheet": sheet_mod,
    }
    mod = READER_MAP[reader_name]
    result = mod.read(client, record)
    if result.instance is None:
        return None

    SCHEMA_MAP = {
        "contract": "ContractTerms",
        "billing": "BillingDoc",
        "shipment": "ShipmentDoc",
        "sheet": "SheetMap",
    }
    return (SCHEMA_MAP[reader_name], result.data)


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def ingest(batch_dir: str, state_dir: str, estimate: bool = False) -> None:
    from nova.llm import LLMClient
    from nova.mailbox import load_batch
    from nova.state import StateDir

    state = StateDir(state_dir)
    state.ensure()

    records = load_batch(Path(batch_dir))

    if estimate:
        # Schema overhead in tokens (measured from flatten_schema output sizes).
        SCHEMA_TOK = {
            "classify": 253,
            "email":    3345,
            "billing":  3613,
            "contract": 8656,
            "sheet":    653,
            "shipment": 2628,
        }
        # Output token averages from the 05a real run, per document type.
        OUT_AVG = {
            "classify": 50,
            "email":    405,
            "billing":  1702,
            "contract": 7694,
            "sheet":    190,
            "shipment": 312,
        }
        # Classify contract vs billing: long PDFs (> 3000 text tokens) are likely contracts.
        CONTRACT_TEXT_THRESHOLD = 3000

        def _text_tokens(pages: list[str]) -> int:
            return sum(len(p) for p in pages) // 4

        def _truncated_tokens(pages: list[str], max_lines: int) -> int:
            chars = 0
            line_count = 0
            for page in pages:
                for line in page.split("\n"):
                    if line_count >= max_lines:
                        break
                    chars += len(line) + 1  # +1 for newline
                    line_count += 1
                if line_count >= max_lines:
                    break
            return chars // 4

        total_in = total_out = 0
        counts: dict[str, int] = {}
        for rec in records:
            if state.facts_exist(rec.doc_id):
                continue
            ext = rec.ext.lower() if rec.ext else "other"
            text_tok = _text_tokens(rec.pages)
            cls_tok = _truncated_tokens(rec.pages, 40)

            if ext == "eml":
                i = text_tok + SCHEMA_TOK["email"]
                o = OUT_AVG["email"]
                label = "eml"
            elif ext == "pdf":
                # Classify (fast, 40-line truncation) + reader
                classify_i = cls_tok + SCHEMA_TOK["classify"]
                classify_o = OUT_AVG["classify"]
                if text_tok > CONTRACT_TEXT_THRESHOLD:
                    reader_i = text_tok + SCHEMA_TOK["contract"]
                    reader_o = OUT_AVG["contract"]
                    label = "pdf_contract"
                else:
                    reader_i = text_tok + SCHEMA_TOK["billing"]
                    reader_o = OUT_AVG["billing"]
                    label = "pdf_billing"
                i = classify_i + reader_i
                o = classify_o + reader_o
            elif ext == "xlsx":
                # Classify (fast, 40-line truncation) + sheet (fast, 4-line truncation)
                classify_i = cls_tok + SCHEMA_TOK["classify"]
                classify_o = OUT_AVG["classify"]
                sheet_tok = _truncated_tokens(rec.pages, 4)
                sheet_i = sheet_tok + SCHEMA_TOK["sheet"]
                sheet_o = OUT_AVG["sheet"]
                i = classify_i + sheet_i
                o = classify_o + sheet_o
                label = "xlsx"
            else:
                i = o = 0
                label = ext or "other"
            total_in += i
            total_out += o
            counts[label] = counts.get(label, 0) + 1

        print(
            f"ESTIMATE: {sum(counts.values())} unread docs "
            f"({', '.join(f'{v} {k}' for k, v in sorted(counts.items()))})\n"
            f"  projected input tokens:  {total_in:,}\n"
            f"  projected output tokens: {total_out:,}\n"
            f"  projected total paid:    {total_in + total_out:,}",
            file=sys.stderr,
        )
        return

    # Full read: thread pool, at most 8 concurrent. audit M4: enforce a
    # per-step deadline of ~540s; stop starting new calls past it so the
    # harness never blows the 600s step limit.
    client = LLMClient(Path(state_dir))
    import time as _time
    deadline = _time.monotonic() + 540

    def _process(record):
        if _time.monotonic() > deadline:
            return
        # Always save the raw DocRecord (pages needed for quote resolution).
        was_scan = record.is_scan
        if not state.doc_exists(record.doc_id):
            state.save_doc(record)
        if state.facts_exist(record.doc_id):
            return
        result = _read_record(client, record)
        if result is None:
            return
        type_, data = result
        received_at = record.received.isoformat()
        state.save_facts(record.doc_id, type_, data, received_at)
        # Scan reader mutated pages with the transcription; persist them so
        # rule evidence can resolve quotes from the saved record.
        if was_scan and not record.is_scan:
            state.save_doc(record)

    # First, re-attempt any already-saved DocRecord whose facts were never
    # produced (previous ingest timed out or hit a model error). audit M4.
    saved_docs = state.load_docs()
    seen_ids = {r.doc_id for r in records}
    retry_queue = [d for d in saved_docs
                   if d.doc_id not in seen_ids and not state.facts_exist(d.doc_id)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_process, rec): rec for rec in list(records) + retry_queue}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                rec = futures[fut]
                print(f"ingest error for {rec.doc_id}: {exc}", file=sys.stderr)

    # Print ledger totals to stderr.
    _print_ledger_summary(Path(state_dir))


def _print_ledger_summary(state_dir: Path) -> None:
    ledger = state_dir / "ledger.jsonl"
    if not ledger.exists():
        return
    paid_in = paid_out = cached_calls = paid_calls = 0
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("cached"):
            cached_calls += 1
        else:
            paid_calls += 1
            paid_in += e.get("input_tokens", 0)
            paid_out += e.get("output_tokens", 0)
    print(
        f"LEDGER: {paid_calls} paid calls ({paid_in:,} in + {paid_out:,} out = "
        f"{paid_in + paid_out:,} tokens), {cached_calls} cache hits",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def report(as_of: str, mode: str, state_dir: str) -> dict:
    from nova.case import Case
    from nova.confidence import score as conf_score
    from nova.policy import apply_policy, DEFAULT_FLAGS
    from nova.resolve import resolve
    from nova.rules.cashback import run as run_cashback
    from nova.rules.duplicate import run as run_duplicate
    from nova.rules.expiry import run as run_expiry
    from nova.rules.late_fees import run as run_late_fees
    from nova.rules.overcharge import run as run_overcharge
    from nova.rules.waived_but_billed import run as run_waived
    from nova.state import StateDir

    as_of_date = date.fromisoformat(as_of)
    state = StateDir(state_dir)

    # Load reader facts, filtered by as_of.
    facts = state.load_all_facts(as_of=as_of_date)

    # Build mailbox for quote resolution.
    mailbox = _build_mailbox(state_dir, facts)

    # Load feedback once; standing facts feed into Case, post-rules decisions
    # fold in after apply_policy.
    from nova.feedback import load_feedback, pre_rule_facts, apply_post_items
    feedback_items = load_feedback(state.root)
    docs = state.load_docs(as_of=as_of_date)
    prf = pre_rule_facts(feedback_items, docs=docs)

    last_flags: dict = {}

    def _run(case) -> list:
        """Run each rule in try/except so a single bad fact drops one item,
        never the batch (audit B3)."""
        nonlocal last_flags
        import traceback
        candidates = []
        for name, run_fn in (
            ("overcharge", run_overcharge),
            ("duplicate", run_duplicate),
            ("waived_but_billed", run_waived),
            ("late_fees", run_late_fees),
            ("cashback", run_cashback),
            ("expiry", run_expiry),
        ):
            try:
                candidates.extend(run_fn(case))
            except Exception as e:
                print(f"rule {name} failed: {e!r}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
        try:
            xs = resolve(candidates, mailbox)
        except Exception as e:
            print(f"resolve failed: {e!r}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            xs = []
        try:
            flags_map = _flags_from_case(xs, case, feedback_items)
        except Exception as e:
            print(f"flags failed: {e!r}", file=sys.stderr)
            flags_map = {}
        last_flags = flags_map
        return apply_policy(xs, mode=mode, flags_map=flags_map)

    # Build Case with Claude Judge (uses LLM client for judge calls, cached).
    judge_fn = _make_judge(state_dir)
    case = Case.from_records(facts, as_of=as_of, judge=judge_fn, mailbox=mailbox,
                              pre_rule_facts=prf, docs=docs)
    items = _run(case)

    # If any pre-rules feedback exists, run again without it and diff to
    # mark learned_at on keys whose verdict/amount/action moved. The diff
    # is cheap: a judge call is cached by LLMClient so no extra API spend.
    pre_rules_items: dict[str, "Item"] = {}
    if any(prf.get(k) for k in ("sender_authority", "rate_accepted", "precedence")):
        base_case = Case.from_records(facts, as_of=as_of, judge=judge_fn,
                                       mailbox=mailbox, docs=docs)
        for it in _run(base_case):
            pre_rules_items[it.id] = it

    # Apply scoped feedback (reject / close / one_off_approval / override_amount)
    # and compute learned_at / supersedes against the latest saved report.
    items, annotations = apply_post_items(
        items, feedback_items, report_dir=state.reports_dir, docs=docs,
    )

    # Pre-rules learned_at: for each item that differs from the no-feedback run.
    if pre_rules_items:
        from nova.feedback import _finding_key_matches  # type: ignore
        for it in items:
            base = pre_rules_items.get(it.id)
            if base is None:
                continue
            changed = (
                base.verdict != it.verdict
                or base.amount_usd != it.amount_usd
                or base.action != it.action
            )
            if not changed:
                continue
            # Attribute to the standing feedback that most plausibly caused
            # the change (audit M11): prefer an exact finding_key match,
            # then a contract/lane whose contract id appears in the item's
            # id or whose finding_key invoice matches, else fall back to
            # the single available standing item.
            standing = [fb for fb in feedback_items if fb.scope_kind == "standing"]
            fb_match = None
            for fb in standing:
                k = fb.finding_key or {}
                if k.get("invoice_id") and k["invoice_id"] == (it.invoice_id or ""):
                    fb_match = fb
                    break
            if fb_match is None:
                for fb in standing:
                    cid = (fb.applies_to or {}).get("contract_id") or ""
                    if cid and (cid in it.id or cid in (it.invoice_id or "")):
                        fb_match = fb
                        break
            if fb_match is None and len(standing) == 1:
                fb_match = standing[0]
            if fb_match is not None:
                annotations.setdefault(it.id, {})["learned_at"] = {
                    "feedback_item_id": fb_match.item_id,
                    "batch": fb_match.batch or "",
                }

    # retro: a key that only exists because of a document received after the
    # prior report but dated/effective-from before that prior as_of (audit B5).
    try:
        _annotate_retro(items, annotations, state.reports_dir, case, docs)
    except Exception as e:
        print(f"retro annotation failed: {e!r}", file=sys.stderr)

    # Per-item signals for the confidence score (audit M1).
    inv_currency = {}
    inv_awbs = {}
    for b in case.billings:
        inv_currency[b.bill.id.value] = (
            b.bill.currency.value if b.bill.currency else "USD"
        ).upper()
        inv_awbs[b.bill.id.value] = {ln.awb for ln in b.bill.lines if ln.awb}
    signals: dict = {}
    for it in items:
        f = last_flags.get(it.id)
        pickup_tracked = f.pickup_from_tracking if f is not None else True
        inr = (inv_currency.get(it.invoice_id or "", "USD") == "INR")
        # Mark judge_used for waiver findings whose source email had a
        # non-null condition — the Judge was called in that path.
        judge_used = False
        if it.class_ == "waived_but_billed" and it.verdict == "finding":
            for ev in it.evidence:
                for em in case.emails:
                    if em.doc != ev.doc:
                        continue
                    for w in (em.email.waivers or []):
                        if w.condition:
                            judge_used = True
                            break
        min_auth = 2 if (f is not None and not f.all_facts_level3plus) else 1
        signals[it.id] = {
            "pickup_from_tracking": pickup_tracked,
            "inr_converted": inr,
            "judge_used": judge_used,
            "min_term_authority": min_auth,
        }

    # Serialise to report JSON.
    report_obj = _build_report(items, as_of, mode, conf_score,
                                annotations=annotations, signals=signals)
    # Persist the report snapshot so later batches can diff for supersedes.
    try:
        state.reports_dir.mkdir(parents=True, exist_ok=True)
        snapshot = state.reports_dir / f"{as_of}_{mode}.json"
        snapshot.write_text(json.dumps(report_obj, indent=1))
    except OSError:
        pass
    return report_obj


def _annotate_retro(items, annotations: dict, report_dir, case, docs) -> None:
    """Mark ``retro: true`` on items that only exist because of a backdated
    document (GLOSSARY §New documents, audit B5). The deciding document must
    have been received after the previous report's ``as_of``, and the fact it
    carries must be effective/dated before that cutoff.
    """
    from nova.feedback import _latest_prev_report, _iter_prev_items

    prev = _latest_prev_report(report_dir)
    if prev is None:
        return
    prev_as_of = prev.get("as_of")
    if not prev_as_of:
        return
    prev_ids = {pf["id"].split("@")[0] for pf in _iter_prev_items(prev)}
    doc_received: dict[str, str] = {}
    for d in docs or []:
        try:
            doc_received[d.doc_id] = d.received.strftime("%Y-%m-%d")
        except Exception:
            continue
    # Doc id -> "stated date": contract.effective_from, amendment.effective_from,
    # invoice.invoice_date. If stated < prev_as_of, the doc is backdated.
    stated: dict[str, str] = {}
    for c in case.contracts:
        try:
            stated[c.doc] = c.effective_from
        except Exception:
            pass
    for b in case.billings:
        inv_d = b.bill.invoice_date.value if b.bill.invoice_date else None
        if inv_d:
            stated[b.doc] = inv_d
    for item in items:
        base_id = item.id.split("@")[0]
        if base_id in prev_ids:
            continue
        if annotations.get(item.id, {}).get("supersedes"):
            continue
        found = False
        for ev in item.evidence:
            rec = doc_received.get(ev.doc)
            if rec is None or rec <= prev_as_of:
                continue
            dt = stated.get(ev.doc)
            if dt is None or dt >= prev_as_of:
                continue
            found = True
            break
        if found:
            annotations.setdefault(item.id, {})["retro"] = True


def _period_for_invoice_lane(case, invoice_id: str, lane: str,
                             contract_id: str) -> str | None:
    """Rate-period label for an invoice-line's lane on its pickup date."""
    if not contract_id:
        return None
    for b in case.billings:
        if b.bill.id.value != invoice_id:
            continue
        for ln in b.bill.lines:
            if ln.lane != lane or not ln.awb:
                continue
            pk = case.pickup_date(ln.awb)
            if pk is None:
                continue
            msa = case.msa_for(contract_id)
            if msa is None:
                return None
            return case.period_for(msa, pk[0])
    return None


def _flags_from_case(items, case, feedback_items) -> dict:
    """Compute per-item ItemFlags from the resolved items and the Case.

    The five autonomous-mode checks (audit B1):
      1. Evidence complete + pickup from a tracking source.
      2. No open conflict on the same contract/lane as this item.
      3. $5k threshold — handled by apply_policy.
      4. Action is reversible — handled by apply_policy.
      5. Authority levels: a feedback-touched key counts as level 2 and so
         fails if no higher-authority source backs it.
    """
    from nova.policy import ItemFlags

    # AWBs that appear in any tracking sheet row or shipment doc.
    tracked_awbs: set[str] = set()
    for s in case.sheets:
        if s.sheet.kind != "tracking_export":
            continue
        for row in s.rows or []:
            awb = (row.get("awb") or "").strip()
            if awb:
                tracked_awbs.add(awb)
    for sh in case.shipments:
        awb = (sh.ship.awb.value if sh.ship.awb else "").strip()
        if awb:
            tracked_awbs.add(awb)

    # invoice_id → (list of AWBs, list of lanes, contract_id)
    invoice_awbs: dict[str, list[str]] = {}
    invoice_contract: dict[str, str] = {}
    invoice_lanes: dict[str, set[str]] = {}
    for b in case.billings:
        inv = b.bill.id.value
        invoice_awbs[inv] = [ln.awb for ln in b.bill.lines if ln.awb]
        invoice_lanes[inv] = {ln.lane for ln in b.bill.lines if ln.lane}
        if b.bill.contract_ref:
            invoice_contract[inv] = b.bill.contract_ref.value
        else:
            msa = case.contract_for_invoice(b)
            if msa is not None:
                invoice_contract[inv] = msa.id

    # Audit B1 (finish): open-conflict check covers the same contract and
    # lane (and rate period). Build the set of (contract_id, lane, period)
    # with open conflicts, falling back to invoice_id for conflicts that
    # we can't resolve to a lane.
    conflict_invoices: set[str] = set()
    conflict_lane_period: set[tuple[str, str, str]] = set()
    for it in items:
        if it.verdict != "conflict" or not it.invoice_id:
            continue
        conflict_invoices.add(it.invoice_id)
        c_id = invoice_contract.get(it.invoice_id)
        if not c_id:
            continue
        for lane in invoice_lanes.get(it.invoice_id, set()):
            period = _period_for_invoice_lane(case, it.invoice_id, lane, c_id)
            conflict_lane_period.add((c_id, lane, period or ""))

    # Items whose key matched any feedback fact (standing or one_off).
    from nova.feedback import _finding_key_matches  # type: ignore
    feedback_touched: set[str] = set()
    for it in items:
        for fb in feedback_items or []:
            try:
                if _finding_key_matches(fb, it):
                    feedback_touched.add(it.id)
                    break
            except Exception:
                continue

    # Audit B1 (finish): the pickup-source check applies to every class
    # that relies on a pickup date — overcharge for the rate period and
    # waived_but_billed for the waiver's month-of-pickup match.
    PICKUP_SENSITIVE = {"overcharge", "waived_but_billed"}

    flags_map: dict = {}
    for it in items:
        if it.class_ in PICKUP_SENSITIVE:
            awbs = invoice_awbs.get(it.invoice_id or "", [])
            pickup_tracked = bool(awbs) and any(a in tracked_awbs for a in awbs)
        else:
            pickup_tracked = True
        same_conflict = False
        if it.invoice_id and it.verdict != "conflict":
            if it.invoice_id in conflict_invoices:
                same_conflict = True
            else:
                c_id = invoice_contract.get(it.invoice_id, "")
                for lane in invoice_lanes.get(it.invoice_id, set()):
                    period = _period_for_invoice_lane(
                        case, it.invoice_id, lane, c_id) or ""
                    if (c_id, lane, period) in conflict_lane_period:
                        same_conflict = True
                        break
        touched = it.id in feedback_touched
        flags_map[it.id] = ItemFlags(
            missing_doc_present=it.missing_doc is not None,
            pickup_from_tracking=pickup_tracked,
            has_same_key_conflict=same_conflict,
            all_terms_level12=True,
            all_facts_level3plus=not touched,
            recipient_from_schedule1=True,
        )
    return flags_map


def _build_mailbox(state_dir: str, facts: list[dict]):
    """Build a Mailbox from the state dir's documents."""
    from nova.mailbox import DocRecord
    from nova.state import StateDir
    from nova.textlayer import Mailbox

    state = StateDir(state_dir)
    docs_dir = state.documents_dir
    if not docs_dir.exists():
        # Return an empty mailbox wrapper.
        return _EmptyMailbox()

    # Build a synthetic doc_id → pages index from the saved DocRecords.
    # The mailbox needs to resolve quotes from doc_ids.
    doc_map: dict[str, list[str]] = {}
    for rec_file in docs_dir.glob("*.json"):
        try:
            d = json.loads(rec_file.read_text())
            doc_map[d["doc_id"]] = d.get("pages", [])
        except Exception:
            pass

    # Also include pages from facts (in case they carry different paths).
    return _DictMailbox(doc_map)


class _EmptyMailbox:
    def pages(self, doc_id):
        raise LookupError(doc_id)


class _DictMailbox:
    def __init__(self, doc_map: dict[str, list[str]]):
        self._map = doc_map

    def pages(self, doc_id: str):
        if doc_id not in self._map:
            raise LookupError(doc_id)
        return self._map[doc_id], False


def _make_judge(state_dir: str):
    """Return a judge function backed by the LLM client."""
    from nova.llm import LLMClient
    from nova.readers.judge import Judge

    client = LLMClient(Path(state_dir))
    judge = Judge(client)

    def _judge(question_id, context):
        # The question_id encodes the question text and the doc to consult.
        # Rules currently pass (question_id, context) where context may have 'doc' and 'pages'.
        doc_id = context.get("doc", "unknown")
        pages = context.get("pages", [""])
        question = context.get("question", question_id)
        return judge.ask(question_id, question, doc_id, pages, context)

    return _judge


def _build_report(items, as_of: str, mode: str, conf_score,
                  annotations: dict | None = None,
                  signals: dict | None = None) -> dict:
    """Convert resolved+policy Items to report JSON."""
    findings = []
    cashback = []
    expiry = []
    late_fee_risk = []
    annotations = annotations or {}

    for item in items:
        serialised = _item_to_dict(item, conf_score, signals=signals)
        ann = annotations.get(item.id) or {}
        if ann.get("learned_at"):
            serialised["learned_at"] = ann["learned_at"]
        if ann.get("supersedes"):
            serialised["supersedes"] = ann["supersedes"]
        if ann.get("retro"):
            serialised["retro"] = True
        if item.class_ in ("overcharge", "duplicate", "waived_but_billed", "late_fee_not_owed"):
            findings.append(serialised)
        elif item.class_ == "cashback":
            # Extract contract_id, period, credit_type from the key "contract/period/type"
            parts = item.id.split(":", 1)
            key_str = parts[1] if len(parts) == 2 else ""
            seg = key_str.split("/")
            s = serialised.copy()
            s["contract_id"] = seg[0] if len(seg) > 0 else ""
            s["period"] = seg[1] if len(seg) > 1 else ""
            s["credit_type"] = seg[2] if len(seg) > 2 else ""
            cashback.append(s)
        elif item.class_ == "expiry":
            parts = item.id.split(":", 1)
            s = serialised.copy()
            s["contract_id"] = parts[1] if len(parts) == 2 else ""
            expiry.append(s)
        elif item.class_ == "late_fee_risk":
            late_fee_risk.append(serialised)

    return {
        "schema_version": "1.0.0",
        "as_of": as_of,
        "mode": mode,
        "findings": findings,
        "portfolio": {
            "cashback": cashback,
            "expiry": expiry,
            "late_fee_risk": late_fee_risk,
        },
    }


def _item_to_dict(item, conf_score, signals: dict | None = None) -> dict:
    """Serialise a resolved Item to a report-schema-compatible dict."""
    sig = (signals or {}).get(item.id, {})
    d: dict = {
        "id": item.id,
        "class": item.class_,
        "verdict": item.verdict,
        "action": item.action,
        "confidence": conf_score(
            item.verdict,
            pickup_from_tracking=sig.get("pickup_from_tracking", True),
            had_reread=sig.get("had_reread", False),
            min_term_authority=sig.get("min_term_authority", 1),
            judge_used=sig.get("judge_used", False),
            inr_converted=sig.get("inr_converted", False),
        ),
        "evidence": [
            {"doc": e.doc, "page": e.page, "quote": e.quote}
            for e in item.evidence
            if e.quote  # skip evidence with no resolvable quote
        ],
        "amount_usd": item.amount_usd,
        "amount_range": item.amount_range,
        "deadline": item.deadline,
        "missing_doc": item.missing_doc,
        "supersedes": [],
        "learned_at": None,
    }
    if item.invoice_id:
        d["invoice_id"] = item.invoice_id
    return d


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------

def feedback(feedback_file: str, state_dir: str) -> None:
    from nova.state import StateDir

    state = StateDir(state_dir)
    state.root.mkdir(parents=True, exist_ok=True)

    payload = json.loads(Path(feedback_file).read_text())
    # Store feedback with its envelope (audit M11) so load_feedback can
    # read after_batch and decided_at from the right place, and
    # learned_at.batch is always a string.
    state.append_feedback(payload)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness.py", description="Freight invoice audit harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest", help="read one batch folder into the state dir")
    p.add_argument("batch_dir")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    p.add_argument("--estimate", action="store_true",
                   help="print token estimate for unread docs and exit (no API calls)")
    p = sub.add_parser("report", help="print report.json for a date")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD; only documents received by then count")
    p.add_argument("--mode", choices=["supervised", "autonomous"], default="supervised")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    p = sub.add_parser("feedback", help="take in a person's decisions (feedback.json)")
    p.add_argument("feedback_file")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "ingest":
            ingest(a.batch_dir, a.state_dir, estimate=getattr(a, "estimate", False))
        elif a.cmd == "report":
            json.dump(report(a.as_of, a.mode, a.state_dir), sys.stdout, indent=1)
            sys.stdout.write("\n")
        else:
            feedback(a.feedback_file, a.state_dir)
    except NotImplementedError as e:
        print(f"harness.py {a.cmd}: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
