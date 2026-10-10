"""report output must validate against grader/schema/report.schema.json."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "harness" / "harness.py"
SCHEMA_FILE = REPO / "grader" / "schema" / "report.schema.json"


def _run_harness(args: list[str], *, state_dir: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(HARNESS)] + args + ["--state-dir", str(state_dir)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_report_validates_against_schema(tmp_path):
    import jsonschema

    schema = json.loads(SCHEMA_FILE.read_text())

    result = _run_harness(["report", "--as-of", "2030-01-01", "--mode", "supervised"], state_dir=tmp_path)
    assert result.returncode == 0, f"report failed: {result.stderr}"

    report = json.loads(result.stdout)
    jsonschema.validate(report, schema)


def test_report_autonomous_mode_validates(tmp_path):
    import jsonschema

    schema = json.loads(SCHEMA_FILE.read_text())

    result = _run_harness(["report", "--as-of", "2030-01-01", "--mode", "autonomous"], state_dir=tmp_path)
    assert result.returncode == 0, f"report failed: {result.stderr}"

    report = json.loads(result.stdout)
    jsonschema.validate(report, schema)


def test_ingest_then_report_no_duplicates(tmp_path):
    """Re-ingesting the same batch must not create duplicate document records."""
    sys.path.insert(0, str(REPO / "harness"))
    from nova.state import StateDir
    from nova.mailbox import load_batch

    batch_src = REPO / "data" / "examples" / "cashback" / "docs" / "batch_01"
    if not batch_src.is_dir():
        pytest.skip("cashback example not found")

    import shutil
    batch_dir = tmp_path / "batch_01"
    shutil.copytree(batch_src, batch_dir)

    state_dir = tmp_path / "state"

    _run_harness(["ingest", str(batch_dir)], state_dir=state_dir)
    _run_harness(["ingest", str(batch_dir)], state_dir=state_dir)

    state = StateDir(state_dir)
    docs = state.load_docs()
    doc_ids = [d.doc_id for d in docs]
    assert len(doc_ids) == len(set(doc_ids)), f"duplicate doc ids: {doc_ids}"


def test_feedback_stored(tmp_path):
    """feedback command appends items to feedback.jsonl."""
    import json as _json

    feedback_payload = {
        "schema_version": "1.0",
        "world": "W1",
        "after_batch": "batch_01",
        "decided_at": "2030-01-01T00:00:00Z",
        "decided_by": {"name": "A", "role": "B", "entity": "C"},
        "items": [
            {"item_id": "fb-01", "finding_key": {"invoice_id": "INV-1", "class": "overcharge"}, "solicited": False,
             "decision": "close", "fact": {"type": "rate_accepted", "subject": {}, "value": {}}}
        ]
    }
    feedback_file = tmp_path / "feedback.json"
    feedback_file.write_text(_json.dumps(feedback_payload))

    state_dir = tmp_path / "state"
    result = _run_harness(["feedback", str(feedback_file)], state_dir=state_dir)
    assert result.returncode == 0, f"feedback failed: {result.stderr}"

    fb_jsonl = state_dir / "feedback.jsonl"
    assert fb_jsonl.exists()
    lines = fb_jsonl.read_text().strip().splitlines()
    assert len(lines) == 1
    stored = _json.loads(lines[0])
    # audit M11: feedback is stored with its envelope (after_batch,
    # decided_at), so load_feedback can source batch/decided_at from the
    # right field.
    assert stored["after_batch"] == "batch_01"
    assert stored["items"][0]["item_id"] == "fb-01"
