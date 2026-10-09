"""as_of filtering: a record received after as_of changes nothing."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from nova.case import Case
from nova.resolve import resolve
from nova.rules.overcharge import run as run_overcharge
from nova.textlayer import Mailbox


EXAMPLE = "overcharge"
EXAMPLES_DIR = Path("data/examples") / EXAMPLE
FIXTURES_DIR = Path("harness/tests/fixtures/examples") / EXAMPLE


def test_late_received_doc_is_dropped():
    base = json.loads((FIXTURES_DIR / "facts.json").read_text())
    mb = Mailbox(EXAMPLES_DIR / "docs")
    expected = json.loads((EXAMPLES_DIR / "expected_finding.json").read_text())
    as_of = expected["as_of"]

    case_base = Case.from_records(base, as_of=as_of, mailbox=mb)
    items_base = resolve(run_overcharge(case_base), mb)

    # Add a decoy duplicate of the contract that would (if seen) still parse,
    # but with a received_at after as_of so it must be filtered out.
    decoy = copy.deepcopy(next(e for e in base if e["type"] == "ContractTerms"))
    decoy["received_at"] = "2099-12-31"
    decoy["doc"] = decoy["doc"] + "#decoy"

    case_late = Case.from_records(base + [decoy], as_of=as_of, mailbox=mb)
    assert len(case_late.contracts) == len(case_base.contracts), (
        "doc received after as_of should be dropped"
    )
    items_late = resolve(run_overcharge(case_late), mb)

    assert [(it.id, it.amount_usd) for it in items_late] == [
        (it.id, it.amount_usd) for it in items_base
    ]
