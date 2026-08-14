from __future__ import annotations

"""Stable cross-run identity (FEATURE-session-persistence.md §4). Persisted
results are keyed by content-derived stable keys, never id(item), so they survive
a restart and re-attach to freshly parsed items."""

import hashlib

from .model import result_to_text
from .subagents import is_agent_launch, resolve_subagent


def item_key(item, prompt_ordinal=None):
    """Stable, cross-run identity for one Item (§4).
       tool   -> 't:' + tool_use_id            (globally unique, from the JSONL)
       prompt -> 'p:' + ordinal + ':' + hash8  (ordinal disambiguates repeats)
       else   -> None (unkeyable -> never persisted)."""
    if item is None:
        return None
    if item.kind == "tool" and item.tool_use_id:
        return "t:" + item.tool_use_id
    if item.kind == "prompt":
        h = hashlib.sha1((item.text or "").encode("utf-8")).hexdigest()[:8]
        return f"p:{prompt_ordinal}:{h}"
    return None


def item_sig(item):
    """Cheap content signature to detect that the underlying line changed since a
    result was made (§5.2). Pairs with item.rev for staleness (§6.3)."""
    res = item.result if isinstance(item.result, str) else result_to_text(item.result)
    raw = f"{item.label}|{(res or '')[:400]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def _iter_all_items(stream):
    """Every item in the session — lead items, turn kids, and resolved sub-agent
    children (recursively). Sub-agents are resolved on demand so their tool ids
    are keyable; resolution degrades safely when the transcript is gone."""
    visited = set()

    def walk(items):
        for it in items:
            yield it
            if is_agent_launch(it):
                resolve_subagent(it, recursive=True, visited=visited)
                if it.children:
                    yield from walk(it.children)

    yield from walk(stream.items)


def build_key_index(tab):
    """key -> Item, for every keyable item in the session (incl. sub-agents).
    The single bridge between the durable key space (on disk) and the live object
    space the renderer reads (§4.1)."""
    idx = {}
    _lead, turns = tab.stream.turns()
    # tools anywhere (lead items, turn kids, resolved sub-agent children)
    for it in _iter_all_items(tab.stream):
        k = item_key(it)
        if k:
            idx[k] = it
    # prompts, numbered exactly as build_audit_transcript numbers the main turns
    for ordinal, (p, _kids) in enumerate(turns, start=1):
        idx[item_key(p, prompt_ordinal=ordinal)] = p
    return idx


def _prompt_ordinal_of(tab, item):
    """1-based ordinal of a prompt among the session's main turns, matching
    build_key_index's numbering. None for non-prompt items."""
    if item is None or item.kind != "prompt":
        return None
    _lead, turns = tab.stream.turns()
    for ordinal, (p, _kids) in enumerate(turns, start=1):
        if p is item:
            return ordinal
    return None


def owning_prompt(tab, item):
    """The prompt Item that governs this item's turn, or the item itself when it
    is a prompt. None for a lead item that precedes the first prompt."""
    if item.kind == "prompt":
        return item
    _lead, turns = tab.stream.turns()
    for (p, kids) in turns:
        if item is p or item in kids:
            return p
    return None
