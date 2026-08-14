"""doctor output pinned with a stubbed shutil.which / version probe, normalized
for python-version, paths, and the cclenzz version token (§1.1, §11.6)."""

import io
import sys

from cclenzz import VERSION
from cclenzz import doctor as doctor_mod
from cclenzz.config import Settings
from cclenzz.doctor import cmd_doctor
from cclenzz.paths import AppPaths


class _Probe:
    def __init__(self, out):
        self.stdout = out
        self.stderr = ""


def _run(caps, tmp_path, monkeypatch, persist=True):
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda b: "/fake/bin/claude")
    monkeypatch.setattr(doctor_mod.subprocess, "run",
                        lambda *a, **k: _Probe("claude 9.9.9 (stub)\n"))
    paths = AppPaths(state_root=str(tmp_path / "state"),
                     projects_glob=str(tmp_path / "proj" / "*" / "*.jsonl"))
    settings = Settings.from_config({"persist": persist})
    out = io.StringIO()
    cmd_doctor(caps, paths, settings, out=out)
    return out.getvalue(), paths


def test_doctor_structure(make_caps, tmp_path, monkeypatch):
    caps = make_caps(color="mono", glyphs="unicode", bg="dark", mouse=False)
    text, paths = _run(caps, tmp_path, monkeypatch)
    lines = text.splitlines()
    py = ".".join(str(x) for x in sys.version_info[:3])
    assert lines[0] == f"cclenzz {VERSION} · python {py} · {sys.platform}"
    assert VERSION == "1.0.0"
    body = "\n".join(lines[1:])
    assert "sessions glob" in body and "(no files" in body
    assert "terminal" in body and "mono" in body and "unicode" in body
    assert "theme" in body and "dark" in body
    assert "claude binary" in body and "/fake/bin/claude" in body and "9.9.9" in body
    assert "audit model" in body and "opus" in body
    assert "explain model" in body and "haiku" in body
    assert "config file" in body and "not present" in body
    assert "state dir" in body and "writable" in body


def test_doctor_persist_disabled(make_caps, tmp_path, monkeypatch):
    caps = make_caps(color="mono")
    text, _ = _run(caps, tmp_path, monkeypatch, persist=False)
    assert "persistence disabled" in text


def test_doctor_no_claude(make_caps, tmp_path, monkeypatch):
    caps = make_caps(color="mono")
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda b: None)
    paths = AppPaths(state_root=str(tmp_path / "s"),
                     projects_glob=str(tmp_path / "p" / "*" / "*.jsonl"))
    out = io.StringIO()
    cmd_doctor(caps, paths, Settings.from_config({}), out=out)
    assert "not found on PATH — audit unavailable" in out.getvalue()
