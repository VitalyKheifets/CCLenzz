from __future__ import annotations

"""Text metrics — width, truncation, durations, clocks (by display cells)."""

import os
import re
import time
import unicodedata
from datetime import datetime, timezone

from .glyphs import ell

PROMPT_HINT_LEN = 48              # truncation length for the last-prompt hint column
KEY_ARG_LEN = 60                  # truncation length for a tool's key argument


def char_w(ch, ambiwidth=1):
    if unicodedata.combining(ch):
        return 0
    ea = unicodedata.east_asian_width(ch)
    if ea in ("W", "F"):
        return 2
    if ea == "A":
        return ambiwidth
    return 1


def disp_w(s, ambiwidth=1):
    return sum(char_w(c, ambiwidth) for c in (s or ""))


def clip_cells(s, n, ambiwidth=1):
    """Clip a string to at most n display cells. Returns (clipped, width)."""
    if n <= 0:
        return "", 0
    out = []
    w = 0
    for c in (s or ""):
        cw = char_w(c, ambiwidth)
        if w + cw > n:
            break
        out.append(c)
        w += cw
    return "".join(out), w


def trunc_end(s, n, ambiwidth=1):
    """Truncate at the end with an ellipsis (commands, queries, prose)."""
    s = (s or "").replace("\n", " ")
    if n <= 0:
        return ""
    if disp_w(s, ambiwidth) <= n:
        return s
    e = ell()
    ew = disp_w(e, ambiwidth)
    if n <= ew:
        clipped, _ = clip_cells(s, n, ambiwidth)
        return clipped
    clipped, _ = clip_cells(s, n - ew, ambiwidth)
    return clipped + e


def trunc_mid(path, n, ambiwidth=1):
    """Middle-truncate a path, preserving the basename (src/…/parser/stream.py)."""
    path = (path or "").replace("\n", " ")
    if n <= 0:
        return ""
    if disp_w(path, ambiwidth) <= n:
        return path
    e = ell()
    base = os.path.basename(path.rstrip("/")) or path
    if disp_w(base, ambiwidth) + disp_w(e, ambiwidth) + 1 >= n:
        return trunc_end(base, n, ambiwidth)
    tail = e + "/" + base
    head_budget = n - disp_w(tail, ambiwidth)
    head, _ = clip_cells(path, head_budget, ambiwidth)
    return head + tail


def fmt_dur(secs):
    """450ms · 1.2s · 12s · 1m04 · 2h13."""
    if secs is None:
        return ""
    if secs < 0:
        secs = 0
    if secs < 1:
        return f"{int(round(secs * 1000))}ms"
    if secs < 10:
        return f"{secs:.1f}s"
    if secs < 60:
        return f"{int(round(secs))}s"
    if secs < 3600:
        m = int(secs // 60)
        s = int(secs % 60)
        return f"{m}m{s:02d}"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    return f"{h}h{m:02d}"


def fmt_idle(mtime, now):
    """now · 3m · 1h · 2d (column-stable: 'just now' → 'now')."""
    delta = max(0, int(now - mtime))
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def fmt_clock(mtime):
    return time.strftime("%H:%M", time.localtime(mtime))


def fmt_clock_secs(epoch):
    return time.strftime("%H:%M:%S", time.localtime(epoch))


def parse_ts(s):
    """Parse an ISO-8601 timestamp to epoch seconds. 3.9-safe. None on failure."""
    if not s or not isinstance(s, str):
        return None
    try:
        s2 = s.strip()
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        # 3.9 fromisoformat wants exactly 3 or 6 fractional digits.
        m = re.match(r"^(.*\.\d+)(.*)$", s2)
        if m:
            frac = m.group(1)
            dot = frac.rfind(".")
            digits = frac[dot + 1:]
            if len(digits) not in (3, 6):
                digits = (digits + "000000")[:6]
            s2 = frac[:dot + 1] + digits + m.group(2)
        return datetime.fromisoformat(s2).timestamp()
    except Exception:
        try:
            return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc).timestamp()
        except Exception:
            return None


def iso_ts(epoch):
    if epoch is None:
        return None
    try:
        dt = datetime.fromtimestamp(epoch, timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int((epoch % 1) * 1000):03d}Z"
    except Exception:
        return None


def _first_line(s):
    s = (s or "").strip().splitlines()
    return s[0] if s else ""


def _trunc(s, n=KEY_ARG_LEN):
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"
