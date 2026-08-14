from __future__ import annotations

"""Sub-agent transcript resolver — inline a sub-agent's full internal steps
(data layer, unchanged from v1)."""

import os
import re

from .model import ItemStream

SUBAGENT_MAX_DEPTH = 5            # recursion cap when inlining nested sub-agents

AGENT_TOOLS = ("Agent", "Task")
_AGENTID_RE = re.compile(r"agentId:\s*([A-Za-z0-9]+)")
_OUTPUT_RE = re.compile(r"output_file:\s*(\S+)")


def is_agent_launch(item):
    if item is None or item.kind != "tool":
        return False
    name = item.name or ""
    return name in AGENT_TOOLS or name.startswith("Task")


def parse_subagent_meta(result_text):
    if not result_text:
        return (None, None)
    aid = _AGENTID_RE.search(result_text)
    out = _OUTPUT_RE.search(result_text)
    return (aid.group(1) if aid else None, out.group(1) if out else None)


def subagent_kind(item):
    if not is_agent_launch(item) or item.result is None:
        return None
    _aid, out = parse_subagent_meta(item.result)
    if out:
        return "async" if os.path.exists(out) else "unavailable"
    return "sync"


def resolve_subagent(item, recursive=False, visited=None, depth=0):
    if item is None or item.resolved or not is_agent_launch(item):
        if item is not None:
            item.resolved = True
        return
    item.resolved = True
    aid, out = parse_subagent_meta(item.result)
    item.agent_id = aid
    if not out:
        item.sub_kind = "sync" if item.result is not None else None
        item.bump()
        return
    item.output_file = out
    if not os.path.exists(out):
        item.sub_kind = "unavailable"
        item.bump()
        return
    item.sub_kind = "async"
    stream = ItemStream(out, None)
    stream.refresh()
    item.sub_stream = stream
    item.children = stream.items
    item.bump()
    if recursive and depth + 1 < SUBAGENT_MAX_DEPTH:
        if visited is None:
            visited = set()
        if aid:
            if aid in visited:
                return
            visited.add(aid)
        for child in item.children:
            if is_agent_launch(child):
                resolve_subagent(child, recursive=True,
                                 visited=visited, depth=depth + 1)


def refresh_subtree(items):
    for it in items:
        if it.sub_stream is not None:
            if it.sub_stream.refresh():
                it.bump()
        if it.children:
            refresh_subtree(it.children)


def subtree_quiet(items):
    for it in items:
        if it.sub_stream is not None and not it.sub_stream.is_turn_complete(idle_ok=True):
            return False
        if it.children and not subtree_quiet(it.children):
            return False
    return True
