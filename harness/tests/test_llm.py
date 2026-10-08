"""LLM client: cache, ledger, tier fallback, retries, truncation, and thread safety."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness"))

import nova.llm as llm_mod
from nova.llm import LLMClient, fake_set_response, fake_reset, TruncatedOutput


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


def test_cache_isolated_by_model(tmp_path, monkeypatch):
    fake_set_response("fake-fast", {"tier": "fast"})
    fake_set_response("fake-main", {"tier": "main"})
    client = LLMClient(tmp_path)

    r_fast = client.call("fast", "t", _MESSAGES, _SCHEMA)
    r_main = client.call("main", "t", _MESSAGES, _SCHEMA)

    assert r_fast == {"tier": "fast"}
    assert r_main == {"tier": "main"}


# ---- real-SDK fallback test (no network) -----------------------------------------------------------------------

def test_real_sdk_fallback_on_not_found(tmp_path, monkeypatch):
    """NotFoundError on first model → fallback to second; ledger records the second model."""
    import httpx2
    import anthropic

    call_count = [0]

    def handler(request):
        call_count[0] += 1
        if call_count[0] == 1:
            body = json.dumps({
                "type": "error",
                "error": {"type": "not_found_error", "message": "model: model-missing"},
            }).encode()
            return httpx2.Response(404, content=body, headers={"Content-Type": "application/json"})
        body = json.dumps({
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "tu_01", "name": "output", "input": {"fell_back": True}}],
            "model": "model-fallback",
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }).encode()
        return httpx2.Response(200, content=body, headers={"Content-Type": "application/json"})

    sdk_client = anthropic.Anthropic(
        api_key="x",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )

    monkeypatch.delenv("NOVA_LLM", raising=False)
    monkeypatch.setenv("NOVA_MODEL_FAST", "model-missing,model-fallback")

    client = LLMClient(tmp_path, _client=sdk_client)
    result = client.call("fast", "fallback-test", _MESSAGES, _SCHEMA)

    assert result == {"fell_back": True}

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["model"] == "model-fallback"


def test_real_sdk_retry_on_rate_limit(tmp_path, monkeypatch):
    """A 429 is retried; the eventual 200 is returned."""
    import httpx2
    import anthropic

    call_count = [0]

    def handler(request):
        call_count[0] += 1
        if call_count[0] == 1:
            body = json.dumps({
                "type": "error",
                "error": {"type": "rate_limit_error", "message": "Rate limited"},
            }).encode()
            return httpx2.Response(429, content=body, headers={"Content-Type": "application/json"})
        body = json.dumps({
            "id": "msg_02",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "tu_02", "name": "output", "input": {"retried": True}}],
            "model": "m",
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }).encode()
        return httpx2.Response(200, content=body, headers={"Content-Type": "application/json"})

    sdk_client = anthropic.Anthropic(
        api_key="x",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )

    monkeypatch.delenv("NOVA_LLM", raising=False)
    monkeypatch.setenv("NOVA_MODEL_FAST", "m")

    # Patch sleep to avoid waiting
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _: None)

    client = LLMClient(tmp_path, _client=sdk_client)
    result = client.call("fast", "retry-test", _MESSAGES, _SCHEMA)

    assert result == {"retried": True}
    assert call_count[0] == 2


def test_real_sdk_400_raises_immediately(tmp_path, monkeypatch):
    """A 400 (bad request) is not retried; it raises right away."""
    import httpx2
    import anthropic

    call_count = [0]

    def handler(request):
        call_count[0] += 1
        body = json.dumps({
            "type": "error",
            "error": {"type": "invalid_request_error", "message": "bad input"},
        }).encode()
        return httpx2.Response(400, content=body, headers={"Content-Type": "application/json"})

    sdk_client = anthropic.Anthropic(
        api_key="x",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )

    monkeypatch.delenv("NOVA_LLM", raising=False)
    monkeypatch.setenv("NOVA_MODEL_FAST", "m")
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _: None)

    client = LLMClient(tmp_path, _client=sdk_client)
    with pytest.raises(anthropic.BadRequestError):
        client.call("fast", "bad-test", _MESSAGES, _SCHEMA)

    assert call_count[0] == 1


# ---- cache key completeness ----------------------------------------------------------------------------------

def test_different_system_misses_cache(tmp_path):
    fake_set_response("*", {"v": 1})
    client = LLMClient(tmp_path)

    client.call("fast", "t", _MESSAGES, _SCHEMA, system="sys-a")
    client.call("fast", "t", _MESSAGES, _SCHEMA, system="sys-b")

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert entries[0]["cached"] is False
    assert entries[1]["cached"] is False


def test_different_schema_misses_cache(tmp_path):
    fake_set_response("*", {"v": 1})
    client = LLMClient(tmp_path)

    schema_a = {"type": "object", "properties": {"a": {"type": "string"}}}
    schema_b = {"type": "object", "properties": {"b": {"type": "integer"}}}

    client.call("fast", "t", _MESSAGES, schema_a)
    client.call("fast", "t", _MESSAGES, schema_b)

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert entries[0]["cached"] is False
    assert entries[1]["cached"] is False


def test_different_max_tokens_misses_cache(tmp_path):
    fake_set_response("*", {"v": 1})
    client = LLMClient(tmp_path)

    client.call("fast", "t", _MESSAGES, _SCHEMA, max_tokens=100)
    client.call("fast", "t", _MESSAGES, _SCHEMA, max_tokens=200)

    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert entries[0]["cached"] is False
    assert entries[1]["cached"] is False


# ---- TruncatedOutput --------------------------------------------------------------------------------------------

def test_truncated_output_raises_and_skips_cache(tmp_path, monkeypatch):
    """stop_reason=max_tokens raises TruncatedOutput and writes no cache file."""
    import httpx2
    import anthropic

    def handler(request):
        body = json.dumps({
            "id": "msg_03",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "tu_03", "name": "output", "input": {"partial": True}}],
            "model": "m",
            "stop_reason": "max_tokens",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 4096},
        }).encode()
        return httpx2.Response(200, content=body, headers={"Content-Type": "application/json"})

    sdk_client = anthropic.Anthropic(
        api_key="x",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )

    monkeypatch.delenv("NOVA_LLM", raising=False)
    monkeypatch.setenv("NOVA_MODEL_FAST", "m")

    client = LLMClient(tmp_path, _client=sdk_client)

    with pytest.raises(TruncatedOutput):
        client.call("fast", "trunc-test", _MESSAGES, _SCHEMA)

    cache_files = list((tmp_path / "cache").glob("*.json")) if (tmp_path / "cache").exists() else []
    assert cache_files == [], "truncated output must not be cached"
