from __future__ import annotations

"""Resolve color tokens to curses attributes per Caps.color / Caps.bg."""

from ..ansi import RGB_, _hex_rgb
from .style import Style


class Palette:
    """Resolve color tokens to curses attributes per Caps.color / Caps.bg.

    Also owns the ``Style`` → curses translation (§5.4) so ``ui/draw.py`` can map
    row-data emphasis flags to real curses attributes without importing curses
    itself."""

    def __init__(self, caps):
        import curses
        self.caps = caps
        self.mode = caps.color
        self._curses = curses
        # Exposed so curses-free draw code can reach these specific attrs.
        self.A_BOLD = curses.A_BOLD
        self.A_DIM = curses.A_DIM
        self.A_REVERSE = curses.A_REVERSE
        self._pairs = {}
        self._next_pair = 1
        self._next_color = 16
        self._color_num = {}     # token -> curses color number (fg or bg)
        self._c16 = {}           # token -> (curses_color, extra_attr)
        self._max_pairs = 0
        self._build()

    def _build(self):
        curses = self._curses
        if self.mode == "mono":
            return
        try:
            self._max_pairs = curses.COLOR_PAIRS - 1
        except Exception:
            self._max_pairs = 63
        light = (self.caps.bg == "light")
        rgb_ok = (self.mode == "rgb" and curses.can_change_color()
                  and getattr(curses, "COLORS", 0) >= 256)
        if not rgb_ok and self.mode == "rgb":
            self.mode = "c256"       # honesty over vanity (§3.2 rule)

        if self.mode == "rgb":
            for token, spec in RGB_.items():
                h = spec[0] if (not light or spec[1] is None) else spec[1]
                try:
                    r, g, b = _hex_rgb(h)
                    n = self._next_color
                    self._next_color += 1
                    curses.init_color(n, r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)
                    self._color_num[token] = n
                except Exception:
                    self._color_num[token] = -1
        elif self.mode == "c256":
            for token, spec in RGB_.items():
                idx = spec[2] if (not light or spec[3] is None) else spec[3]
                self._color_num[token] = idx if idx is not None else -1
        else:  # c16
            names = {"default": -1, "black": curses.COLOR_BLACK, "red": curses.COLOR_RED,
                     "green": curses.COLOR_GREEN, "yellow": curses.COLOR_YELLOW,
                     "blue": curses.COLOR_BLUE, "magenta": curses.COLOR_MAGENTA,
                     "cyan": curses.COLOR_CYAN, "white": curses.COLOR_WHITE}
            for token, spec in RGB_.items():
                col = names.get(spec[4], -1) if spec[4] else -1
                extra = 0
                if "BOLD" in spec[5]:
                    extra |= curses.A_BOLD
                if "DIM" in spec[5]:
                    extra |= curses.A_DIM
                self._c16[token] = (col, extra)

    def _pair(self, fg_num, bg_num):
        curses = self._curses
        key = (fg_num, bg_num)
        p = self._pairs.get(key)
        if p is not None:
            return p
        if self._next_pair > self._max_pairs:
            return 0
        pid = self._next_pair
        self._next_pair += 1
        try:
            curses.init_pair(pid, fg_num, bg_num)
        except Exception:
            self._pairs[key] = 0
            return 0
        attr = curses.color_pair(pid)
        self._pairs[key] = attr
        return attr

    def attr(self, token, sel=False, extra=0, bg_token=None):
        curses = self._curses
        if self.mode == "mono":
            a = extra
            if token == "error" or token == "cat.prompt" or token == "accent":
                a |= curses.A_BOLD
            if sel:
                a |= curses.A_BOLD
            return a
        if self.mode == "c16":
            col, ex = self._c16.get(token, self._c16.get("fg", (-1, 0)))
            a = self._pair(col, -1) | ex | extra
            if sel:
                a |= curses.A_BOLD
            return a
        # rgb / c256
        fg = self._color_num.get(token, -1)
        bg = -1
        if bg_token:
            bg = self._color_num.get(bg_token, -1)
        elif sel:
            bg = self._color_num.get("sel.bg", -1)
        return self._pair(fg, bg) | extra

    def style_extra(self, style):
        """Map a ``Style`` flag set to the equivalent OR of curses attributes."""
        e = 0
        if style & Style.BOLD:
            e |= self._curses.A_BOLD
        if style & Style.DIM:
            e |= self._curses.A_DIM
        if style & Style.REVERSE:
            e |= self._curses.A_REVERSE
        return int(e)

    def bg_attr(self, bg_token):
        """Attribute that fills a cell with a background color (fg=fg token)."""
        if self.mode in ("mono", "c16"):
            return 0
        fg = self._color_num.get("fg", -1)
        bg = self._color_num.get(bg_token, -1)
        return self._pair(fg, bg)
