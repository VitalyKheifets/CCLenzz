from __future__ import annotations

"""cclenzz — Claude Code Monitor.

A live, tabbed terminal view of Claude Code sessions read straight from
``~/.claude/projects/*/*.jsonl``, plus an LLM "intent audit" that scores, per
prompt, whether the actions matched intent.

The runtime is stdlib-only. The program is organised as a layered package
(data → services → UI); see ``docs/FEATURE-modular-restructure.md``.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Single source of truth for the release version is ``pyproject.toml``;
# ``scripts/release.sh`` keeps the fallback below in sync with it. When cclenzz
# is installed as a distribution the version comes from package metadata; when
# it runs from a bare source checkout or the ``.pyz`` zipapp (which carries no
# ``*.dist-info``) the hardcoded fallback is used instead.
try:
    __version__ = _pkg_version("cclenzz")
except PackageNotFoundError:               # source checkout / zipapp
    __version__ = "1.0.0"

# Backwards-compatible alias: every surface that shows a version reads this
# constant (``--version``, the doctor banner, persisted sidecars).
VERSION = __version__
