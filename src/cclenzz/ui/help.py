from __future__ import annotations

"""The keys overlay (`h`)."""

from ..textutil import clip_cells  # noqa: F401  (kept for parity with put usage)
from .screen import put

HELP_LINES = [
    ("", "cclenzz — keys"),
    ("j / k", "move one row"),
    ("Ctrl-D/U", "half page"),
    ("g / G", "top / bottom"),
    ("} / {", "next / prev prompt"),
    ("→ Enter", "open: unfold, then full prompt / detail"),
    ("←", "close: hide detail, then fold / parent"),
    ("→ ← Enter", "on audit badge: toggle detail"),
    ("z", "fold all turns"),
    ("] / [", "next / prev tab"),
    ("1-9", "tab N"),
    ("l / d", "picker / close tab"),
    ("e / c / C", "errors / category filter"),
    ("/ n N", "search / next / prev"),
    ("f / p", "follow / pause"),
    ("a / m / x", "audit / auto / cancel"),
    ("?", "explain line under cursor"),
    ("y / Y", "yank arg / detail"),
    ("o / O", "pager / editor"),
    ("t / w", "timestamps / wrap"),
    ("r / Ctrl-L", "reload / repaint"),
    ("h / q", "help / quit"),
    ("Esc", "dismiss (never quits)"),
]


def show_help(screen, pal, caps):
    """Blocking help overlay. Restores nothing (caller resets the timeout)."""
    import curses
    stdscr = screen._stdscr if hasattr(screen, "_stdscr") else screen
    stdscr.timeout(-1)
    lines = HELP_LINES
    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        top = max(0, (h - len(lines)) // 2)
        for i, (k, d) in enumerate(lines):
            y = top + i
            if y >= h - 1:
                break
            x = max(2, (w - 40) // 2)
            if k == "":
                put(screen, caps, y, x, d, pal.attr("accent", extra=curses.A_BOLD))
            else:
                put(screen, caps, y, x, f"{k:<10}", pal.attr("accent"))
                put(screen, caps, y, x + 11, d, pal.attr("fg"))
        put(screen, caps, h - 1, 2, "press any key to close",
            pal.attr("fg.dim"))
        stdscr.refresh()
        stdscr.getch()
        break
