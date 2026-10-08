"""The only place that calls the Anthropic API.

Three model tiers:
  fast   NOVA_MODEL_FAST   default claude-haiku-4-5-20251001
  main   NOVA_MODEL_MAIN   default claude-sonnet-4-6
  strong NOVA_MODEL_STRONG default claude-opus-4-7

Set NOVA_LLM=fake to skip the network entirely (use fake_set_response / fake_set_fail to control
behaviour in tests).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_FAST = "claude-haiku-4-5-20251001"
_DEFAULT_MAIN = "claude-sonnet-4-6"
_DEFAULT_STRONG = "claude-opus-4-7"

_TIER_ENVS = ["NOVA_MODEL_FAST", "NOVA_MODEL_MAIN", "NOVA_MODEL_STRONG"]
_TIER_DEFAULTS = [_DEFAULT_FAST, _DEFAULT_MAIN, _DEFAULT_STRONG]
_TIER_INDEX = {"fast": 0, "main": 1, "strong": 2}

# ---- fake client state (module-level so tests can manipulate it) -----------------------------------------------
_fake_responses: dict[str, dict] = {}   # model -> response dict; "*" is wildcard
_fake_fail_models: set[str] = set()     # models that should raise "model not found"


def fake_set_response(model: str, response: dict) -> None:
    """Register a canned response for the given model (or "*" for all)."""
    _fake_responses[model] = response


def fake_set_fail(model: str) -> None:
    """Make the fake client raise 'model not found' for this model."""
    _fake_fail_models.add(model)


def fake_reset() -> None:
    """Clear all fake client state."""
    _fake_responses.clear()
    _fake_fail_models.clear()


# ---- helpers ----------------------------------------------------------------------------------------------------------

def _tier_models() -> list[str]:
    return [os.environ.get(env, default) for env, default in zip(_TIER_ENVS, _TIER_DEFAULTS)]


def _cache_key(model: str, prompt_version: str, messages: list) -> str:
    payload = json.dumps({"model": model, "v": prompt_version, "msgs": messages}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---- LLMClient --------------------------------------------------------------------------------------------------------

class LLMClient:
    """Manages model tiers, disk cache, ledger, retries, and optional fake mode."""

    def __init__(self, state_dir: Path):
        self._state = Path(state_dir)
        self._cache_dir = self._state / "cache"
        self._ledger = self._state / "ledger.jsonl"
        self._fake = os.environ.get("NOVA_LLM", "").lower() == "fake"
        if not self._fake:
            import anthropic
            self._client = anthropic.Anthropic()

    # ---- public API ---------------------------------------------------------------------------------------------------

    def call(
        self,
        tier: str,
        purpose: str,
        messages: list[dict],
        schema: dict,
        prompt_version: str = "1",
    ) -> dict:
        """Call the model at the given tier, falling back through tiers on model-not-found."""
        idx = _TIER_INDEX[tier]
        models = _tier_models()
        last_err: Exception | None = None
        for model in models[idx:]:
            try:
                return self._call_model(model, purpose, messages, schema, prompt_version)
            except Exception as e:
                msg = str(e).lower()
                if "model not found" in msg or "model_not_found" in msg:
                    last_err = e
                    continue
                raise
        raise RuntimeError(f"all models exhausted from tier '{tier}'") from last_err

    def pool(self, tasks: list[tuple], max_workers: int = 4) -> list:
        """Run [(callable, *args), ...] in a thread pool and return results in order."""
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fn, *args) for fn, *args in tasks]
            return [f.result() for f in futures]

    # ---- internals ----------------------------------------------------------------------------------------------------

    def _call_model(
        self,
        model: str,
        purpose: str,
        messages: list[dict],
        schema: dict,
        prompt_version: str,
    ) -> dict:
        key = _cache_key(model, prompt_version, messages)
        cached = self._read_cache(key)

        if cached is not None:
            self._write_ledger({
                "time": datetime.now(timezone.utc).isoformat(),
                "purpose": purpose,
                "model": model,
                "input_tokens": cached.get("input_tokens", 0),
                "output_tokens": cached.get("output_tokens", 0),
                "cached": True,
            })
            return cached["result"]

        result, input_tokens, output_tokens = self._invoke(model, messages, schema)
        self._write_cache(key, {"result": result, "input_tokens": input_tokens, "output_tokens": output_tokens})
        self._write_ledger({
            "time": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached": False,
        })
        return result

    def _invoke(self, model: str, messages: list[dict], schema: dict) -> tuple[dict, int, int]:
        if self._fake:
            return self._fake_invoke(model, schema)
        return self._real_invoke(model, messages, schema)

    def _fake_invoke(self, model: str, schema: dict) -> tuple[dict, int, int]:
        if model in _fake_fail_models:
            raise ValueError(f"model not found: {model}")
        result = _fake_responses.get(model) or _fake_responses.get("*") or {}
        return result, 10, 5

    def _real_invoke(self, model: str, messages: list[dict], schema: dict) -> tuple[dict, int, int]:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                import anthropic
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=4096,
                    temperature=0,
                    tools=[{"name": "output", "description": "Structured output", "input_schema": schema}],
                    tool_choice={"type": "tool", "name": "output"},
                    messages=messages,
                )
                for block in resp.content:
                    if block.type == "tool_use" and block.name == "output":
                        return block.input, resp.usage.input_tokens, resp.usage.output_tokens
                raise ValueError("no tool_use block in response")
            except Exception as e:
                msg = str(e).lower()
                if "model not found" in msg or "model_not_found" in msg:
                    raise
                if ("rate_limit" in msg or "overloaded" in msg or "529" in msg or "529" in msg) and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError("exceeded retry limit")

    def _read_cache(self, key: str) -> dict | None:
        p = self._cache_dir / f"{key}.json"
        try:
            return json.loads(p.read_text())
        except FileNotFoundError:
            return None

    def _write_cache(self, key: str, data: dict) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / f"{key}.json").write_text(json.dumps(data))

    def _write_ledger(self, entry: dict) -> None:
        self._state.mkdir(parents=True, exist_ok=True)
        with open(self._ledger, "a") as f:
            f.write(json.dumps(entry) + "\n")
