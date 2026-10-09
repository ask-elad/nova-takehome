"""Compare reader-produced facts with hand-written fixtures on the eight examples.

For each example:

1. Load the fixture (``harness/tests/fixtures/examples/<ex>/facts.json``).
2. For every fixture record, run the matching reader on the real document
   (``data/examples/<ex>/docs``) using the shared LLM client (cache-backed).
3. Compare the reader's output dict against the fixture dict field by field
   and print a per-example summary.
4. Build a Case from the reader facts and run the rules; compare the findings
   with ``data/examples/<ex>/expected_finding.json``.

Usage:
    python harness/scripts/compare_readers.py <state_dir> [--example overcharge]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness"))

from nova.case import Case
from nova.llm import LLMClient
from nova.mailbox import DocRecord, load_batch
from nova.readers import billing as billing_reader
from nova.readers import contract as contract_reader
from nova.readers import email_doc as email_reader
from nova.readers import sheet as sheet_reader
from nova.readers import shipment as shipment_reader
from nova.resolve import resolve as resolve_items
from nova.rules.cashback import run as run_cashback
from nova.rules.duplicate import run as run_duplicate
from nova.rules.expiry import run as run_expiry
from nova.rules.late_fees import run as run_late_fees
from nova.rules.overcharge import run as run_overcharge
from nova.rules.waived_but_billed import run as run_waived
from nova.textlayer import Mailbox

EXAMPLES = [
    "overcharge",
    "conflict",
    "duplicate",
    "duplicate_rebilled_4_months",
    "waived_but_billed",
    "late_fees",
    "cashback",
    "expiry",
]

READERS = {
    "ContractTerms": contract_reader,
    "BillingDoc": billing_reader,
    "EmailFacts": email_reader,
    "SheetMap": sheet_reader,
    "ShipmentDoc": shipment_reader,
}


# ---------------------------------------------------------------------------
# Dict comparison
# ---------------------------------------------------------------------------

def _normalise(v: Any) -> Any:
    """Compare numeric strings as decimals; treat None and "" and missing lists the same."""
    if isinstance(v, str):
        try:
            d = Decimal(v)
            return ("num", d)
        except Exception:
            return ("str", v.strip().lower())
    return v


def _is_leaf(v: Any) -> bool:
    return not isinstance(v, (dict, list))


def _walk_leaves(obj: Any, path: str = ""):
    """Yield (path, value) for every leaf."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def compare_dicts(expected: dict, got: dict, ignore_prefixes: tuple[str, ...] = ("", )) -> dict:
    """Return {matched, total, mismatches:[(path, expected, got)], missing:[path], extra:[path]}."""
    exp_leaves = dict(_walk_leaves(expected))
    got_leaves = dict(_walk_leaves(got))
    matched = 0
    mismatches = []
    missing = []
    for path, ev in exp_leaves.items():
        if path in got_leaves:
            gv = got_leaves[path]
            if _normalise(ev) == _normalise(gv):
                matched += 1
            else:
                mismatches.append((path, ev, gv))
        else:
            missing.append(path)
    extra = [p for p in got_leaves if p not in exp_leaves]
    return {
        "matched": matched,
        "total": len(exp_leaves),
        "mismatches": mismatches,
        "missing": missing,
        "extra": extra,
    }


# ---------------------------------------------------------------------------
# Running the readers on one example
# ---------------------------------------------------------------------------

def _records_by_doc(docs_root: Path) -> dict[str, DocRecord]:
    out: dict[str, DocRecord] = {}
    for batch in sorted(docs_root.iterdir()):
        if batch.is_dir():
            for r in load_batch(batch):
                out[r.doc_id] = r
    return out


def _run_reader(client: LLMClient, fixture_type: str, record: DocRecord):
    reader = READERS[fixture_type]
    return reader.read(client, record)


def _run_rules_on_facts(mailbox: Mailbox, reader_facts: list[dict], as_of: str):
    case = Case.from_records(reader_facts, as_of=as_of, mailbox=mailbox)
    cands = []
    cands.extend(run_overcharge(case))
    cands.extend(run_duplicate(case))
    cands.extend(run_waived(case))
    cands.extend(run_late_fees(case))
    cands.extend(run_cashback(case))
    cands.extend(run_expiry(case))
    return resolve_items(cands, mailbox)


def compare_example(client: LLMClient, example: str) -> dict:
    docs_root = REPO / "data" / "examples" / example / "docs"
    fixture_path = REPO / "harness" / "tests" / "fixtures" / "examples" / example / "facts.json"
    expected_path = REPO / "data" / "examples" / example / "expected_finding.json"
    fixture = json.loads(fixture_path.read_text())
    expected = json.loads(expected_path.read_text())
    mailbox = Mailbox(docs_root)
    records = _records_by_doc(docs_root)

    reader_facts: list[dict] = []
    per_type_stats: dict[str, dict] = defaultdict(lambda: {"matched": 0, "total": 0, "mismatches": 0, "docs": 0})
    per_doc_rows = []
    for entry in fixture:
        typ = entry["type"]
        doc = entry["doc"]
        rec = records.get(doc)
        if rec is None:
            per_doc_rows.append((typ, doc, "doc-not-found", 0, 0))
            continue
        if typ not in READERS:
            # ShipmentDoc etc.—if a reader missing, skip
            per_doc_rows.append((typ, doc, "no-reader", 0, 0))
            continue
        result = _run_reader(client, typ, rec)
        cmp = compare_dicts(entry["data"], result.data)
        per_doc_rows.append((typ, doc, result.tier_used + ("*" if result.reread else ""),
                             cmp["matched"], cmp["total"]))
        ts = per_type_stats[typ]
        ts["matched"] += cmp["matched"]
        ts["total"] += cmp["total"]
        ts["mismatches"] += len(cmp["mismatches"])
        ts["docs"] += 1
        # Preserve received_at from the fixture so the as_of filter works.
        reader_fact = {
            "type": typ,
            "doc": doc,
            "data": result.data,
        }
        if "received_at" in entry:
            reader_fact["received_at"] = entry["received_at"]
        reader_facts.append(reader_fact)

    # Rules on reader facts
    items = _run_rules_on_facts(mailbox, reader_facts, as_of=expected["as_of"])
    exp_findings = {f["id"]: f for f in expected.get("findings", [])}
    exp_portfolio_ids = set()
    for cat in expected.get("portfolio", {}).values():
        for p in cat:
            exp_portfolio_ids.add(p["id"])

    got_by_id = {it.id: it for it in items}
    rule_rows: list[tuple[str, str, str]] = []
    for fid, ef in exp_findings.items():
        it = got_by_id.get(fid)
        if ef["verdict"] == "no_finding":
            # Decoy: we don't emit no_finding items. OK iff it isn't in got.
            if it is None:
                rule_rows.append((fid, "OK", "no_finding (absent)"))
            else:
                rule_rows.append((fid, "VERDICT", f"got {it.verdict}, expected no_finding"))
            continue
        if it is None:
            rule_rows.append((fid, "MISS", f"expected {ef['verdict']}"))
            continue
        if it.verdict != ef["verdict"]:
            rule_rows.append((fid, "VERDICT", f"got {it.verdict}, expected {ef['verdict']}"))
            continue
        if ef["verdict"] == "finding":
            if ef.get("amount_usd") is not None and it.amount_usd is not None:
                if Decimal(it.amount_usd) == Decimal(ef["amount_usd"]):
                    rule_rows.append((fid, "OK", f"${it.amount_usd}"))
                else:
                    rule_rows.append((fid, "AMOUNT", f"${it.amount_usd} vs ${ef['amount_usd']}"))
            else:
                rule_rows.append((fid, "OK", it.verdict))
        else:
            rule_rows.append((fid, "OK", it.verdict))
    for pid in exp_portfolio_ids:
        it = got_by_id.get(pid)
        rule_rows.append((pid, "OK" if it is not None else "MISS", "portfolio"))

    return {
        "example": example,
        "per_doc_rows": per_doc_rows,
        "per_type_stats": dict(per_type_stats),
        "rule_rows": rule_rows,
    }


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def print_example(res: dict) -> None:
    ex = res["example"]
    print(f"\n=== {ex} ===")
    print(f"  {'type':15}  {'doc':70}  {'tier':6}  {'matched':>8}")
    for typ, doc, tier, matched, total in res["per_doc_rows"]:
        pct = f"{matched}/{total}" if total else "-"
        print(f"  {typ:15}  {doc[:70]:70}  {tier:6}  {pct:>8}")
    print(f"  per-type totals:")
    for typ, s in sorted(res["per_type_stats"].items()):
        pct = f"{s['matched']}/{s['total']}" if s["total"] else "-"
        print(f"    {typ:15}  docs={s['docs']}  fields_matched={pct}  mismatches={s['mismatches']}")
    print(f"  rules on reader facts:")
    for fid, status, note in res["rule_rows"]:
        print(f"    {status:7}  {fid:50}  {note}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("state_dir", help="state directory for the LLM cache / ledger")
    ap.add_argument("--example", action="append", default=None,
                    help="run on this example only (repeat to run several)")
    args = ap.parse_args()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    client = LLMClient(state_dir)
    examples = args.example or EXAMPLES

    overall_matched = 0
    overall_total = 0
    overall_rules_ok = 0
    overall_rules_total = 0
    for ex in examples:
        res = compare_example(client, ex)
        print_example(res)
        for s in res["per_type_stats"].values():
            overall_matched += s["matched"]
            overall_total += s["total"]
        for _, status, _ in res["rule_rows"]:
            overall_rules_total += 1
            if status == "OK":
                overall_rules_ok += 1

    print(f"\n=== OVERALL ===")
    print(f"  reader fields matched: {overall_matched}/{overall_total}")
    print(f"  rules reproduced:      {overall_rules_ok}/{overall_rules_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
