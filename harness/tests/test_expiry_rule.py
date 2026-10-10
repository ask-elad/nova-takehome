"""Unit tests for the expiry rule (glossary §Expiry)."""
from __future__ import annotations

from nova.case import Case
from nova.rules.expiry import operative_date, run as run_expiry


CONTRACT_DOC = "batch_01/0001.eml#MSA.pdf"


def _msa(end_date: str, auto_renewal: bool = False, notice_days: int | None = None) -> dict:
    data = {
        "id": {"value": "C1", "ref": {"page": 1, "line": 1}},
        "kind": "msa", "parties": ["A", "B"],
        "dated": {"value": "2030-01-01", "ref": {"page": 1, "line": 1}},
        "effective_from": {"value": "2030-01-01", "ref": {"page": 1, "line": 1}},
        "end_date": {"value": end_date, "ref": {"page": 3, "line": 21}},
        "auto_renewal": auto_renewal,
        "rate_periods": [], "rate_rows": [],
        "payment_due_days": {"value": "45", "ref": {"page": 3, "line": 1}},
        "payment_grace_days": {"value": "0", "ref": {"page": 3, "line": 1}},
        "late_fee_rate": {"value": "1.0", "ref": {"page": 3, "line": 1}},
        "late_fee_compounding": False,
        "schedule1_rows": [],
    }
    if auto_renewal and notice_days is not None:
        data["renewal_notice_days"] = notice_days
        data["renewal_notice_ref"] = {"page": 3, "line": 22}
    return {"type": "ContractTerms", "doc": CONTRACT_DOC, "data": data}


def _run(as_of: str, msa: dict):
    return run_expiry(Case.from_records([msa], as_of=as_of))


def test_zero_days_is_a_finding():
    cands = _run("2034-03-20", _msa("2034-03-20"))
    assert len(cands) == 1
    assert cands[0].deadline == "2034-03-20"


def test_60_days_is_a_finding():
    cands = _run("2034-01-19", _msa("2034-03-20"))
    assert len(cands) == 1


def test_61_days_is_no_finding():
    cands = _run("2034-01-18", _msa("2034-03-20"))
    assert cands == []


def test_auto_renewal_shifts_operative_date():
    # end 2034-03-20, notice 30 days → operative 2034-02-18.
    msa = _msa("2034-03-20", auto_renewal=True, notice_days=30)
    assert operative_date_of(msa) == "2034-02-18"
    cands = _run("2034-02-18", msa)
    assert len(cands) == 1
    assert cands[0].deadline == "2034-02-18"


def operative_date_of(record: dict):
    c = Case.from_records([record], as_of="2000-01-01")
    return operative_date(c.contracts[0])


def test_auto_renewal_boundary_61_days_before_operative_is_no_finding():
    msa = _msa("2034-03-20", auto_renewal=True, notice_days=30)
    # operative 2034-02-18; 61 days before is 2033-12-19.
    cands = _run("2033-12-19", msa)
    assert cands == []


def _amendment(amends: str, effective_from: str, new_end: str) -> dict:
    data = {
        "id": {"value": "C1-AMD1", "ref": {"page": 1, "line": 1}},
        "kind": "amendment",
        "amends": {"value": amends, "ref": {"page": 1, "line": 1}},
        "parties": ["A", "B"],
        "dated": {"value": effective_from, "ref": {"page": 1, "line": 1}},
        "effective_from": {"value": effective_from, "ref": {"page": 1, "line": 1}},
        "end_date": {"value": new_end, "ref": {"page": 1, "line": 7}},
        "auto_renewal": False,
        "rate_periods": [], "rate_rows": [],
        "payment_due_days": {"value": "45", "ref": {"page": 1, "line": 1}},
        "payment_grace_days": {"value": "0", "ref": {"page": 1, "line": 1}},
        "late_fee_rate": {"value": "1.0", "ref": {"page": 1, "line": 1}},
        "late_fee_compounding": False,
        "schedule1_rows": [],
    }
    return {"type": "ContractTerms",
            "doc": "batch_02/0003.eml#AMD1.pdf", "data": data}


def test_signed_amendment_extends_end_and_removes_alert():
    """A signed amendment extending the end date past the 60-day window
    takes the expiry alert away (audit B5)."""
    msa = _msa("2034-03-20")
    amd = _amendment("C1", effective_from="2034-01-10", new_end="2035-03-20")
    case = Case.from_records([msa, amd], as_of="2034-02-01")
    assert run_expiry(case) == []


def test_signed_amendment_moves_deadline_within_window():
    msa = _msa("2034-03-20")
    # Amendment that moves end earlier, still inside 60-day window.
    amd = _amendment("C1", effective_from="2034-01-10", new_end="2034-02-15")
    case = Case.from_records([msa, amd], as_of="2034-01-20")
    cands = run_expiry(case)
    assert len(cands) == 1
    assert cands[0].deadline == "2034-02-15"
