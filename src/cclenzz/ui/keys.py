from __future__ import annotations

"""KeyEvent normalization. ``tui`` owns the ``curses`` module; it builds a
``KeySet`` of the relevant ``curses.KEY_*`` codes once and passes it down so the
controller can match keys without importing curses (§4/§5.7)."""


class KeySet:
    """A snapshot of the curses key codes the controller matches against."""

    __slots__ = ("UP", "DOWN", "NPAGE", "PPAGE", "HOME", "END", "ENTER",
                 "LEFT", "RIGHT", "BTAB", "RESIZE", "BACKSPACE", "MOUSE")

    def __init__(self, curses):
        self.UP = curses.KEY_UP
        self.DOWN = curses.KEY_DOWN
        self.NPAGE = curses.KEY_NPAGE
        self.PPAGE = curses.KEY_PPAGE
        self.HOME = curses.KEY_HOME
        self.END = curses.KEY_END
        self.ENTER = curses.KEY_ENTER
        self.LEFT = curses.KEY_LEFT
        self.RIGHT = curses.KEY_RIGHT
        self.BTAB = curses.KEY_BTAB
        self.RESIZE = curses.KEY_RESIZE
        self.BACKSPACE = curses.KEY_BACKSPACE
        self.MOUSE = curses.KEY_MOUSE


class FakeKeySet:
    """A KeySet with the standard code values, for headless controller tests
    (matches the values ncurses uses on Linux/macOS)."""

    __slots__ = KeySet.__slots__

    def __init__(self):
        self.UP = 259
        self.DOWN = 258
        self.NPAGE = 338
        self.PPAGE = 339
        self.HOME = 262
        self.END = 360
        self.ENTER = 343
        self.LEFT = 260
        self.RIGHT = 261
        self.BTAB = 353
        self.RESIZE = 410
        self.BACKSPACE = 263
        self.MOUSE = 409
