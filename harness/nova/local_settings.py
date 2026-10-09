"""Optional repo-local settings read from ``<repo>/.nova-local.json``.

The grader passes only ``PATH``, ``ANTHROPIC_API_KEY`` and ``ANTHROPIC_BASE_URL``
to the harness, so repo-local defaults for the cache dir, token cap, and model
names have to live on disk — not in environment variables alone. Env vars still
win when they are set; the file is a fallback for a developer who wants
``make grade`` to re-use a persistent cache.

Keys accepted:
  - ``cache_dir`` (str) → sets ``NOVA_CACHE_DIR``
  - ``max_paid_tokens`` (int) → sets ``NOVA_MAX_PAID_TOKENS``
  - ``model_overrides`` (dict with keys ``fast``, ``main``, ``strong``) →
    sets ``NOVA_MODEL_FAST`` / ``NOVA_MODEL_MAIN`` / ``NOVA_MODEL_STRONG``

A missing file is not an error. Any JSON error is swallowed and the file is
ignored so a bad local override cannot break a real grader run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ENV_FOR_KEY = {
    "cache_dir": "NOVA_CACHE_DIR",
    "max_paid_tokens": "NOVA_MAX_PAID_TOKENS",
}

_TIER_ENV = {
    "fast": "NOVA_MODEL_FAST",
    "main": "NOVA_MODEL_MAIN",
    "strong": "NOVA_MODEL_STRONG",
}


def _repo_root() -> Path:
    # This file lives at <repo>/harness/nova/local_settings.py
    return Path(__file__).resolve().parents[2]


def load(path: Path | None = None) -> dict:
    """Return the parsed settings dict (or ``{}`` if missing/invalid)."""
    p = path if path is not None else _repo_root() / ".nova-local.json"
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def apply(path: Path | None = None) -> dict:
    """Populate ``os.environ`` from the file. Env vars already set win.

    Returns the settings dict that was applied (useful for tests).
    """
    settings = load(path)
    for key, env in _ENV_FOR_KEY.items():
        if env in os.environ:
            continue
        if key not in settings:
            continue
        os.environ[env] = str(settings[key])
    overrides = settings.get("model_overrides") or {}
    if isinstance(overrides, dict):
        for tier, env in _TIER_ENV.items():
            if env in os.environ:
                continue
            val = overrides.get(tier)
            if not val:
                continue
            if isinstance(val, list):
                val = ",".join(str(x) for x in val)
            os.environ[env] = str(val)
    return settings
