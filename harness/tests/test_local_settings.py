"""Unit tests for the optional .nova-local.json settings loader."""
from __future__ import annotations

import json
import os

import pytest

from nova import local_settings


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    # Snapshot and clear the env vars we might touch.
    keys = [
        "NOVA_CACHE_DIR",
        "NOVA_MAX_PAID_TOKENS",
        "NOVA_MODEL_FAST",
        "NOVA_MODEL_MAIN",
        "NOVA_MODEL_STRONG",
    ]
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / ".nova-local.json"
    return f


def test_missing_file_is_noop(tmp_path, tmp_settings):
    out = local_settings.apply(tmp_path / "does-not-exist.json")
    assert out == {}
    assert "NOVA_CACHE_DIR" not in os.environ


def test_file_populates_env(tmp_settings):
    tmp_settings.write_text(json.dumps({
        "cache_dir": "/x/y",
        "max_paid_tokens": 42,
        "model_overrides": {"fast": "fast-a,fast-b", "main": ["m1", "m2"]},
    }))
    local_settings.apply(tmp_settings)
    assert os.environ["NOVA_CACHE_DIR"] == "/x/y"
    assert os.environ["NOVA_MAX_PAID_TOKENS"] == "42"
    assert os.environ["NOVA_MODEL_FAST"] == "fast-a,fast-b"
    assert os.environ["NOVA_MODEL_MAIN"] == "m1,m2"


def test_env_wins_over_file(tmp_settings, monkeypatch):
    tmp_settings.write_text(json.dumps({"cache_dir": "/from-file"}))
    monkeypatch.setenv("NOVA_CACHE_DIR", "/from-env")
    local_settings.apply(tmp_settings)
    assert os.environ["NOVA_CACHE_DIR"] == "/from-env"


def test_bad_json_is_ignored(tmp_settings):
    tmp_settings.write_text("{not json")
    out = local_settings.apply(tmp_settings)
    assert out == {}
