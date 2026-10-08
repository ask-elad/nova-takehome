"""LLM client: cache, ledger, and tier fallback using the fake client."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness"))

import nova.llm as llm_mod
from nova.llm import LLMClient, fake_set_response, fake_set_fail, fake_reset


@pytest.fixture(autouse=True)
def _fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_LLM", "fake")
    monkeypatch.setenv("NOVA_MODEL_FAST", "fake-fast")
    monkeypatch.setenv("NOVA_MODEL_MAIN", "fake-main")
    monkeypatch.setenv("NOVA_MODEL_STRONG", "fake-strong")
    fake_reset()
    yield
    fake_reset()


_SCHEMA = {"type": "object", "properties": {"value": {"type": "string"}}}
_MESSAGES = [{"role": "user", "content": "hello"}]


def test_second_call_served_from_cache(tmp_path):
    fake_set_response("*", {"value": "ok"})
    client = LLMClient(tmp_path)

    r1 = client.call("fast", "test", _MESSAGES, _SCHEMA)
    r2 = client.call("fast", "test", _MESSAGES, _SCHEMA)

    assert r1 == r2 == {"value": "ok"}

    # both calls must appear in the ledger
    ledger_lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
    assert len(ledger_lines) == 2
    entries = [json.loads(l) for l in ledger_lines]
    assert entries[0]["cached"] is False
    assert entries[1]["cached"] is True


def test_both_calls_in_ledger(tmp_path):
    fake_set_response("*", {"x": 1})
    client = LLMClient(tmp_path)
    client.call("main", "purpose-a", _MESSAGES, _SCHEMA)
    client.call("main", "purpose-a", _MESSAGES, _SCHEMA)

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(entries) == 2
    assert all("time" in e and "model" in e and "purpose" in e for e in entries)


def test_fallback_to_next_model_on_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_MODEL_FAST", "model-missing")
    monkeypatch.setenv("NOVA_MODEL_MAIN", "fake-main")
    fake_set_fail("model-missing")
    fake_set_response("fake-main", {"fell_back": True})

    client = LLMClient(tmp_path)
    result = client.call("fast", "fallback-test", _MESSAGES, _SCHEMA)

    assert result == {"fell_back": True}

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["model"] == "fake-main"


def test_cache_isolated_by_model(tmp_path, monkeypatch):
    fake_set_response("fake-fast", {"tier": "fast"})
    fake_set_response("fake-main", {"tier": "main"})
    client = LLMClient(tmp_path)

    r_fast = client.call("fast", "t", _MESSAGES, _SCHEMA)
    r_main = client.call("main", "t", _MESSAGES, _SCHEMA)

    assert r_fast == {"tier": "fast"}
    assert r_main == {"tier": "main"}
