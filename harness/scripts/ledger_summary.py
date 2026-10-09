"""Summarise state/ledger.jsonl: calls, in/out tokens per (model, purpose), cached vs paid.

Usage:
    python harness/scripts/ledger_summary.py <state_dir>
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def summarise(state_dir: Path) -> str:
    ledger = Path(state_dir) / "ledger.jsonl"
    if not ledger.is_file():
        return f"no ledger at {ledger}"

    rows: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"calls": 0, "cached": 0, "paid": 0, "in_tok": 0, "out_tok": 0,
                 "paid_in_tok": 0, "paid_out_tok": 0}
    )
    totals = {"calls": 0, "cached": 0, "paid": 0, "in_tok": 0, "out_tok": 0,
              "paid_in_tok": 0, "paid_out_tok": 0}
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        key = (e.get("model", "?"), e.get("purpose", "?"))
        row = rows[key]
        row["calls"] += 1
        totals["calls"] += 1
        in_tok = int(e.get("input_tokens", 0) or 0)
        out_tok = int(e.get("output_tokens", 0) or 0)
        row["in_tok"] += in_tok
        row["out_tok"] += out_tok
        totals["in_tok"] += in_tok
        totals["out_tok"] += out_tok
        if e.get("cached"):
            row["cached"] += 1
            totals["cached"] += 1
        else:
            row["paid"] += 1
            row["paid_in_tok"] += in_tok
            row["paid_out_tok"] += out_tok
            totals["paid"] += 1
            totals["paid_in_tok"] += in_tok
            totals["paid_out_tok"] += out_tok

    lines = [f"ledger: {ledger}"]
    hdr = f"{'model':30}  {'purpose':20}  {'calls':>6}  {'cached':>6}  {'paid':>5}  {'in':>8}  {'out':>8}  {'paid_in':>8}  {'paid_out':>8}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for (model, purpose), row in sorted(rows.items()):
        lines.append(
            f"{model[:30]:30}  {purpose[:20]:20}  {row['calls']:>6}  {row['cached']:>6}  "
            f"{row['paid']:>5}  {row['in_tok']:>8}  {row['out_tok']:>8}  "
            f"{row['paid_in_tok']:>8}  {row['paid_out_tok']:>8}"
        )
    lines.append("-" * len(hdr))
    lines.append(
        f"{'TOTAL':30}  {'':20}  {totals['calls']:>6}  {totals['cached']:>6}  "
        f"{totals['paid']:>5}  {totals['in_tok']:>8}  {totals['out_tok']:>8}  "
        f"{totals['paid_in_tok']:>8}  {totals['paid_out_tok']:>8}"
    )
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ledger_summary.py <state_dir>", file=sys.stderr)
        return 2
    print(summarise(Path(sys.argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
