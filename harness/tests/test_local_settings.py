"""Unit tests for the optional .nova-local.json settings loader."""
from __future__ import annotations

import json
from nova import local_settings


def test_missing_file_is_noop(tmp_path):
    env: dict = {}
    out = local_settings.apply(tmp_path / "does-not-exist.json", environ=env)
    assert out == {}
    assert env == {}


def test_file_populates_env(tmp_path):
    f = tmp_path / ".nova-local.json"
    f.write_text(json.dumps({
        "cache_dir": "/x/y",
        "max_paid_tokens": 42,
        "model_overrides": {"fast": "fast-a,fast-b", "main": ["m1", "m2"]},
    }))
    env: dict = {}
    local_settings.apply(f, environ=env)
    assert env["NOVA_CACHE_DIR"] == "/x/y"
    assert env["NOVA_MAX_PAID_TOKENS"] == "42"
    assert env["NOVA_MODEL_FAST"] == "fast-a,fast-b"
    assert env["NOVA_MODEL_MAIN"] == "m1,m2"


def test_env_wins_over_file(tmp_path):
    f = tmp_path / ".nova-local.json"
    f.write_text(json.dumps({"cache_dir": "/from-file"}))
    env = {"NOVA_CACHE_DIR": "/from-env"}
    local_settings.apply(f, environ=env)
    assert env["NOVA_CACHE_DIR"] == "/from-env"


def test_bad_json_is_ignored(tmp_path):
    f = tmp_path / ".nova-local.json"
    f.write_text("{not json")
    env: dict = {}
    out = local_settings.apply(f, environ=env)
    assert out == {}
    assert env == {}
