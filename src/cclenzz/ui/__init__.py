from __future__ import annotations

"""Curses TUI — presentation layer. Row building (``rows.py``), key normalization
(``keys.py``) and per-key state transitions (``controller.py``) are curses-free
and headless-testable; only ``palette``/``screen``/``draw``/``tui``/``picker``/
``help``/``external`` touch curses."""
