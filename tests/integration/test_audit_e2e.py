"""End-to-end audit/explain through a pty against the stub `claude` (§11.9).
No real model call happens."""

import glob
import json
import os

import pytest

from helpers.ptytui import PtySession


def _sidecar(sb):
    hits = glob.glob(os.path.join(sb.state_dir, "sessions", "*", "*.json"))
    return hits[0] if hits else None


def test_audit_writes_sidecar_and_rehydrates(sandbox):
    sb = sandbox(claude_stub="fake_claude_ok")
    sb.add_session("basic.jsonl")
    before = sb.claude_hash()
    p = PtySession(sb.env())
    try:
        assert p.read_until("read the config", timeout=6)
        p.send("a")
        assert p.read_until("verdicts", timeout=10)   # success toast
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()

    side = _sidecar(sb)
    assert side, "no sidecar written"
    doc = json.load(open(side))
    assert doc["schema"] == 1
    assert doc["cclenzz_version"] == "1.0.0"
    assert doc["audit"]["verdicts"], "no verdicts persisted"

    # the stub received the audit task prefix + [prompt 1]
    if os.path.exists(sb.capture):
        cap = json.load(open(sb.capture))
        assert "--json-schema" in cap["argv"]
        assert cap["stdin"].startswith("Audit the session transcript below.")
        assert "[prompt 1]" in cap["stdin"]

    # relaunch → rehydrated badge visible
    p2 = PtySession(sb.env())
    try:
        assert p2.read_until("aligned", timeout=6)   # label from rehydrated verdict
        p2.send("q")
        assert p2.wait(timeout=6) == 0
    finally:
        p2.close()

    assert sb.claude_hash() == before   # ~/.claude never written


def test_audit_auth_toast(sandbox):
    sb = sandbox(claude_stub="fake_claude_auth")
    sb.add_session("basic.jsonl")
    p = PtySession(sb.env())
    try:
        assert p.read_until("read the config", timeout=6)
        p.send("a")
        assert p.read_until("Not logged in", timeout=10)
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()
