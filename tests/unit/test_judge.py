"""ClaudeCliJudge exercised against the stub `claude` binaries via real
subprocesses (fast, local). Covers ok/auth/garbage/empty/absent/cancel and the
auth-signal table (§11.7)."""

import os
import threading
import time

import pytest

from cclenzz.audit.judge import (ClaudeCliJudge, _auth_error_result,
                                 _looks_like_auth_error)

BIN = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "bin")
TRANSCRIPT = '[prompt 1] (item 0) "do the thing"\n\n[session status] COMPLETE'


def _judge(stub):
    return ClaudeCliJudge(os.path.join(BIN, stub), "opus", "haiku")


def test_audit_ok():
    res = _judge("fake_claude_ok").audit(TRANSCRIPT)
    assert res["ok"] is True
    assert res["verdicts"] and res["verdicts"][0]["prompt_idx"] == 1
    assert res["cost"] == 0.0123
    assert res["cancelled"] is False


def test_explain_ok():
    res = _judge("fake_claude_ok").explain("explain this Bash call")
    assert res["ok"] is True
    assert "Runs the test suite." in res["text"]
    assert res["cost"] == 0.0004


def test_audit_auth_error():
    res = _judge("fake_claude_auth").audit(TRANSCRIPT)
    assert res["ok"] is False and res["auth"] is True
    assert "auth login" in res["error"] and "auth status" in res["error"]


def test_audit_garbage_envelope():
    res = _judge("fake_claude_garbage").audit(TRANSCRIPT)
    assert res["ok"] is False
    assert "could not parse" in res["error"]


def test_audit_empty_exit1():
    res = _judge("fake_claude_empty").audit(TRANSCRIPT)
    assert res["ok"] is False
    assert "boom" in res["error"] or "claude exited" in res["error"]


def test_audit_binary_absent():
    res = ClaudeCliJudge("/no/such/claude_binary_xyz", "opus", "haiku").audit(TRANSCRIPT)
    assert res["ok"] is False
    assert "not found on PATH" in res["error"]


def test_audit_cancel():
    j = _judge("fake_claude_slow")
    cancel = threading.Event()
    result = {}

    def work():
        result["r"] = j.audit(TRANSCRIPT, cancel=cancel)
    t = threading.Thread(target=work)
    t.start()
    time.sleep(0.4)
    cancel.set()
    t.join(timeout=5)
    assert not t.is_alive()
    assert result["r"]["cancelled"] is True


def test_auth_signal_table():
    for msg in ("401 Unauthorized", "OAuth token has expired", "please run /login",
                "not logged in", "authentication_error", "invalid api key"):
        assert _looks_like_auth_error(msg) is True
    for msg in ("", "transcript too long", "some random error"):
        assert _looks_like_auth_error(msg) is False


def test_auth_error_result_embeds_binary():
    r = _auth_error_result("opus", "/opt/mybin/claude")
    assert "/opt/mybin/claude auth login" in r["error"]
