from __future__ import annotations

"""Curses-free text-emphasis flags. ``RowBuilder`` emits these on spans instead
of raw ``curses.A_*`` attributes; ``ui/draw.py`` maps them back to curses at draw
time, yielding bit-identical attributes (§5.4)."""

import enum


class Style(enum.IntFlag):
    NONE = 0
    BOLD = 1
    DIM = 2
    REVERSE = 4
