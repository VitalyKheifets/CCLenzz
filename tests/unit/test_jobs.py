"""AuditJob / ExplainJob single-flight managers driven by the scripted
fake_judge: verdict storage, cost accrual, auth beep, and explain auto-expand."""

import time

import pytest

from cclenzz.config import Settings
from cclenzz.paths import AppPaths
from cclenzz.sessions import Session
from cclenzz.ui.jobs import AuditJob, ExplainJob
from cclenzz.ui.tabstate import Tab, Toast

from helpers.jsonl import fixture_path


def _tab(fixture="basic.jsonl"):
    s = Session(fixture_path(fixture))
    s.read_meta()
    return Tab(s, True)


@pytest.fixture
def env(tmp_path):
    settings = Settings.from_config({"persist": False})   # no disk writes
    paths = AppPaths(state_root=str(tmp_path),
                     projects_glob=str(tmp_path / "*.jsonl"))
    return settings, paths


def _wait_done(job, timeout=2.0):
    deadline = time.time() + timeout
    while job.status != "done" and time.time() < deadline:
        time.sleep(0.02)
    assert job.status == "done"


AUDIT_OK = {
    "ok": True,
    "verdicts": [{"prompt_idx": 1, "ask": "a", "delivered": "d", "defects": [],
                  "alignment": 100, "evidence_gaps": [], "confidence": 100,
                  "reason": "r", "flagged_items": []}],
    "cost": 0.01, "model": "opus", "cancelled": False,
}
AUDIT_AUTH = {
    "ok": False, "auth": True, "error": "Not logged in — run `claude login`.",
    "verdicts": [], "cost": None, "model": "opus", "cancelled": False,
}


# --------------------------------------------------------------------------- #
def test_audit_single_flight_toast(env, fake_judge, caps_unicode_dark):
    settings, paths = env
    tab = _tab()
    job = AuditJob(fake_judge, settings, paths)
    job.status = "running"                        # pretend a run is in flight
    toast = job.start(tab, caps_unicode_dark)
    assert isinstance(toast, Toast)
    assert toast.text == "audit already running…"


def test_audit_success_stores_verdicts_and_cost(env, fake_judge, caps_unicode_dark):
    settings, paths = env
    tab = _tab()
    fake_judge.audit_result = AUDIT_OK
    job = AuditJob(fake_judge, settings, paths)

    start_toast = job.start(tab, caps_unicode_dark)
    assert isinstance(start_toast, Toast)
    _wait_done(job)

    out = job.consume_done(caps_unicode_dark)
    assert out["beep"] is False
    assert out["toast"] is not None

    _lead, turns = tab.stream.turns()
    p1 = turns[0][0]
    assert id(p1) in tab.audit_by_prompt
    assert tab.audit_by_prompt[id(p1)]["alignment"] == 100
    assert tab.audit_cost == pytest.approx(0.01)
    assert len(fake_judge.audit_calls) == 1


def test_audit_auth_failure_beeps_with_long_toast(env, fake_judge, caps_unicode_dark):
    settings, paths = env
    tab = _tab()
    fake_judge.audit_result = AUDIT_AUTH
    job = AuditJob(fake_judge, settings, paths)
    job.start(tab, caps_unicode_dark)
    _wait_done(job)

    out = job.consume_done(caps_unicode_dark)
    assert out["beep"] is True
    assert out["toast"] is not None
    assert out["toast"].ttl == 20.0
    assert tab.audit_by_prompt == {}              # nothing stored on auth error


def test_explain_start_auto_expands_and_marks_running(env, fake_judge,
                                                      caps_unicode_dark):
    settings, paths = env
    tab = _tab()
    item = next(it for it in tab.items if it.kind == "tool")
    fake_judge.explain_result = {"ok": True, "text": "because", "cost": 0.001,
                                 "model": "haiku", "cancelled": False}
    job = ExplainJob(fake_judge, settings, paths)

    toast = job.start(tab, item, caps_unicode_dark)
    assert isinstance(toast, Toast)
    # auto-expand + a running record are set synchronously in start()
    assert id(item) in tab.expanded
    assert tab.explain[id(item)]["status"] == "running"


def test_explain_consume_done_marks_done_with_text(env, fake_judge,
                                                   caps_unicode_dark):
    settings, paths = env
    tab = _tab()
    item = next(it for it in tab.items if it.kind == "tool")
    fake_judge.explain_result = {"ok": True, "text": "because", "cost": 0.001,
                                 "model": "haiku", "cancelled": False}
    job = ExplainJob(fake_judge, settings, paths)
    job.start(tab, item, caps_unicode_dark)
    _wait_done(job)

    out = job.consume_done(caps_unicode_dark, [tab])
    rec = tab.explain[id(item)]
    assert rec["status"] == "done"
    assert rec["text"] == "because"
    assert out["toast"] is not None
    assert len(fake_judge.explain_calls) == 1
