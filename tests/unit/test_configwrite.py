"""Config rendering + the shared atomic text writer (``configwrite.py``).

Covers ``_toml_value`` escaping, ``write_config``'s round-trip (wizard answers
active, non-wizard keys preserved uncommented when they had an explicit value),
and ``_atomic_write_text``'s permissions + failure-cleanup contract. All pure
logic — no terminal, no network, tmp dirs only."""

import os
import stat
import tomllib

import pytest

from cclenzz import configwrite
from cclenzz.configwrite import (_atomic_write_text, _toml_value, write_config)


ANSWERS = {"theme": "dark", "icons": "nerd", "color": "always", "auto_audit": True}


# --- _toml_value ------------------------------------------------------------ #
def test_toml_value_bool():
    assert _toml_value(True) == "true"
    assert _toml_value(False) == "false"


def test_toml_value_int_and_float():
    assert _toml_value(30) == "30"
    assert _toml_value(1.5) == "1.5"


def test_toml_value_str_is_quoted():
    assert _toml_value("opus") == '"opus"'


def test_toml_value_str_escapes_backslash_and_quote():
    # A Windows-ish glob with a quote in it must survive as valid TOML.
    assert _toml_value('a\\b"c') == '"a\\\\b\\"c"'
    # And it must parse back to the original string.
    parsed = tomllib.loads(f"k = {_toml_value('a\\b\"c')}")
    assert parsed["k"] == 'a\\b"c'


# --- write_config: wizard answers ------------------------------------------- #
def _roundtrip(tmp_path, answers, existing=None):
    path = write_config(answers, existing, str(tmp_path / "config.toml"))
    with open(path, "rb") as fh:
        return path, tomllib.load(fh)


def test_write_config_renders_wizard_answers(tmp_path):
    _, cfg = _roundtrip(tmp_path, ANSWERS)
    assert cfg["theme"] == "dark"
    assert cfg["icons"] == "nerd"
    assert cfg["color"] == "always"
    assert cfg["auto_audit"] is True


def test_write_config_auto_audit_false_renders_as_bool(tmp_path):
    _, cfg = _roundtrip(tmp_path, {**ANSWERS, "auto_audit": False})
    assert cfg["auto_audit"] is False


def test_write_config_returns_the_path(tmp_path):
    dest = str(tmp_path / "config.toml")
    assert write_config(ANSWERS, None, dest) == dest


def test_write_config_none_existing_does_not_crash(tmp_path):
    # Optional keys stay commented → absent from the parsed TOML.
    _, cfg = _roundtrip(tmp_path, ANSWERS, existing=None)
    assert "audit_model" not in cfg
    assert "interval" not in cfg


# --- write_config: optional-key preservation -------------------------------- #
def test_write_config_preserves_optional_string_key(tmp_path):
    _, cfg = _roundtrip(tmp_path, ANSWERS, existing={"audit_model": "haiku"})
    assert cfg["audit_model"] == "haiku"


def test_write_config_preserves_optional_number_and_bool(tmp_path):
    existing = {"interval": 2.5, "persist": False, "state_retention_days": 7}
    _, cfg = _roundtrip(tmp_path, ANSWERS, existing=existing)
    assert cfg["interval"] == 2.5
    assert cfg["persist"] is False
    assert cfg["state_retention_days"] == 7


def test_write_config_keeps_inline_comment_when_uncommenting(tmp_path):
    path = write_config(ANSWERS, {"claude_bin": "claude"},
                        str(tmp_path / "config.toml"))
    text = open(path, encoding="utf-8").read()
    # The value is now active, and the template's trailing comment survives.
    assert 'claude_bin = "claude"' in text
    assert "# the claude CLI used for audit/explain calls" in text


def test_write_config_ignores_non_optional_existing_keys(tmp_path):
    # `theme` is wizard-owned, not in CONFIG_OPTIONAL_KEYS: an existing value
    # must not override the wizard's answer.
    _, cfg = _roundtrip(tmp_path, ANSWERS, existing={"theme": "light"})
    assert cfg["theme"] == "dark"


# --- _atomic_write_text ----------------------------------------------------- #
def test_atomic_write_creates_dir_and_file_owner_only(tmp_path):
    target = tmp_path / "nested" / "deep" / "f.txt"
    _atomic_write_text(str(target), "hello")
    assert target.read_text() == "hello"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(target.parent).st_mode) == 0o700


def test_atomic_write_no_dir_component(tmp_path, monkeypatch):
    # A bare filename (no dirname) must skip the makedirs branch and still write.
    monkeypatch.chdir(tmp_path)
    _atomic_write_text("bare.txt", "x")
    assert (tmp_path / "bare.txt").read_text() == "x"


def test_atomic_write_cleans_up_tmp_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "f.txt"

    def boom(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(configwrite.os, "fsync", boom)
    with pytest.raises(OSError):
        _atomic_write_text(str(target), "data")
    # Neither the real file nor the temp scratch file survives a failed write.
    assert not target.exists()
    assert not (tmp_path / "f.txt.tmp").exists()
