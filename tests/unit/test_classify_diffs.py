"""Unit tests for cclenzz.classify and cclenzz.diffs."""

import pytest

from cclenzz.classify import _short_path, classify_tool, item_label
from cclenzz.diffs import (
    build_diff,
    diff_churn,
    is_file_edit,
    item_churn,
)

CWD = "/home/u/proj"


# --------------------------------------------------------------------------
# classify_tool
# --------------------------------------------------------------------------

def test_classify_bash():
    cat, tool, arg, kind = classify_tool("Bash", {"command": "ls -la\nsecond"}, CWD)
    assert (cat, tool, kind) == ("bash", "Bash", "text")
    assert arg == "ls -la"


def test_classify_read_short_path():
    cat, tool, arg, kind = classify_tool(
        "Read", {"file_path": "/home/u/proj/src/x.py"}, CWD)
    assert (cat, tool, arg, kind) == ("read", "Read", "src/x.py", "path")


def test_classify_edit():
    cat, tool, arg, kind = classify_tool(
        "Edit", {"file_path": "/home/u/proj/a.py"}, CWD)
    assert (cat, tool, arg, kind) == ("edit", "Edit", "a.py", "path")


def test_classify_grep():
    cat, tool, arg, kind = classify_tool("Grep", {"pattern": "foo"}, CWD)
    assert (cat, tool, arg, kind) == ("search", "Grep", "foo", "text")


def test_classify_glob_is_search():
    cat, tool, arg, kind = classify_tool("Glob", {"pattern": "*.py"}, CWD)
    assert (cat, tool, arg, kind) == ("search", "Glob", "*.py", "text")


def test_classify_agent():
    cat, tool, arg, kind = classify_tool(
        "Agent", {"subagent_type": "explorer"}, CWD)
    assert (cat, tool, arg, kind) == ("agent", "Agent", "explorer", "text")


def test_classify_task_prefix():
    cat, tool, arg, kind = classify_tool("TaskFoo", {"description": "a task"}, CWD)
    assert cat == "agent"
    assert tool == "TaskFoo"
    assert arg == "a task"
    assert kind == "text"


def test_classify_websearch():
    cat, tool, arg, kind = classify_tool("WebSearch", {"query": "python"}, CWD)
    assert (cat, tool, arg, kind) == ("web", "WebSearch", "python", "text")


def test_classify_webfetch():
    cat, tool, arg, kind = classify_tool("WebFetch", {"url": "http://x.com"}, CWD)
    assert (cat, tool, arg, kind) == ("web", "WebFetch", "http://x.com", "text")


def test_classify_skill():
    cat, tool, arg, kind = classify_tool("Skill", {"skill": "docx"}, CWD)
    assert (cat, tool, arg, kind) == ("skill", "Skill", "docx", "text")


def test_classify_toolsearch_is_search():
    cat, tool, arg, kind = classify_tool("ToolSearch", {"query": "stuff"}, CWD)
    assert (cat, tool, arg, kind) == ("search", "ToolSearch", "stuff", "text")


def test_classify_artifact():
    cat, tool, arg, kind = classify_tool(
        "Artifact", {"file_path": "/home/u/proj/page.html"}, CWD)
    assert (cat, tool, arg, kind) == ("artifact", "Artifact", "page.html", "path")


def test_classify_mcp():
    cat, tool, arg, kind = classify_tool("mcp__srv__dothing", {}, CWD)
    assert (cat, tool, arg, kind) == ("mcp", "MCP", "srv.dothing", "text")


def test_classify_unknown():
    cat, tool, arg, kind = classify_tool("UnknownTool", {}, CWD)
    assert (cat, tool, arg, kind) == ("other", "UnknownTool", "", "text")


def test_classify_none_name():
    cat, tool, arg, kind = classify_tool(None, None, CWD)
    assert cat == "other"
    assert tool == "?"


# --------------------------------------------------------------------------
# _short_path
# --------------------------------------------------------------------------

def test_short_path_relative_to_cwd():
    assert _short_path("/home/u/proj/src/a.py", CWD) == "src/a.py"


def test_short_path_outside_cwd_basename():
    assert _short_path("/other/place/file.txt", CWD) == "file.txt"


def test_short_path_empty():
    assert _short_path("", CWD) == ""


def test_short_path_no_cwd():
    assert _short_path("/a/b/c.py", None) == "c.py"


# --------------------------------------------------------------------------
# item_label
# --------------------------------------------------------------------------

def test_item_label_uses_session_items(session):
    stream = session("basic.jsonl")
    prompt = stream.items[0]
    assert item_label(prompt) == prompt.text
    read_tool = stream.items[1]
    assert item_label(read_tool) == "Read · config.py"


# --------------------------------------------------------------------------
# diffs — over edits.jsonl
# --------------------------------------------------------------------------

def _items_by_name(stream):
    return {it.name: it for it in stream.items if it.kind == "tool"}


def test_is_file_edit(session):
    stream = session("edits.jsonl")
    tools = _items_by_name(stream)
    assert is_file_edit(tools["Edit"]) is True
    assert is_file_edit(tools["Write"]) is True
    assert is_file_edit(tools["NotebookEdit"]) is True
    # a prompt is not a file edit
    assert is_file_edit(stream.items[0]) is False


def test_build_diff_edit_unified(session):
    stream = session("edits.jsonl")
    edit = _items_by_name(stream)["Edit"]
    text = build_diff(edit, CWD)
    assert "---" in text
    assert "+++" in text
    assert any(ln.startswith("-x = 1") for ln in text.splitlines())
    assert any(ln.startswith("+x = 10") for ln in text.splitlines())


def test_build_diff_write_no_baseline_tag(session):
    stream = session("edits.jsonl")
    write = _items_by_name(stream)["Write"]
    text = build_diff(write, CWD)
    assert "(no baseline)" in text
    assert any(ln.startswith("+new file") for ln in text.splitlines())


def test_build_diff_cached(session):
    stream = session("edits.jsonl")
    edit = _items_by_name(stream)["Edit"]
    first = build_diff(edit, CWD)
    assert edit._diff is first
    assert build_diff(edit, CWD) is first


def test_diff_churn_counts_exclude_headers(session):
    stream = session("edits.jsonl")
    edit = _items_by_name(stream)["Edit"]
    text = build_diff(edit, CWD)
    added, removed = diff_churn(text)
    # old: x=1,y=2 ; new: x=10,y=2,z=3  -> -x=1, +x=10, +z=3
    assert added == 2
    assert removed == 1


def test_diff_churn_ignores_plusplusplus():
    text = "--- file\n+++ file\n-old\n+new\n+more"
    assert diff_churn(text) == (2, 1)


def test_build_diff_identical_no_change():
    # Construct a minimal Edit item with identical strings.
    from cclenzz.model import Item
    it = Item("tool", "edit", "Edit", "x.py", "path", name="Edit",
              tool_input={"file_path": "/home/u/proj/x.py",
                          "old_string": "same", "new_string": "same"})
    assert build_diff(it, CWD) == "(no textual change)"


def test_item_churn_cached(session):
    stream = session("edits.jsonl")
    edit = _items_by_name(stream)["Edit"]
    c1 = item_churn(edit, CWD)
    c2 = item_churn(edit, CWD)
    assert c1 is c2
    assert c1 == (2, 1)
