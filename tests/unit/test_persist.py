"""Sidecar cache: path mirroring, audit/explain roundtrip + rehydrate,
schema/corruption tolerance, persist=false no-op, and the hard invariant that
no write path is ever built under the projects-glob tree (§11.7)."""

import os
import shutil

import pytest

from cclenzz import configwrite
from cclenzz.config import Settings
from cclenzz.paths import AppPaths
from cclenzz.persist import (persist_audit, persist_explain, prune_state,
                             rehydrate, session_state_path)
from cclenzz.sessions import Session
from cclenzz.audit.transcript import build_audit_transcript
from cclenzz.identity import build_key_index, item_key
from cclenzz.ui.tabstate import Tab

from helpers.jsonl import fixture_path

SLUG = "-home-u-proj"


def _setup(tmp_path, fixture="basic.jsonl", sid="aaaa1111"):
    proj = tmp_path / "proj" / SLUG
    proj.mkdir(parents=True)
    shutil.copy(fixture_path(fixture), str(proj / f"{sid}.jsonl"))
    paths = AppPaths(state_root=str(tmp_path / "state"),
                     projects_glob=str(tmp_path / "proj" / "*" / "*.jsonl"))
    return paths, str(proj / f"{sid}.jsonl")


def _tab(path):
    s = Session(path)
    s.read_meta()
    return Tab(s, True)


def _audit_res(tab):
    transcript, index_map, prompt_map = build_audit_transcript(
        list(tab.items), tab.stream)
    # flag the first tool item
    tool_idx = next(i for i, it in index_map.items() if it.kind == "tool")
    res = {"verdicts": [{"prompt_idx": 1, "ask": "the ask", "delivered": "did it",
                         "alignment": 88, "confidence": 90, "reason": "why",
                         "defects": [], "evidence_gaps": [], "scope": "main",
                         "flagged_items": [tool_idx]}]}
    return res, index_map, prompt_map


def test_state_path_uses_slug(tmp_path):
    paths, path = _setup(tmp_path)
    tab = _tab(path)
    sp = session_state_path(paths, tab.session)
    assert sp.endswith(os.path.join("state", "sessions", SLUG, "aaaa1111.json"))


def test_audit_roundtrip(tmp_path):
    paths, path = _setup(tmp_path)
    settings = Settings.from_config({})
    tab = _tab(path)
    res, im, pm = _audit_res(tab)
    tab.audit_signature = (len(tab.items), tab.last_mtime)
    tab.audit_cost = 0.05
    persist_audit(paths, settings, tab, res, im, pm)
    assert os.path.exists(session_state_path(paths, tab.session))

    tab2 = _tab(path)
    rehydrate(paths, settings, tab2)
    assert tab2.audit_by_prompt, "verdict did not rehydrate"
    view = next(iter(tab2.audit_by_prompt.values()))
    assert view["alignment"] == 88 and view["confidence"] == 90
    assert tab2.audit_flagged, "flagged item did not rehydrate"
    assert tab2.audit_cost == 0.05


def test_explain_roundtrip_and_stale(tmp_path):
    paths, path = _setup(tmp_path)
    settings = Settings.from_config({})
    tab = _tab(path)
    tool = next(it for it in tab.items if it.kind == "tool")
    rec = {"status": "done", "text": "reads config", "model": "haiku"}
    persist_explain(paths, settings, tab, tool, rec)

    tab2 = _tab(path)
    rehydrate(paths, settings, tab2)
    tool2 = next(it for it in tab2.items if it.kind == "tool")
    assert tab2.explain[id(tool2)]["text"] == "reads config"
    assert tab2.explain[id(tool2)]["stale"] is False

    # mutate the item so its signature changes → stale on next rehydrate
    tool2.result = "different content"
    tool2.bump()
    persist_explain(paths, settings, tab2, tool2, rec)  # persists new sig
    # now hand-corrupt: reload original, its sig differs from persisted
    tab3 = _tab(path)
    rehydrate(paths, settings, tab3)
    tool3 = next(it for it in tab3.items if it.kind == "tool")
    assert tab3.explain[id(tool3)]["stale"] is True


def test_persist_false_is_noop(tmp_path):
    paths, path = _setup(tmp_path)
    settings = Settings.from_config({"persist": False})
    tab = _tab(path)
    res, im, pm = _audit_res(tab)
    persist_audit(paths, settings, tab, res, im, pm)
    assert not os.path.exists(session_state_path(paths, tab.session))
    tab2 = _tab(path)
    rehydrate(paths, settings, tab2)
    assert not tab2.audit_by_prompt


def test_wrong_schema_discarded(tmp_path):
    paths, path = _setup(tmp_path)
    settings = Settings.from_config({})
    tab = _tab(path)
    sp = session_state_path(paths, tab.session)
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w") as fh:
        fh.write('{"schema": 99, "audit": {"verdicts": [{"prompt_key": "x"}]}}')
    tab2 = _tab(path)
    rehydrate(paths, settings, tab2)
    assert not tab2.audit_by_prompt


def test_corrupt_sidecar_tolerated(tmp_path):
    paths, path = _setup(tmp_path)
    settings = Settings.from_config({})
    tab = _tab(path)
    sp = session_state_path(paths, tab.session)
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w") as fh:
        fh.write('{"schema": 1, "audit": {trunca')
    rehydrate(paths, settings, tab)   # must not raise
    assert not tab.audit_by_prompt


def test_no_write_under_projects_glob(tmp_path, monkeypatch):
    paths, path = _setup(tmp_path)
    settings = Settings.from_config({})
    tab = _tab(path)
    res, im, pm = _audit_res(tab)
    proj_root = str(tmp_path / "proj")
    written = []
    real_replace = configwrite.os.replace

    def spy_replace(src, dst):
        written.append(dst)
        return real_replace(src, dst)
    monkeypatch.setattr(configwrite.os, "replace", spy_replace)
    persist_audit(paths, settings, tab, res, im, pm)
    persist_explain(paths, settings, tab,
                    next(it for it in tab.items if it.kind == "tool"),
                    {"status": "done", "text": "t", "model": "haiku"})
    assert written, "nothing was written"
    for dst in written:
        assert not os.path.abspath(dst).startswith(os.path.abspath(proj_root)), dst


def test_prune_orphans_and_retention(tmp_path):
    paths, path = _setup(tmp_path)
    settings = Settings.from_config({})
    tab = _tab(path)
    res, im, pm = _audit_res(tab)
    persist_audit(paths, settings, tab, res, im, pm)
    live_sidecar = session_state_path(paths, tab.session)
    # an orphan sidecar (no matching jsonl)
    orphan = os.path.join(paths.sessions_state_dir(), SLUG, "ghost0000.json")
    with open(orphan, "w") as fh:
        fh.write("{}")
    prune_state(paths, settings)
    assert os.path.exists(live_sidecar)
    assert not os.path.exists(orphan)
