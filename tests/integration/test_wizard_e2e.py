"""Wizard through a pty (§11.9): accepting defaults writes a template config;
a re-run preserves a hand-added optional key; Ctrl-C aborts without writing."""

import os
import time

import pytest

from cclenzz.configwrite import CONFIG_TEMPLATE
from helpers.ptytui import PtySession


def _run_wizard(sb, keys_between, per=0.4):
    """Launch `cclenzz setup`, drive it, return exit code. Drains the pty between
    keystrokes so the child never blocks writing its (verbose) redraws."""
    p = PtySession(sb.env(), args=("setup",))
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            p._poll(0.1)
        for k in keys_between:
            p.send(k)
            end = time.time() + per
            while time.time() < end:
                p._poll(0.1)
        return p.wait(timeout=8)
    finally:
        p.close()


def test_setup_accept_defaults(sandbox):
    sb = sandbox()
    cfg_path = os.path.join(sb.state_dir, "config.toml")
    os.remove(cfg_path)  # start clean so the wizard has nothing to preselect
    code = _run_wizard(sb, ["\r", "\r", "\r", "\r"])
    assert code == 0
    assert os.path.exists(cfg_path)
    expected = CONFIG_TEMPLATE.format(theme="auto", icons="auto", color="auto",
                                      auto_audit="false")
    assert open(cfg_path).read() == expected


def test_setup_preserves_optional_key(sandbox):
    sb = sandbox()
    cfg_path = os.path.join(sb.state_dir, "config.toml")
    with open(cfg_path, "w") as fh:
        fh.write('theme = "dark"\ninterval = 2.0\n')
    code = _run_wizard(sb, ["\r", "\r", "\r", "\r"])
    assert code == 0
    text = open(cfg_path).read()
    assert "interval = 2.0" in text          # re-emitted uncommented
    assert "# live poll interval" in text    # trailing comment preserved


def test_setup_abort_writes_nothing(sandbox):
    sb = sandbox()
    cfg_path = os.path.join(sb.state_dir, "config.toml")
    os.remove(cfg_path)
    p = PtySession(sb.env(), args=("setup",))
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            p._poll(0.1)
        p.send("\x03")   # Ctrl-C → abort
        code = p.wait(timeout=8)
    finally:
        p.close()
    assert code == 130
    assert not os.path.exists(cfg_path)
