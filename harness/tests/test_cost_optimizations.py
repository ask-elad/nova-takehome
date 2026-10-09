"""Tests for cost-optimisation changes (offline, fake client).

1. classify sends only the first 40 lines of a document.
2. sheet reader sends only the header row + first 3 data rows (4 lines).
3. billing reader starts on fast tier; escalates to main only on verify failure.
4. Prompt caching: _real_invoke attaches cache_control to system and tool definition.
5. Ledger records cache_read_input_tokens and cache_creation_input_tokens.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness"))

from nova.llm import LLMClient, fake_set_response, fake_reset
from nova.mailbox import DocRecord, render_pages
from nova.readers import billing as billing_reader
from nova.readers import classify as classify_reader
from nova.readers import sheet as sheet_reader


@pytest.fixture(autouse=True)
def _fake_env(monkeypatch):
    monkeypatch.setenv("NOVA_LLM", "fake")
    monkeypatch.setenv("NOVA_MODEL_FAST", "fake-fast")
    monkeypatch.setenv("NOVA_MODEL_MAIN", "fake-main")
    monkeypatch.setenv("NOVA_MODEL_STRONG", "fake-strong")
    fake_reset()
    yield
    fake_reset()


def _record(pages, doc_id="batch_01/0001.eml#DOC.pdf", ext="pdf"):
    return DocRecord(
        doc_id=doc_id,
        received=datetime(2032, 1, 1, tzinfo=timezone.utc),
        sender_addr="x@y.example",
        sender_name="X",
        subject="subj",
        pages=pages,
        is_scan=False,
        parent_id="batch_01/0001.eml",
        ext=ext,
    )


def _many_line_page(n: int) -> str:
    return "\n".join(f"Line {i+1}: some content here" for i in range(n))


# ---------------------------------------------------------------------------
# 1. Classify sends at most 40 lines
# ---------------------------------------------------------------------------

def test_classify_truncates_to_40_lines(tmp_path):
    """The classify reader must include at most 40 lines in the user message."""
    captured_messages = []

    def _spy_invoke(model, schema):
        return {"kind": "invoice", "reason": "has charges"}, 10, 5

    client = LLMClient(tmp_path)
    client._fake = True

    original_fake_invoke = client._fake_invoke.__func__

    def _intercepting_fake_invoke(self, model, schema):
        # Just record — the call happens via _call_model → _invoke → _fake_invoke
        return {"kind": "invoice", "reason": "has charges"}, 10, 5

    # Patch _call_model to capture the messages passed to it
    original_call_model = client._call_model

    captured = {}

    def _capturing_call_model(model, purpose, messages, schema, pv, system, max_tokens):
        captured["messages"] = messages
        return original_call_model(model, purpose, messages, schema, pv, system, max_tokens)

    fake_set_response("*", {"kind": "invoice", "reason": "has charges"})

    # Build a record with 100 lines of content
    page = _many_line_page(100)
    rec = _record([page])

    with patch.object(client, "_call_model", side_effect=_capturing_call_model):
        classify_reader.read(client, rec)

    # Verify the user message content was limited
    assert "messages" in captured
    user_content = captured["messages"][0]["content"]
    # Count the labelled lines ([p1 LN] prefix)
    rendered_lines = [l for l in user_content.split("\n") if l.startswith("[p1")]
    assert len(rendered_lines) <= 40, (
        f"classify sent {len(rendered_lines)} lines (expected ≤ 40)"
    )


def test_classify_full_short_doc_unchanged(tmp_path):
    """A document with fewer than 40 lines is not truncated."""
    fake_set_response("*", {"kind": "email", "reason": "email body"})
    client = LLMClient(tmp_path)

    captured = {}
    original_call = client._call_model

    def _cap(model, purpose, messages, schema, pv, system, max_tokens):
        captured["messages"] = messages
        return original_call(model, purpose, messages, schema, pv, system, max_tokens)

    rec = _record([_many_line_page(20)])
    with patch.object(client, "_call_model", side_effect=_cap):
        classify_reader.read(client, rec)

    lines = [l for l in captured["messages"][0]["content"].split("\n") if l.startswith("[p1")]
    assert len(lines) == 20, f"Short doc: expected 20 lines, got {len(lines)}"


# ---------------------------------------------------------------------------
# 2. Sheet reader sends at most 4 lines (header + 3 data rows)
# ---------------------------------------------------------------------------

def test_sheet_reader_truncates_to_4_lines(tmp_path):
    """Sheet reader must include at most 4 lines of the spreadsheet."""
    # 50-row spreadsheet
    header = "AWB | Event | Date | Station | Reason code"
    data_rows = "\n".join(f"TX{i:08d} | PICKED_UP | 2032-01-0{i%9+1} | USS1 | -" for i in range(50))
    page = header + "\n" + data_rows

    fake_set_response("*", {
        "kind": "tracking_export",
        "sheet_number": 1,
        "columns": {"awb": "AWB", "event": "Event", "date": "Date"},
        "ref": {"page": 1, "line": 1},
    })
    client = LLMClient(tmp_path)

    captured = {}
    original_call = client._call_model

    def _cap(model, purpose, messages, schema, pv, system, max_tokens):
        captured["messages"] = messages
        return original_call(model, purpose, messages, schema, pv, system, max_tokens)

    rec = _record([page])
    with patch.object(client, "_call_model", side_effect=_cap):
        sheet_reader.read(client, rec)

    lines = [l for l in captured["messages"][0]["content"].split("\n") if l.startswith("[p1")]
    assert len(lines) <= 4, f"Sheet reader sent {len(lines)} lines (expected ≤ 4)"


# ---------------------------------------------------------------------------
# 3. Billing starts on fast tier; escalates to main on verify failure
# ---------------------------------------------------------------------------

def test_billing_starts_on_fast_tier(tmp_path):
    """billing reader must use fast tier for its first attempt."""
    inv_page = (
        "TX-US-2032-5394\n"
        "Tarrowby Express Inc.\n"
        "USD\n"
        "2032-04-01\n"
        "100.00\n"
    )
    fake_set_response("fake-fast", {
        "id": {"value": "TX-US-2032-5394", "ref": {"page": 1, "line": 1}},
        "kind": "invoice",
        "issuer": {"value": "Tarrowby Express Inc.", "ref": {"page": 1, "line": 2}},
        "currency": {"value": "USD", "ref": {"page": 1, "line": 3}},
        "total": {"value": "100.00", "ref": {"page": 1, "line": 5}},
        "lines": [],
    })
    client = LLMClient(tmp_path)
    rec = _record([inv_page])
    result = billing_reader.read(client, rec)

    assert result.instance is not None
    assert result.tier_used == "fast"
    assert result.reread is False

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert entries[0]["model"] == "fake-fast"


def test_billing_escalates_to_main_on_verify_failure(tmp_path):
    """billing reader escalates to main when fast-tier result fails verification."""
    inv_page = "TX-US-2032-5394\nTarrowby Express Inc.\nUSD\n2032-04-01\n100.00\n"
    # fast returns a wrong value (not on cited line)
    fake_set_response("fake-fast", {
        "id": {"value": "WRONG-ID", "ref": {"page": 1, "line": 1}},
        "kind": "invoice",
        "issuer": {"value": "Tarrowby Express Inc.", "ref": {"page": 1, "line": 2}},
        "currency": {"value": "USD", "ref": {"page": 1, "line": 3}},
        "total": {"value": "100.00", "ref": {"page": 1, "line": 5}},
        "lines": [],
    })
    # main returns the correct value
    fake_set_response("fake-main", {
        "id": {"value": "TX-US-2032-5394", "ref": {"page": 1, "line": 1}},
        "kind": "invoice",
        "issuer": {"value": "Tarrowby Express Inc.", "ref": {"page": 1, "line": 2}},
        "currency": {"value": "USD", "ref": {"page": 1, "line": 3}},
        "total": {"value": "100.00", "ref": {"page": 1, "line": 5}},
        "lines": [],
    })
    client = LLMClient(tmp_path)
    rec = _record([inv_page])
    result = billing_reader.read(client, rec)

    assert result.reread is True
    assert result.tier_used == "main"
    assert result.verify_failures == []

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert entries[0]["model"] == "fake-fast"
    assert entries[1]["model"] == "fake-main"


# ---------------------------------------------------------------------------
# 4. Prompt caching: _real_invoke adds cache_control to system and tool
# ---------------------------------------------------------------------------

def test_real_invoke_adds_cache_control_to_system_and_tool(tmp_path, monkeypatch):
    """_real_invoke must set cache_control on the system text and tool definition."""
    monkeypatch.delenv("NOVA_LLM", raising=False)  # use real path

    captured_kwargs = {}

    class _Block:
        type = "tool_use"
        name = "output"
        input = {"kind": "awb", "awb": {"value": "X", "ref": {"page": 1, "line": 1}}}

    class _FakeResp:
        stop_reason = "tool_use"
        content = [_Block()]
        usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=20,
            cache_creation_input_tokens=10,
        )

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = lambda **kw: (_capture(kw) or _FakeResp())

    def _capture(kw):
        captured_kwargs.update(kw)

    from nova.llm import LLMClient
    client = LLMClient(tmp_path, _client=fake_client)
    client._fake = False

    schema = {"type": "object", "properties": {}}
    client._real_invoke("claude-test", [{"role": "user", "content": "test"}],
                        schema, "System text", 256)

    # system must be a list with cache_control
    assert "system" in captured_kwargs
    sys_arg = captured_kwargs["system"]
    assert isinstance(sys_arg, list)
    assert any(b.get("cache_control", {}).get("type") == "ephemeral" for b in sys_arg), (
        "system must have cache_control={type:ephemeral}"
    )

    # tool definition must have cache_control
    tools = captured_kwargs.get("tools", [])
    assert len(tools) == 1
    assert tools[0].get("cache_control", {}).get("type") == "ephemeral", (
        "tool definition must have cache_control={type:ephemeral}"
    )


def test_real_invoke_no_cache_control_when_no_system(tmp_path, monkeypatch):
    """When system is empty, no system field is added (or it's the plain string)."""
    monkeypatch.delenv("NOVA_LLM", raising=False)

    captured_kwargs = {}

    class _Block2:
        type = "tool_use"
        name = "output"
        input = {}

    class _FakeResp:
        stop_reason = "tool_use"
        content = [_Block2()]
        usage = MagicMock(input_tokens=10, output_tokens=5,
                          cache_read_input_tokens=0, cache_creation_input_tokens=0)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = lambda **kw: (captured_kwargs.update(kw) or _FakeResp())

    client = LLMClient(tmp_path, _client=fake_client)
    client._fake = False

    schema = {"type": "object", "properties": {}}
    client._real_invoke("claude-test", [{"role": "user", "content": "q"}],
                        schema, "", 256)

    # No system kwarg when system text is empty
    assert "system" not in captured_kwargs or captured_kwargs.get("system") == []


# ---------------------------------------------------------------------------
# 5. Ledger records cache token fields
# ---------------------------------------------------------------------------

def test_ledger_records_cache_tokens(tmp_path, monkeypatch):
    """A paid call writes cache_read and cache_creation fields to the ledger."""
    monkeypatch.delenv("NOVA_LLM", raising=False)

    class _Block3:
        type = "tool_use"
        name = "output"
        input = {"x": 1}

    class _FakeResp:
        stop_reason = "tool_use"
        content = [_Block3()]
        usage = MagicMock(input_tokens=100, output_tokens=50,
                          cache_read_input_tokens=800, cache_creation_input_tokens=200)

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _FakeResp()

    client = LLMClient(tmp_path, _client=fake_client)
    client._fake = False

    schema = {"type": "object", "properties": {}}
    client._real_invoke("test-model", [{"role": "user", "content": "q"}],
                        schema, "sys", 256)

    # Now check the ledger (written by _call_model, not _real_invoke directly)
    # So go through _call_model instead:
    client2 = LLMClient(tmp_path, _client=fake_client)
    client2._fake = False

    client2.call("fast", "test_purpose",
                 [{"role": "user", "content": "unique_test_content_xyz"}],
                 schema, prompt_version="v1", system="sys", max_tokens=256)

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    paid = [e for e in entries if not e.get("cached")]
    assert len(paid) >= 1
    # The ledger entry should have cache token fields
    last = paid[-1]
    assert "cache_read_tokens" in last, "ledger must record cache_read_tokens"
    assert "cache_creation_tokens" in last, "ledger must record cache_creation_tokens"
