from __future__ import annotations

"""Structured parsing (Item / ItemStream) — the core data layer.

Crash-proof on schema drift: malformed JSON lines are silently skipped, a
partial last line is ignored, and the parser never raises on session data."""

import json
import os

from .classify import classify_tool, item_label
from .textutil import parse_ts

CATEGORIES = ["prompt", "read", "edit", "bash", "search",
              "mcp", "agent", "web", "skill", "artifact", "other"]


def result_to_text(res):
    if res is None:
        return None
    if isinstance(res, str):
        return res
    if isinstance(res, list):
        parts = []
        for b in res:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "tool_reference":
                    parts.append(f"[tool_reference: {b.get('tool_name')}]")
                else:
                    parts.append(json.dumps(b, ensure_ascii=False)[:300])
            else:
                parts.append(str(b))
        return "\n".join(p for p in parts if p)
    return str(res)


def extract_user_text(event):
    """Return the human prompt text for a 'user' event, or None if it's just a
    tool_result / meta / attachment-carrying message."""
    if event.get("isMeta"):
        return None
    msg = event.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        text = " ".join(p for p in parts if p).strip()
        return text or None
    return None


class Item:
    """One printable topic with everything needed for expand/filter/color."""
    __slots__ = ("kind", "category", "tool", "arg", "arg_kind", "text",
                 "name", "input", "result", "is_error", "tool_use_id",
                 "ts_start", "ts_end", "rev",
                 "children", "agent_id", "output_file", "sub_kind",
                 "sub_stream", "resolved",
                 "_diff", "_churn")

    def __init__(self, kind, category, tool, arg, arg_kind="text", text=None,
                 name=None, tool_input=None, tool_use_id=None, ts_start=None):
        self.kind = kind
        self.category = category
        self.tool = tool
        self.arg = arg
        self.arg_kind = arg_kind
        self.text = text
        self.name = name
        self.input = tool_input
        self.result = None
        self.is_error = False
        self.tool_use_id = tool_use_id
        self.ts_start = ts_start
        self.ts_end = None
        self.rev = 0
        self.children = []
        self.agent_id = None
        self.output_file = None
        self.sub_kind = None
        self.sub_stream = None
        self.resolved = False
        self._diff = None
        self._churn = None

    @property
    def label(self):
        return item_label(self)

    @property
    def duration(self):
        if self.ts_start is None or self.ts_end is None:
            return None
        d = self.ts_end - self.ts_start
        return d if d >= 0 else None

    def bump(self):
        self.rev += 1


class ItemStream:
    """Incremental reader for one session file (data layer, unchanged), plus
    per-item timestamps/revisions and turn grouping (§4)."""

    def __init__(self, path, cwd):
        self.path = path
        self.cwd = cwd
        self.offset = 0
        self.items = []
        self.results = {}
        self.by_id = {}
        self.last_event_type = None
        self.last_stop_reason = None
        self.pending_tools = set()
        self.says = []
        self._turns_cache = None
        self._turns_len = -1

    def _reset(self):
        self.offset = 0
        self.items = []
        self.results = {}
        self.by_id = {}
        self.last_event_type = None
        self.last_stop_reason = None
        self.pending_tools = set()
        self.says = []
        self._turns_cache = None
        self._turns_len = -1

    def refresh(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return False
        if size < self.offset:
            self._reset()
        if size == self.offset:
            return False
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read()
        except OSError:
            return False
        nl = chunk.rfind(b"\n")
        if nl == -1:
            return False
        consumed = chunk[: nl + 1]
        self.offset += len(consumed)
        changed = False
        for line in consumed.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            changed = self._ingest(o) or changed
        return changed

    def _ingest(self, o):
        t = o.get("type")
        changed = False
        ts = parse_ts(o.get("timestamp"))

        if self.cwd is None and o.get("cwd"):
            self.cwd = o.get("cwd")

        if t in ("user", "assistant") and not o.get("isMeta"):
            self.last_event_type = t
            if t == "assistant":
                self.last_stop_reason = (o.get("message") or {}).get("stop_reason")

        if t == "user":
            msg = o.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                for b in msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tid = b.get("tool_use_id")
                        if not tid:
                            continue
                        self.pending_tools.discard(tid)
                        payload = (result_to_text(b.get("content")),
                                   bool(b.get("is_error")))
                        self.results[tid] = payload
                        it = self.by_id.get(tid)
                        if it is not None:
                            it.result, it.is_error = payload
                            it.ts_end = ts
                            it.bump()
                            changed = True
            text = extract_user_text(o)
            if text:
                self.items.append(Item("prompt", "prompt", None, None,
                                       text=text, ts_start=ts))
                self._turns_cache = None
                changed = True

        elif t == "assistant" and not o.get("isMeta"):
            msg = o.get("message") or {}
            for b in msg.get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "text":
                    say = (b.get("text") or "").strip()
                    if say:
                        self.says.append((len(self.items), say))
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    cat, tool, arg, akind = classify_tool(
                        b.get("name"), b.get("input"), self.cwd)
                    it = Item("tool", cat, tool, arg, akind,
                              name=b.get("name"), tool_input=b.get("input"),
                              tool_use_id=b.get("id"), ts_start=ts)
                    if it.tool_use_id in self.results:
                        it.result, it.is_error = self.results[it.tool_use_id]
                    elif it.tool_use_id:
                        self.pending_tools.add(it.tool_use_id)
                    if it.tool_use_id:
                        self.by_id[it.tool_use_id] = it
                    self.items.append(it)
                    self._turns_cache = None
                    changed = True
        return changed

    def is_turn_complete(self, idle_ok=True):
        if self.last_event_type != "assistant":
            return False
        if self.last_stop_reason == "tool_use":
            return False
        if self.pending_tools:
            return False
        return bool(idle_ok)

    def turns(self):
        """(lead_items, [(prompt_item, [child_items]), …]). Cached until items
        change (§4.3)."""
        if self._turns_cache is not None and self._turns_len == len(self.items):
            return self._turns_cache
        lead = []
        turns = []
        cur = None
        for it in self.items:
            if it.kind == "prompt":
                cur = (it, [])
                turns.append(cur)
            elif cur is None:
                lead.append(it)
            else:
                cur[1].append(it)
        self._turns_cache = (lead, turns)
        self._turns_len = len(self.items)
        return self._turns_cache
