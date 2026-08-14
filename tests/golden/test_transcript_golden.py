"""build_audit_transcript output pinned byte-for-byte against references
captured from the current file (§11.6). Transcripts are path-independent."""

import os
import shutil

import pytest

from cclenzz.audit.transcript import _gist, build_audit_transcript, result_summary
from cclenzz.model import ItemStream

from helpers.jsonl import fixture_path, materialize

REF = os.path.join(os.path.dirname(__file__), "reference", "transcripts")
FS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "sessions")


def _ref(name):
    with open(os.path.join(REF, name), "r", encoding="utf-8") as fh:
        return fh.read()


def _transcript(path):
    st = ItemStream(path, None)
    st.refresh()
    txt, _im, _pm = build_audit_transcript(list(st.items), st)
    return txt


@pytest.mark.parametrize("fixture,ref", [
    ("basic.jsonl", "basic.txt"),
    ("inprogress.jsonl", "inprogress.txt"),
    ("edits.jsonl", "edits.txt"),
    ("errors.jsonl", "errors.txt"),
    ("categories.jsonl", "categories.txt"),
    ("parent_sync.jsonl", "parent_sync.txt"),
])
def test_transcript_golden(fixture, ref):
    assert _transcript(fixture_path(fixture)) == _ref(ref)


def test_transcript_async_subagent(tmp_path):
    child = shutil.copy(fixture_path("child_agent.jsonl"),
                        os.path.join(str(tmp_path), "child.jsonl"))
    parent = materialize("parent_agent.jsonl.tmpl", str(tmp_path),
                         subs={"OUTPUT_FILE": child}, dest_name="parent.jsonl")
    txt = _transcript(parent)
    # path-independence: the temp output_file path never appears
    assert child not in txt
    assert txt == _ref("parent_async.txt")


def test_status_trailers():
    assert "[session status] COMPLETE" in _transcript(fixture_path("basic.jsonl"))
    assert "[session status] IN PROGRESS" in _transcript(fixture_path("inprogress.jsonl"))


def test_result_summary_and_gist():
    st = ItemStream(fixture_path("basic.jsonl"), None)
    st.refresh()
    tools = [it for it in st.items if it.kind == "tool"]
    # the Read tool result summarizes its output
    read = tools[0]
    assert result_summary(read).startswith(" → ")
    assert _gist("a\nb\nc\nd\ne", lines=2) == "a ⏎ b"
