"""Unit tests for cclenzz.model — ItemStream / Item parsing."""

import os

import pytest

from cclenzz.model import (
    CATEGORIES,
    Item,
    ItemStream,
    extract_user_text,
    result_to_text,
)


# --------------------------------------------------------------------------
# extract_user_text
# --------------------------------------------------------------------------

def test_extract_user_text_meta_none():
    assert extract_user_text({"isMeta": True, "message": {"content": "hi"}}) is None


def test_extract_user_text_string():
    ev = {"message": {"role": "user", "content": "  hello world  "}}
    assert extract_user_text(ev) == "hello world"


def test_extract_user_text_list_text_blocks():
    ev = {"message": {"content": [
        {"type": "text", "text": "one"},
        {"type": "text", "text": "two"},
    ]}}
    assert extract_user_text(ev) == "one two"


def test_extract_user_text_message_not_dict():
    assert extract_user_text({"message": "raw"}) is None
    assert extract_user_text({}) is None


def test_extract_user_text_tool_result_only_none():
    ev = {"message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
    ]}}
    assert extract_user_text(ev) is None


def test_extract_user_text_empty_string_none():
    assert extract_user_text({"message": {"content": "   "}}) is None


# --------------------------------------------------------------------------
# result_to_text
# --------------------------------------------------------------------------

def test_result_to_text_none():
    assert result_to_text(None) is None


def test_result_to_text_str():
    assert result_to_text("plain") == "plain"


def test_result_to_text_text_blocks():
    res = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    assert result_to_text(res) == "a\nb"


def test_result_to_text_tool_reference():
    res = [{"type": "tool_reference", "tool_name": "X"}]
    assert result_to_text(res) == "[tool_reference: X]"


def test_result_to_text_dict_json_truncated():
    out = result_to_text({"a": 1, "b": 2})
    assert isinstance(out, str)
    assert "a" in out


# --------------------------------------------------------------------------
# ItemStream over basic.jsonl
# --------------------------------------------------------------------------

def test_basic_item_sequence(session):
    stream = session("basic.jsonl")
    kinds = [(it.kind, it.tool or it.category) for it in stream.items]
    assert kinds == [
        ("prompt", "prompt"),
        ("tool", "Read"),
        ("tool", "Edit"),
        ("prompt", "prompt"),
        ("tool", "Bash"),
    ]


def test_basic_results_attached(session):
    stream = session("basic.jsonl")
    read_tool = stream.items[1]
    assert read_tool.result == "line1\nline2"
    assert read_tool.is_error is False
    assert read_tool.ts_end is not None
    assert read_tool.duration is not None


def test_basic_says_recorded(session):
    stream = session("basic.jsonl")
    texts = [s for _idx, s in stream.says]
    assert "I'll look at the config." in texts
    assert "Done, fixed the bug." in texts


def test_categories_constant():
    assert CATEGORIES[0] == "prompt"
    assert "bash" in CATEGORIES
    assert "other" in CATEGORIES


# --------------------------------------------------------------------------
# Incremental parsing — whole vs chunked feed
# --------------------------------------------------------------------------

def test_incremental_matches_whole(tmp_path):
    from helpers.jsonl import fixture_path
    raw = open(fixture_path("basic.jsonl"), "rb").read()

    whole_path = os.path.join(str(tmp_path), "whole.jsonl")
    with open(whole_path, "wb") as fh:
        fh.write(raw)
    whole = ItemStream(whole_path, None)
    whole.refresh()

    # Grow the file in two chunks, refreshing between.
    grow_path = os.path.join(str(tmp_path), "grow.jsonl")
    half = len(raw) // 2
    # split on a newline boundary so the first refresh consumes whole lines
    split = raw.rfind(b"\n", 0, half) + 1
    grow = ItemStream(grow_path, None)
    with open(grow_path, "wb") as fh:
        fh.write(raw[:split])
    grow.refresh()
    with open(grow_path, "ab") as fh:
        fh.write(raw[split:])
    grow.refresh()

    assert len(grow.items) == len(whole.items)
    assert [it.kind for it in grow.items] == [it.kind for it in whole.items]


def test_partial_last_line_ignored_until_newline(tmp_path):
    from helpers.jsonl import fixture_path
    lines = open(fixture_path("basic.jsonl"), "rb").read().splitlines(keepends=True)
    p = os.path.join(str(tmp_path), "s.jsonl")
    body = b"".join(lines[:-1])
    last = lines[-1].rstrip(b"\n")   # last line without trailing newline

    with open(p, "wb") as fh:
        fh.write(body + last)
    s = ItemStream(p, None)
    s.refresh()
    n_before = len(s.items)

    # append the newline; the previously-partial line is now complete
    with open(p, "ab") as fh:
        fh.write(b"\n")
    s.refresh()
    assert len(s.items) >= n_before


def test_shrink_triggers_reset(tmp_path):
    from helpers.jsonl import fixture_path
    raw = open(fixture_path("basic.jsonl"), "rb").read()
    p = os.path.join(str(tmp_path), "s.jsonl")
    with open(p, "wb") as fh:
        fh.write(raw)
    s = ItemStream(p, None)
    s.refresh()
    assert len(s.items) == 5
    assert s.offset > 0

    # Rewrite with a single short prompt line -> file shrinks -> _reset.
    short = (b'{"type":"user","cwd":"/x","timestamp":"2026-01-01T10:00:00.000Z",'
             b'"message":{"role":"user","content":"hi"}}\n')
    with open(p, "wb") as fh:
        fh.write(short)
    s.refresh()
    assert s.offset == len(short)
    assert len(s.items) == 1
    assert s.items[0].kind == "prompt"


# --------------------------------------------------------------------------
# malformed.jsonl — degrade, never crash
# --------------------------------------------------------------------------

def test_malformed_does_not_raise(session):
    stream = session("malformed.jsonl")  # refresh already called; no exception
    # only the valid, non-meta, prompt-bearing lines survive
    prompts = [it for it in stream.items if it.kind == "prompt"]
    texts = [it.text for it in prompts]
    assert "meta message ignored" not in texts
    # the trailing partial line ("partial last line...") is dropped
    assert not any("partial last line" in (t or "") for t in texts)


def test_malformed_parses_valid_lines(session):
    stream = session("malformed.jsonl")
    # at least the first valid user prompt is parsed
    assert any(it.kind == "prompt" for it in stream.items)


# --------------------------------------------------------------------------
# turns() grouping + is_turn_complete
# --------------------------------------------------------------------------

def test_turns_lead_grouping(session):
    stream = session("lead_items.jsonl")
    lead, turns = stream.turns()
    assert len(lead) == 1        # the pre-prompt tool_use is a lead item
    assert len(turns) == 1       # exactly one prompt turn


def test_is_turn_complete_basic(session):
    stream = session("basic.jsonl")
    assert stream.is_turn_complete() is True


def test_is_turn_complete_inprogress(session):
    stream = session("inprogress.jsonl")
    assert stream.is_turn_complete() is False
