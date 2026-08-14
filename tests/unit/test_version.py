"""``__version__`` plumbing (§Phase 1). ``__version__`` is resolved from package
metadata with a hardcoded fallback for source checkouts / the .pyz zipapp;
``VERSION`` is the backwards-compatible alias every version surface reads. Both
must agree, and ``--version`` must print exactly ``cclenzz <version>`` on exit 0."""

import importlib.metadata
import re

import cclenzz
from cclenzz.cli import main


def test_version_and_alias_agree():
    assert cclenzz.VERSION == cclenzz.__version__
    assert isinstance(cclenzz.__version__, str) and cclenzz.__version__


def test_version_matches_installed_metadata():
    # The test suite runs against the installed (editable) distribution, so the
    # metadata path — not the fallback — is what resolves here.
    assert cclenzz.__version__ == importlib.metadata.version("cclenzz")


def test_fallback_is_valid_semver():
    # The hardcoded fallback in __init__ (used by the zipapp, which carries no
    # dist-info) must be a plain X.Y.Z that release.sh keeps in sync.
    m = re.search(r'__version__ = "([^"]+)"', open(cclenzz.__file__, encoding="utf-8").read())
    assert m, "no hardcoded __version__ fallback found in cclenzz/__init__.py"
    parts = m.group(1).split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_cli_version_flag(capsys):
    rc = main(["--version"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == f"cclenzz {cclenzz.__version__}"
