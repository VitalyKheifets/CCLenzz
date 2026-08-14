from __future__ import annotations

"""Per-tab and transient-toast view state."""

import os
import time

from ..model import ItemStream
from ..subagents import refresh_subtree


class Toast:
    __slots__ = ("text", "token", "born", "ttl")

    def __init__(self, text, token="fg", ttl=2.5):
        self.text = text
        self.token = token
        self.born = time.time()
        self.ttl = ttl

    def alive(self):
        return (time.time() - self.born) < self.ttl

    def faded(self):
        return (time.time() - self.born) > max(1.5, self.ttl - 1.0)


class Tab:
    """Per-session view state."""
    __slots__ = ("session", "stream", "expanded", "folded", "cat_filter",
                 "errors_only", "following", "stick", "cur", "top",
                 "last_mtime", "unread", "new_since_release", "owner_at_cursor",
                 "search", "search_active", "matches", "match_i",
                 "show_ts", "wrap_detail",
                 "audit_by_prompt", "audit_flagged", "audit_signature",
                 "audit_deltas", "audit_cost", "audit_dirty", "audit_folded",
                 "explain",          # dict: id(item) -> ExplainRec
                 "_row_cache")

    def __init__(self, session, follow):
        self.session = session
        self.stream = ItemStream(session.path, session.cwd)
        self.stream.refresh()
        self.expanded = set()
        self.folded = set()
        self.cat_filter = None
        self.errors_only = False
        self.following = follow
        self.stick = True
        self.cur = 0
        self.top = 0
        try:
            self.last_mtime = os.path.getmtime(session.path)
        except OSError:
            self.last_mtime = 0
        self.unread = 0
        self.new_since_release = 0
        self.owner_at_cursor = None
        self.search = ""
        self.search_active = False
        self.matches = []
        self.match_i = 0
        self.show_ts = False
        self.wrap_detail = True
        self.audit_by_prompt = {}
        self.audit_flagged = set()
        self.audit_signature = None
        self.audit_deltas = {}          # id(prompt) -> (delta, born_time)
        self.audit_cost = 0.0
        self.audit_dirty = False
        self.audit_folded = set()       # id(prompt) -> derivation view collapsed
        self.explain = {}               # id(item) -> ExplainRec (see §3.1)
        self._row_cache = {}

    @property
    def items(self):
        return self.stream.items

    def reload(self):
        changed = self.stream.refresh()
        refresh_subtree(self.stream.items)
        try:
            self.last_mtime = os.path.getmtime(self.session.path)
        except OSError:
            pass
        return changed
