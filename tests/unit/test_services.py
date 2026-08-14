"""Config load/Settings, terminal-capability env matrix, score bands, and
explain-context building (§11.7)."""

import os

import pytest

from cclenzz import termcaps
from cclenzz.audit.explain import (EXPLAIN_MAX_CHARS, EXPLAIN_MAX_LINES,
                                   _clip_explain, build_explain_context)
from cclenzz.audit.scoring import CONF_LOW, dim_for, label_for
from cclenzz.config import CONFIG_KEYS, Settings, load_config
from cclenzz.sessions import Session
from cclenzz.termcaps import detect_caps
from cclenzz.ui.tabstate import Tab

from helpers.jsonl import fixture_path


# ---- config ----
def test_load_config_absent(tmp_path):
    assert load_config(str(tmp_path / "nope.toml")) == {}


def test_load_config_every_key(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('theme="dark"\nicons="ascii"\ncolor="never"\nauto_audit=true\n'
                 'audit_model="opus"\nexplain_model="haiku"\ninterval=2.0\n'
                 'ambiwidth=2\nprojects_glob="/x/*.jsonl"\nclaude_bin="cb"\n'
                 'persist=false\nstate_retention_days=30\n')
    cfg = load_config(str(p))
    assert set(cfg) <= CONFIG_KEYS
    assert cfg["interval"] == 2.0 and cfg["persist"] is False


def test_load_config_unknown_key_warns(tmp_path, capsys):
    p = tmp_path / "c.toml"
    p.write_text('theme="dark"\nbogus=1\n')
    load_config(str(p))
    assert "unknown config key 'bogus'" in capsys.readouterr().err


def test_load_config_malformed_exits(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('theme = "dark\n')
    with pytest.raises(SystemExit) as e:
        load_config(str(p))
    assert e.value.code == 1


def test_settings_empty_string_fallback():
    assert Settings.from_config({"claude_bin": ""}).claude_bin == "claude"
    assert Settings.from_config({"audit_model": ""}).audit_model == "opus"


def test_settings_persist_and_retention():
    assert Settings.from_config({}).persist is True
    assert Settings.from_config({"persist": False}).persist is False
    assert Settings.from_config({"state_retention_days": 30}).state_retention_days == 30


# ---- termcaps ----
def _env(monkeypatch, **kw):
    for k in ("NO_COLOR", "CLICOLOR_FORCE", "COLORTERM", "TMUX", "TERM_PROGRAM",
              "LC_ALL", "LC_CTYPE", "LANG", "TERM"):
        monkeypatch.delenv(k, raising=False)
    for k, v in kw.items():
        monkeypatch.setenv(k, v)


def test_no_color_beats_always(monkeypatch):
    _env(monkeypatch, NO_COLOR="1", COLORTERM="truecolor")
    caps = detect_caps({"color": "always"})
    assert caps.color == "mono"


def test_colorterm_truecolor(monkeypatch):
    _env(monkeypatch, COLORTERM="truecolor")
    assert detect_caps({}).color == "rgb"


def test_clicolor_force_promotes(monkeypatch):
    _env(monkeypatch, CLICOLOR_FORCE="1")
    assert detect_caps({}).color in ("c16", "c256", "rgb")


def test_icons_auto_locale(monkeypatch):
    _env(monkeypatch, LANG="en_US.UTF-8")
    assert detect_caps({}).glyphs == "unicode"
    _env(monkeypatch, LANG="C")
    assert detect_caps({}).glyphs == "ascii"


def test_nerd_only_explicit(monkeypatch):
    _env(monkeypatch, LANG="en_US.UTF-8")
    assert detect_caps({}).glyphs != "nerd"
    assert detect_caps({"icons": "nerd"}).glyphs == "nerd"


def test_osc8_allowlist_and_multiplexer(monkeypatch):
    _env(monkeypatch, TERM_PROGRAM="iTerm.app")
    assert detect_caps({}).osc8 is True
    _env(monkeypatch, TERM_PROGRAM="iTerm.app", TMUX="/tmp/x")
    assert detect_caps({}).osc8 is False


def test_theme_override_skips_osc11(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(termcaps, "_query_bg_osc11",
                        lambda: (_ for _ in ()).throw(AssertionError("queried!")))
    assert detect_caps({"theme": "light"}).bg == "light"
    assert detect_caps({"theme": "dark"}).bg == "dark"


def test_ambiwidth_only_when_2(monkeypatch):
    _env(monkeypatch)
    assert detect_caps({}).ambiwidth == 1
    assert detect_caps({"ambiwidth": 2}).ambiwidth == 2
    assert detect_caps({"ambiwidth": 5}).ambiwidth == 1


class _TtyStdout:
    """Stand-in for a real tty so the color/bg/title branches gated on
    ``sys.stdout.isatty()`` are exercised without a terminal."""

    def isatty(self):
        return True


def _tty(monkeypatch, ncolors):
    """Force detect_caps down its is_tty path with a deterministic terminfo
    color count (the real curses call is nondeterministic across machines)."""
    import curses
    monkeypatch.setattr(termcaps.sys, "stdout", _TtyStdout())
    monkeypatch.setattr(curses, "setupterm", lambda *a, **k: None)
    monkeypatch.setattr(curses, "tigetnum", lambda cap: ncolors)


def test_color_256_terminfo_gives_c256(monkeypatch):
    _env(monkeypatch, TERM="xterm-256color")
    _tty(monkeypatch, 256)
    assert detect_caps({"theme": "dark"}).color == "c256"


def test_color_16_terminfo_gives_c16(monkeypatch):
    _env(monkeypatch, TERM="xterm")
    _tty(monkeypatch, 16)
    assert detect_caps({"theme": "dark"}).color == "c16"


def test_color_never_forces_mono(monkeypatch):
    _env(monkeypatch, COLORTERM="truecolor")
    assert detect_caps({"color": "never"}).color == "mono"


def test_color_always_promotes_mono_to_c16(monkeypatch):
    # No tty, no COLORTERM → would be mono; `color = always` floors it at c16.
    _env(monkeypatch)
    assert detect_caps({"color": "always"}).color == "c16"


def test_bg_queried_on_real_tty_without_theme(monkeypatch):
    _env(monkeypatch)
    _tty(monkeypatch, 256)
    monkeypatch.setattr(termcaps, "_query_bg_osc11", lambda: "light")
    assert detect_caps({}).bg == "light"


def test_title_off_on_dumb_terminal(monkeypatch):
    _env(monkeypatch, TERM="dumb")
    _tty(monkeypatch, 8)
    caps = detect_caps({"theme": "dark"})
    assert caps.title is False
    _env(monkeypatch, TERM="xterm")
    _tty(monkeypatch, 8)
    assert detect_caps({"theme": "dark"}).title is True


def test_query_bg_osc11_falls_back_to_dark(monkeypatch):
    # No real tty on stdin → termios raises → the guard returns "dark".
    assert termcaps._query_bg_osc11() == "dark"


# ---- scoring ----
@pytest.mark.parametrize("align,label", [
    (100, "aligned"), (85, "aligned"), (84, "partial"), (60, "partial"),
    (59, "drift"), (0, "drift"), ("junk", "drift"), (None, "drift"),
])
def test_label_bands(align, label):
    assert label_for(align)[0] == label


def test_dim_for():
    assert dim_for(CONF_LOW - 1) is True
    assert dim_for(CONF_LOW) is False
    assert dim_for(None) is True


# ---- explain context ----
def _tab(fixture):
    s = Session(fixture_path(fixture))
    s.read_meta()
    return Tab(s, True)


def test_explain_context_prompt_mode():
    tab = _tab("basic.jsonl")
    prompt = next(it for it in tab.items if it.kind == "prompt")
    ctx = build_explain_context(prompt, tab)
    assert "restate the user's goal" in ctx
    assert "read the config" in ctx


def test_explain_context_tool_mode():
    tab = _tab("basic.jsonl")
    tool = next(it for it in tab.items if it.kind == "tool")
    ctx = build_explain_context(tool, tab)
    assert "user asked:" in ctx
    assert "tool:" in ctx and "category:" in ctx


def test_clip_explain_caps():
    text = "\n".join([f"line {i}" for i in range(20)])
    out = _clip_explain(text)
    assert len(out.splitlines()) <= EXPLAIN_MAX_LINES
    long = "x" * (EXPLAIN_MAX_CHARS + 50)
    assert len(_clip_explain(long)) <= EXPLAIN_MAX_CHARS
