"""Tests for Case.terms_on: amendment layering, rate notices, invoice pick."""
from __future__ import annotations

import json
from pathlib import Path

from nova.case import Case


EXAMPLE_DIR = Path("harness/tests/fixtures/examples/overcharge")


def _load_case(as_of: str = "2032-08-31") -> Case:
    records = json.loads((EXAMPLE_DIR / "facts.json").read_text())
    return Case.from_records(records, as_of=as_of)


def test_terms_on_base_msa_only():
    c = _load_case()
    t = c.terms_on("TBX-US-EXP-E60", "2032-01-15")
    assert t is not None
    assert t.msa.id == "TBX-US-EXP-E60"
    for _row, src in t.rate_rows:
        assert src.kind == "msa"
        assert src.authority_level == 1
    # Precedence rank: signed_amendment should outrank msa.
    msa_rank = c._rank_for("msa", t.msa)
    amd_rank = c._rank_for("signed_amendment", t.msa)
    assert amd_rank > msa_rank


def test_terms_on_amendment_overrides_lane_band(tmp_path):
    """A signed amendment on the same (lane, band) replaces the MSA row."""
    base = json.loads((EXAMPLE_DIR / "facts.json").read_text())
    msa_entry = next(e for e in base if e["type"] == "ContractTerms")
    msa_rates = msa_entry["data"]["rate_rows"]
    target = next(r for r in msa_rates if not r["is_minimum_charge"])
    lane, band = target["lane"], target["band"]

    amendment = {
        "type": "ContractTerms",
        "doc": "batch_01/0099.eml#AMD-1.pdf",
        "received_at": "2032-02-01",
        "data": {
            "id": {"value": "TBX-US-EXP-E60-AMD-1", "ref": {"page": 1, "line": 1}},
            "kind": "amendment",
            "amends": {"value": "TBX-US-EXP-E60", "ref": {"page": 1, "line": 2}},
            "parties": msa_entry["data"]["parties"],
            "dated": {"value": "2032-02-01", "ref": {"page": 1, "line": 3}},
            "effective_from": {"value": "2032-02-15", "ref": {"page": 1, "line": 4}},
            "auto_renewal": False,
            "rate_periods": msa_entry["data"]["rate_periods"],
            "rate_rows": [
                {
                    "lane": lane,
                    "band": band,
                    "band_min_kg": target.get("band_min_kg"),
                    "band_max_kg": target.get("band_max_kg"),
                    "is_minimum_charge": False,
                    "rates": [{"period": None, "rate": "0.01"}],
                    "ref": {"page": 1, "line": 10},
                }
            ],
            "payment_due_days": {"value": "45", "ref": {"page": 1, "line": 20}},
            "payment_grace_days": {"value": "0", "ref": {"page": 1, "line": 21}},
            "late_fee_rate": {"value": "1.19", "ref": {"page": 1, "line": 22}},
            "late_fee_compounding": False,
            "schedule1_rows": [],
        },
    }
    case = Case.from_records(base + [amendment], as_of="2032-08-31")

    # Before the amendment is effective: MSA row.
    before = case.terms_on("TBX-US-EXP-E60", "2032-02-01")
    rows_before = [rs for rs in before.rate_rows if rs[0].lane == lane and rs[0].band == band]
    assert rows_before[0][1].kind == "msa"

    # On/after effective date: amendment row replaces it.
    after = case.terms_on("TBX-US-EXP-E60", "2032-02-15")
    rows_after = [rs for rs in after.rate_rows if rs[0].lane == lane and rs[0].band == band]
    assert len(rows_after) == 1
    assert rows_after[0][1].kind == "amendment"
    assert rows_after[0][0].rates[0].rate == "0.01"

    # Rows not restated still come from the MSA.
    other_rows = [rs for rs in after.rate_rows if not (rs[0].lane == lane and rs[0].band == band)]
    assert other_rows, "expected other MSA rows to fall through"
    assert any(src.kind == "msa" for _r, src in other_rows)


def test_rate_notice_requires_schedule1_rates_authority():
    """A rate notice from an unauthorised sender is not returned."""
    base = json.loads((EXAMPLE_DIR / "facts.json").read_text())
    email = {
        "type": "EmailFacts",
        "doc": "batch_01/0098.eml",
        "received_at": "2032-02-01",
        "data": {
            "kind": "rate_notice",
            "sender": {"value": "Stranger <stranger@example.com>", "ref": {"page": 1, "line": 1}},
            "own_lines": [],
            "quoted_lines": [],
            "rate_notice": {
                "effective_from": {"value": "2032-02-15", "ref": {"page": 1, "line": 5}},
                "rows": [{"lane": "USE2-INE2", "band": "0-44.5 kg", "rate": "9.99",
                          "ref": {"page": 1, "line": 6}}],
                "ref": {"page": 1, "line": 4},
            },
        },
    }
    case = Case.from_records(base + [email], as_of="2032-08-31")
    terms = case.terms_on("TBX-US-EXP-E60", "2032-03-01")
    assert terms is not None
    assert terms.rate_notices == []


def test_charge_code_resolution_via_annex_e():
    """Annex E aliases map a billed label to its code."""
    base = json.loads((EXAMPLE_DIR / "facts.json").read_text())
    msa_entry = next(e for e in base if e["type"] == "ContractTerms")
    msa_entry["data"]["charge_code_aliases"] = [
        {"code": "SEC", "label": "Security surcharge",
         "aliases": ["Screening fee"], "ref": {"page": 1, "line": 1}}
    ]
    msa_entry["data"]["accessorials"] = [
        {"code": "SEC", "label": "Security surcharge", "rate": "0.25",
         "basis": "USD per kg", "basis_kind": "per_kg", "ref": {"page": 1, "line": 2}}
    ]
    case = Case.from_records(base, as_of="2032-08-31")
    msa = case.msa_for("TBX-US-EXP-E60")
    assert case.charge_code_for_label(msa, "Security surcharge") == "SEC"
    assert case.charge_code_for_label(msa, "Screening fee") == "SEC"
    assert case.charge_code_for_label(msa, "Nope") is None
