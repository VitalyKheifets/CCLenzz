"""Unit tests for cclenzz.subagents and cclenzz.identity."""

import os
import shutil

import pytest

from cclenzz.identity import (
    _prompt_ordinal_of,
    build_key_index,
    item_key,
    item_sig,
    owning_prompt,
)
from cclenzz.model import ItemStream
from cclenzz.subagents import (
    SUBAGENT_MAX_DEPTH,
    is_agent_launch,
    parse_subagent_meta,
    refresh_subtree,
    resolve_subagent,
    subagent_kind,
    subtree_quiet,
)

from helpers.jsonl import fixture_path, materialize


class _Tab:
    """Minimal tab stand-in: build_key_index / owning_prompt only use .stream."""
    def __init__(self, stream):
        self.stream = stream


# --------------------------------------------------------------------------
# parse_subagent_meta / is_agent_launch
# --------------------------------------------------------------------------

def test_parse_subagent_meta():
    text = "agentId: abc123\noutput_file: /tmp/x\nmore"
    assert parse_subagent_meta(text) == ("abc123", "/tmp/x")


def test_parse_subagent_meta_none():
    assert parse_subagent_meta(None) == (None, None)
    assert parse_subagent_meta("nothing here") == (None, None)


def test_subagent_max_depth():
    assert SUBAGENT_MAX_DEPTH == 5


# --------------------------------------------------------------------------
# async / sync / unavailable resolution
# --------------------------------------------------------------------------

def _async_parent(tmp_path):
    child = os.path.join(str(tmp_path), "child_agent.jsonl")
    shutil.copy(fixture_path("child_agent.jsonl"), child)
    parent = materialize("parent_agent.jsonl.tmpl", str(tmp_path),
                         subs={"OUTPUT_FILE": child})
    s = ItemStream(parent, None)
    s.refresh()
    return s, child


def _agent_item(stream):
    return next(it for it in stream.items if is_agent_launch(it))


def test_is_agent_launch(tmp_path):
    s, _child = _async_parent(tmp_path)
    agent = _agent_item(s)
    assert is_agent_launch(agent) is True
    assert is_agent_launch(s.items[0]) is False   # a prompt


def test_resolve_async(tmp_path):
    s, _child = _async_parent(tmp_path)
    agent = _agent_item(s)
    assert "output_file" in (agent.result or "")
    assert subagent_kind(agent) == "async"
    resolve_subagent(agent)
    assert agent.sub_kind == "async"
    assert agent.agent_id == "abc123"
    assert len(agent.children) == 2   # child's Grep tool + (grouped) items
    # child transcript's tool is inlined
    assert any(c.name == "Grep" for c in agent.children if c.kind == "tool")


def test_resolve_missing_output_unavailable(tmp_path):
    parent = materialize("parent_agent.jsonl.tmpl", str(tmp_path),
                         subs={"OUTPUT_FILE": "/no/such/path/child.jsonl"})
    s = ItemStream(parent, None)
    s.refresh()
    agent = _agent_item(s)
    assert subagent_kind(agent) == "unavailable"
    resolve_subagent(agent)
    assert agent.sub_kind == "unavailable"
    assert agent.children == []


def test_resolve_sync(tmp_path):
    parent = materialize("parent_sync.jsonl", str(tmp_path))
    s = ItemStream(parent, None)
    s.refresh()
    agent = _agent_item(s)
    assert subagent_kind(agent) == "sync"
    resolve_subagent(agent)
    assert agent.sub_kind == "sync"


def test_refresh_and_quiet_subtree(tmp_path):
    s, _child = _async_parent(tmp_path)
    agent = _agent_item(s)
    resolve_subagent(agent)
    # refresh_subtree must not raise; child transcript is complete -> quiet
    refresh_subtree(s.items)
    assert subtree_quiet(s.items) is True


# --------------------------------------------------------------------------
# identity — item_key / item_sig
# --------------------------------------------------------------------------

def test_item_key_tool(session):
    stream = session("basic.jsonl")
    read_tool = stream.items[1]
    assert item_key(read_tool) == "t:" + read_tool.tool_use_id


def test_item_key_prompt_ordinal_and_hash(session):
    stream = session("basic.jsonl")
    prompt = stream.items[0]
    key = item_key(prompt, prompt_ordinal=1)
    assert key.startswith("p:1:")
    hexpart = key.split(":")[2]
    assert len(hexpart) == 8
    int(hexpart, 16)   # valid hex


def test_item_key_none_for_unkeyable():
    from cclenzz.model import Item
    # a tool without a tool_use_id is unkeyable
    it = Item("tool", "other", "X", "", name="X", tool_use_id=None)
    assert item_key(it) is None


def test_build_key_index(session):
    stream = session("basic.jsonl")
    tab = _Tab(stream)
    idx = build_key_index(tab)
    # every tool id is present
    assert "t:t1" in idx
    assert "t:t2" in idx
    assert "t:t3" in idx
    # prompts numbered by ordinal
    assert any(k.startswith("p:1:") for k in idx)
    assert any(k.startswith("p:2:") for k in idx)
    assert idx["t:t1"] is stream.items[1]


def test_prompt_ordinal_of(session):
    stream = session("basic.jsonl")
    tab = _Tab(stream)
    assert _prompt_ordinal_of(tab, stream.items[0]) == 1
    assert _prompt_ordinal_of(tab, stream.items[3]) == 2
    # non-prompt -> None
    assert _prompt_ordinal_of(tab, stream.items[1]) is None


def test_owning_prompt(session):
    stream = session("basic.jsonl")
    tab = _Tab(stream)
    prompt1 = stream.items[0]
    read_tool = stream.items[1]
    assert owning_prompt(tab, read_tool) is prompt1
    assert owning_prompt(tab, prompt1) is prompt1


def test_item_sig_changes_with_result(session):
    stream = session("basic.jsonl")
    read_tool = stream.items[1]
    sig1 = item_sig(read_tool)
    read_tool.result = "something totally different"
    read_tool.bump()
    sig2 = item_sig(read_tool)
    assert sig1 != sig2
