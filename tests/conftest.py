import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tests"))

from helpers.jsonl import fixture_path, materialize  # noqa: E402
from helpers.sandbox import Sandbox  # noqa: E402

from cclenzz.model import ItemStream  # noqa: E402
from cclenzz.termcaps import Caps  # noqa: E402


def _caps(**over):
    base = dict(color="c256", glyphs="unicode", ambiwidth=1, mouse=False,
                osc8=False, osc52=True, title=False, bg="dark", is_tty=False,
                term="xterm-256color", term_program="", curses_colors=256,
                can_change=False)
    base.update(over)
    return Caps(**base)


@pytest.fixture
def caps_unicode_dark():
    return _caps()


@pytest.fixture
def caps_ascii():
    return _caps(glyphs="ascii", color="mono")


@pytest.fixture
def caps_mono():
    return _caps(color="mono")


@pytest.fixture
def make_caps():
    return _caps


@pytest.fixture
def session(tmp_path):
    """Materialize an ItemStream over one fixture file in a tmp dir."""
    def _make(name):
        dst = materialize(name, str(tmp_path))
        s = ItemStream(dst, None)
        s.refresh()
        return s
    return _make


@pytest.fixture
def sandbox(tmp_path):
    def _make(**kw):
        return Sandbox(tmp_path, **kw)
    return _make


@pytest.fixture
def fake_judge():
    """A scripted Judge recording calls; returns canned result dicts."""
    class FakeJudge:
        def __init__(self):
            self.audit_calls = []
            self.explain_calls = []
            self.audit_result = None
            self.explain_result = None

        def audit(self, transcript, model=None, cancel=None):
            self.audit_calls.append((transcript, model))
            return self.audit_result

        def explain(self, context, model=None, cancel=None):
            self.explain_calls.append((context, model))
            return self.explain_result
    return FakeJudge()
