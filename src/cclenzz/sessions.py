from __future__ import annotations

"""Session discovery + metadata (lazy: §14.1). ``discover_sessions`` takes an
``AppPaths`` so the projects glob is injected, never a module global."""

import glob
import json
import os

from .model import extract_user_text

LIVE_MINUTES_DEFAULT = 5          # file mtime within this window == "open/live"
MAX_SESSIONS_DEFAULT = 40         # how many recent sessions to read for the picker


class Session:
    def __init__(self, path):
        self.path = path
        st = os.stat(path)
        self.mtime = st.st_mtime
        self.size = st.st_size
        self.session_id = os.path.splitext(os.path.basename(path))[0]
        self.dir_label = os.path.basename(os.path.dirname(path))
        self.cwd = None
        self.project = self._project_from_dir()
        self.title = None
        self.item_count = 0
        self.meta_loaded = False

    def _project_from_dir(self):
        seg = self.dir_label.rstrip("-").split("-")
        return seg[-1] if seg and seg[-1] else self.dir_label

    def read_meta(self):
        """Full read: cwd, a title hint and an exact item count."""
        custom_title = ai_title = last_prompt = first_prompt = None
        count = 0
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    t = o.get("type")
                    if self.cwd is None and o.get("cwd"):
                        self.cwd = o.get("cwd")
                    if t == "custom-title":
                        custom_title = o.get("customTitle")
                    elif t == "ai-title":
                        ai_title = o.get("aiTitle")
                    elif t == "last-prompt":
                        last_prompt = o.get("lastPrompt")
                    elif t == "user":
                        text = extract_user_text(o)
                        if text:
                            count += 1
                            if first_prompt is None:
                                first_prompt = text
                    elif t == "assistant":
                        msg = o.get("message") or {}
                        for b in msg.get("content", []) or []:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                count += 1
        except OSError:
            pass
        if self.cwd:
            self.project = os.path.basename(self.cwd.rstrip("/")) or self.project
        self.title = custom_title or ai_title or last_prompt or first_prompt or "(no prompt yet)"
        self.item_count = count
        self.meta_loaded = True
        return self

    def read_meta_fast(self, chunk=65536):
        """§14.1: metadata from head (cwd, first prompt) + tail (title events)
        reads only — no full walk, no exact item count."""
        custom_title = ai_title = last_prompt = first_prompt = None
        try:
            with open(self.path, "rb") as fh:
                head = fh.read(chunk)
                size = self.size
                if size > chunk * 2:
                    fh.seek(max(chunk, size - chunk))
                    tail = fh.read()
                else:
                    tail = b""
            for blob in (head, tail):
                for raw in blob.split(b"\n"):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        o = json.loads(raw.decode("utf-8", "replace"))
                    except (ValueError, json.JSONDecodeError):
                        continue
                    t = o.get("type")
                    if self.cwd is None and o.get("cwd"):
                        self.cwd = o.get("cwd")
                    if t == "custom-title":
                        custom_title = o.get("customTitle")
                    elif t == "ai-title":
                        ai_title = o.get("aiTitle")
                    elif t == "last-prompt":
                        last_prompt = o.get("lastPrompt")
                    elif t == "user" and first_prompt is None:
                        text = extract_user_text(o)
                        if text:
                            first_prompt = text
        except OSError:
            pass
        if self.cwd:
            self.project = os.path.basename(self.cwd.rstrip("/")) or self.project
        self.title = custom_title or ai_title or last_prompt or first_prompt or "(no prompt yet)"
        self.item_count = None            # exact count deliberately dropped (§14.1)
        self.meta_loaded = True
        return self


def discover_sessions(paths, max_sessions, fast=False):
    session_paths = glob.glob(paths.projects_glob)
    sessions = []
    for p in session_paths:
        try:
            sessions.append(Session(p))
        except OSError:
            continue
    sessions.sort(key=lambda s: s.mtime, reverse=True)
    if max_sessions and max_sessions > 0:
        sessions = sessions[:max_sessions]
    for s in sessions:
        if fast:
            s.read_meta_fast()
        else:
            s.read_meta()
    return sessions


def is_live(session, now, live_minutes):
    return (now - session.mtime) <= live_minutes * 60
