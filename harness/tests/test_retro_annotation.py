"""Unit test for the retro annotation (audit B5).

A key that only exists because of a document received after an earlier report
but dated/effective-from before that report's as_of carries retro: true.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "harness.py"
sys.path.insert(0, str(HARNESS.parent))
harness = importlib.import_module("harness")


class _Doc:
    def __init__(self, doc_id, received_iso):
        self.doc_id = doc_id
        self.received = datetime.fromisoformat(received_iso).replace(tzinfo=timezone.utc)


class _Case:
    def __init__(self):
        self.contracts = []
        self.billings = []


class _Item:
    def __init__(self, id_, evidence):
        self.id = id_
        self.evidence = evidence


class _Ev:
    def __init__(self, doc):
        self.doc = doc


def _write_prev(report_dir: Path, as_of: str) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{as_of}_supervised.json").write_text(
        '{"as_of": "%s", "findings": [], "portfolio": {"cashback": [],'
        ' "expiry": [], "late_fee_risk": []}}' % as_of
    )


class _FakeAmendment:
    def __init__(self, doc, effective_from):
        self.doc = doc
        self.effective_from = effective_from


def test_retro_marks_backdated_new_key(tmp_path):
    _write_prev(tmp_path, "2040-05-31")
    case = _Case()
    case.contracts = [_FakeAmendment(
        doc="batch_02/0003.eml#AMD.pdf", effective_from="2040-04-01")]
    docs = [_Doc("batch_02/0003.eml#AMD.pdf", "2040-06-05")]
    items = [_Item("overcharge:INV-1",
                   [_Ev("batch_02/0003.eml#AMD.pdf")])]
    annotations: dict = {}
    harness._annotate_retro(items, annotations, tmp_path, case, docs)
    assert annotations["overcharge:INV-1"].get("retro") is True


def test_retro_skips_prior_doc(tmp_path):
    _write_prev(tmp_path, "2040-05-31")
    case = _Case()
    case.contracts = [_FakeAmendment(
        doc="batch_01/0001.eml#MSA.pdf", effective_from="2040-01-01")]
    # Received BEFORE prev as_of: not retro.
    docs = [_Doc("batch_01/0001.eml#MSA.pdf", "2040-01-15")]
    items = [_Item("overcharge:INV-1",
                   [_Ev("batch_01/0001.eml#MSA.pdf")])]
    annotations: dict = {}
    harness._annotate_retro(items, annotations, tmp_path, case, docs)
    assert "retro" not in annotations.get("overcharge:INV-1", {})
