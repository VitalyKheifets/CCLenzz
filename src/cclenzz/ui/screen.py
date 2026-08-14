from __future__ import annotations

"""The ``Screen`` seam: a tiny protocol the draw layer targets, a curses adapter
for production, and the shared cell-clipping ``put`` helper. ``FakeScreen`` (in
tests/helpers) is the headless substitute."""

from typing import Protocol

from ..textutil import clip_cells


class Screen(Protocol):
    def getmaxyx(self): ...
    def addstr(self, y, x, s, attr) -> None: ...
    def erase(self): ...
    def refresh(self): ...


class CursesScreen:
    """Wraps a curses ``stdscr``, converting ``curses.error`` at the edges into
    silent drops exactly where the old inline ``put`` did."""

    def __init__(self, stdscr):
        import curses
        self._stdscr = stdscr
        self._curses = curses

    def getmaxyx(self):
        return self._stdscr.getmaxyx()

    def addstr(self, y, x, s, attr):
        try:
            self._stdscr.addstr(y, x, s, attr)
        except self._curses.error:
            pass

    def erase(self):
        self._stdscr.erase()

    def refresh(self):
        self._stdscr.refresh()


def put(screen, caps, y, x, text, attr, maxx=None):
    """Clip ``text`` to the available cells and draw it. Returns the next x."""
    h, w = screen.getmaxyx()
    if maxx is None:
        maxx = w
    if y < 0 or y >= h or x < 0:
        return x
    avail = maxx - x
    if avail <= 0:
        return x
    clipped, cw = clip_cells(text, avail, caps.ambiwidth)
    if not clipped:
        return x
    screen.addstr(y, x, clipped, attr)
    return x + cw
