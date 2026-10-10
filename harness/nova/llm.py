"""The only place that calls the Anthropic API.

Three model tiers, each an ordered list (newest first, older as fallbacks):
  fast   NOVA_MODEL_FAST   default claude-haiku-5-5,claude-haiku-4-5-20251001
  main   NOVA_MODEL_MAIN   default claude-sonnet-5-5,claude-sonnet-5,claude-sonnet-4-6,claude-sonnet-4-5-20250929
  strong NOVA_MODEL_STRONG default claude-opus-5-5,claude-opus-5,claude-opus-4-8,claude-opus-4-7,claude-opus-4-6,claude-opus-4-5-20251101

Env vars accept comma-separated lists. On NotFoundError the client tries the remaining models
in the tier, then the next tier up.

Set NOVA_LLM=fake to skip the network entirely (use fake_set_response to control behaviour in tests).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_FAST = "claude-haiku-5-5,claude-haiku-4-5-20251001"
_DEFAULT_MAIN = "claude-sonnet-5-5,claude-sonnet-5,claude-sonnet-4-6,claude-sonnet-4-5-20250929"
_DEFAULT_STRONG = "claude-opus-5-5,claude-opus-5,claude-opus-4-8,claude-opus-4-7,claude-opus-4-6,claude-opus-4-5-20251101"

_TIER_ENVS = ["NOVA_MODEL_FAST", "NOVA_MODEL_MAIN", "NOVA_MODEL_STRONG"]
_TIER_DEFAULTS = [_DEFAULT_FAST, _DEFAULT_MAIN, _DEFAULT_STRONG]
_TIER_INDEX = {"fast": 0, "main": 1, "strong": 2}

_RETRYABLE_TYPES = (
    "anthropic.RateLimitError",
    "anthropic.OverloadedError",
    "anthropic.InternalServerError",
    "anthropic.APIConnectionError",
    "anthropic.APITimeoutError",
)


class TruncatedOutput(Exception):
    """Raised when the model hits max_tokens before finishing its response."""


# ---- fake client state (module-level so tests can manipulate it) -----------------------------------------------
_fake_responses: dict[str, dict] = {}   # model -> response dict; "*" is wildcard


def fake_set_response(model: str, response: dict) -> None:
    """Register a canned response for the given model (or "*" for all)."""
    _fake_responses[model] = response


def fake_reset() -> None:
    """Clear all fake client state."""
    _fake_responses.clear()


# ---- helpers ----------------------------------------------------------------------------------------------------------

def _tier_models() -> list[list[str]]:
    """Return [[fast models], [main models], [strong models]] from env or defaults."""
    result = []
    for env, default in zip(_TIER_ENVS, _TIER_DEFAULTS):
        val = os.environ.get(env, default)
        result.append([m.strip() for m in val.split(",") if m.strip()])
    return result


def _cache_key(model: str, prompt_version: str, system: str, messages: list, schema: dict, max_tokens: int) -> str:
    payload = json.dumps(
        {"model": model, "v": prompt_version, "system": system, "msgs": messages, "schema": schema, "max_tokens": max_tokens},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _is_retryable(exc: Exception) -> bool:
    try:
        import anthropic
        return isinstance(exc, (
            anthropic.RateLimitError,
            anthropic.OverloadedError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ))
    except ImportError:
        return False


def _is_not_found(exc: Exception) -> bool:
    """Fall back to the next model on 404, 403 (no access to this model),
    and 400s that specifically say the model is unavailable (audit M4).
    """
    try:
        import anthropic
    except ImportError:
        return False
    if isinstance(exc, (anthropic.NotFoundError, anthropic.PermissionDeniedError)):
        return True
    if isinstance(exc, anthropic.BadRequestError):
        msg = str(exc).lower()
        if any(s in msg for s in (
            "model not available", "model is not available",
            "deprecated", "no longer supported", "unavailable",
            "not found",
        )):
            return True
    return False


# ---- LLMClient --------------------------------------------------------------------------------------------------------

class LLMClient:
    """Manages model tiers, disk cache, ledger, retries, and optional fake mode."""

    def __init__(self, state_dir: Path, _client=None):
        self._state = Path(state_dir)
        cache_override = os.environ.get("NOVA_CACHE_DIR")
        self._cache_dir = Path(cache_override) if cache_override else (self._state / "cache")
        self._ledger = self._state / "ledger.jsonl"
        self._ledger_lock = threading.Lock()
        self._fake = os.environ.get("NOVA_LLM", "").lower() == "fake"
        _max_raw = os.environ.get("NOVA_MAX_PAID_TOKENS")
        self._max_paid_tokens: int | None = int(_max_raw) if _max_raw else None
        if not self._fake:
            if _client is not None:
                self._client = _client
            else:
                import anthropic
                # audit M4: tight per-call timeout and low SDK-level
                # retries. Our own retry loop in _real_invoke covers
                # transient failures with jittered backoff.
                self._client = anthropic.Anthropic(timeout=90, max_retries=1)

    # ---- public API ---------------------------------------------------------------------------------------------------

    def call(
        self,
        tier: str,
        purpose: str,
        messages: list[dict],
        schema: dict,
        prompt_version: str = "1",
        system: str = "",
        max_tokens: int = 4096,
    ) -> dict:
        """Call the model at the given tier, falling back through tiers on NotFoundError."""
        tier_idx = _TIER_INDEX[tier]
        all_tiers = _tier_models()
        # Build a flat list: remaining models in this tier, then all models in higher tiers
        candidates: list[str] = []
        for models in all_tiers[tier_idx:]:
            candidates.extend(models)

        last_err: Exception | None = None
        for model in candidates:
            try:
                return self._call_model(model, purpose, messages, schema, prompt_version, system, max_tokens)
            except TruncatedOutput:
                raise
            except Exception as e:
                if _is_not_found(e):
                    last_err = e
                    continue
                raise
        raise RuntimeError(f"all models exhausted from tier '{tier}'") from last_err

    def pool(self, tasks: list[tuple], max_workers: int = 4) -> list:
        """Run [(callable, *args), ...] in a thread pool and return results in order."""
        from concurrent.futures import ThreadPoolExecutor
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
        system: str,
        max_tokens: int,
    ) -> dict:
        key = _cache_key(model, prompt_version, system, messages, schema, max_tokens)
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

        if self._max_paid_tokens is not None:
            current_paid = self._ledger_paid_total()
            if current_paid >= self._max_paid_tokens:
                raise RuntimeError(
                    f"NOVA_MAX_PAID_TOKENS={self._max_paid_tokens} reached "
                    f"(paid so far: {current_paid}). Stopping before {purpose}."
                )
        result, input_tokens, output_tokens, cache_read, cache_creation = self._invoke(model, messages, schema, system, max_tokens)
        self._write_cache(key, {"result": result, "input_tokens": input_tokens, "output_tokens": output_tokens})
        self._write_ledger({
            "time": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_creation,
            "cached": False,
        })
        return result

    def _invoke(self, model: str, messages: list[dict], schema: dict, system: str, max_tokens: int) -> tuple[dict, int, int, int, int]:
        if self._fake:
            return self._fake_invoke(model, schema)
        return self._real_invoke(model, messages, schema, system, max_tokens)

    def _fake_invoke(self, model: str, schema: dict) -> tuple[dict, int, int, int, int]:
        result = _fake_responses.get(model) or _fake_responses.get("*") or {}
        return result, 10, 5, 0, 0

    def _real_invoke(self, model: str, messages: list[dict], schema: dict, system: str, max_tokens: int) -> tuple[dict, int, int, int, int]:
        import anthropic
        max_retries = 5
        use_tool_choice = True
        for attempt in range(max_retries):
            try:
                kwargs: dict[str, Any] = dict(
                    model=model,
                    max_tokens=max_tokens,
                    tools=[{
                        "name": "output",
                        "description": "Structured output",
                        "input_schema": schema,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=messages,
                )
                if use_tool_choice:
                    kwargs["tool_choice"] = {"type": "tool", "name": "output"}
                if system:
                    kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                resp = self._client.messages.create(**kwargs)
                if resp.stop_reason == "max_tokens":
                    raise TruncatedOutput(f"model {model} hit max_tokens={max_tokens}")
                for block in resp.content:
                    if block.type == "tool_use" and block.name == "output":
                        cache_read = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
                        cache_creation = getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
                        return block.input, resp.usage.input_tokens, resp.usage.output_tokens, cache_read, cache_creation
                raise ValueError("no tool_use block in response")
            except TruncatedOutput:
                raise
            except anthropic.NotFoundError:
                raise
            except anthropic.PermissionDeniedError:
                raise
            except anthropic.BadRequestError as e:
                # Some newer models don't support tool_choice:tool/any. Retry
                # without tool_choice (the single-tool definition is enough).
                msg = str(e).lower()
                if "tool_choice" in msg and use_tool_choice:
                    use_tool_choice = False
                    continue
                raise
            except Exception as e:
                if _is_retryable(e) and attempt < max_retries - 1:
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
        target = self._cache_dir / f"{key}.json"
        fd, tmp = tempfile.mkstemp(dir=self._cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _ledger_paid_total(self) -> int:
        """Sum input + output tokens for all non-cached ledger entries."""
        total = 0
        try:
            for line in self._ledger.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if not entry.get("cached", False):
                    total += entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
        except FileNotFoundError:
            pass
        return total

    def _write_ledger(self, entry: dict) -> None:
        self._state.mkdir(parents=True, exist_ok=True)
        with self._ledger_lock:
            with open(self._ledger, "a") as f:
                f.write(json.dumps(entry) + "\n")
