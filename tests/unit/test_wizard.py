"""Setup wizard: `_wizard_select` selection logic via a scripted KeyReader,
`_default_idx`, and the non-tty short-circuit in `run_wizard`."""

from cclenzz.wizard import _default_idx, _wizard_select, run_wizard

OPTIONS = [("a", "A", ""), ("b", "B", ""), ("c", "C", "")]


class ScriptedKeyReader:
    """A KeyReader test double: read_key() pops scripted tokens; the context
    manager hooks are no-ops (no real terminal is touched)."""

    def __init__(self, keys):
        self.keys = list(keys)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read_key(self):
        return self.keys.pop(0)


def _select(keys, caps, default=0):
    return _wizard_select("t", OPTIONS, default, caps, False,
                          reader=ScriptedKeyReader(keys))


# --------------------------------------------------------------------------- #
def test_down_then_enter_selects_next(caps_unicode_dark, capsys):
    assert _select(["down", "enter"], caps_unicode_dark) == 1
    capsys.readouterr()                           # swallow the ANSI output


def test_enter_returns_default(caps_unicode_dark, capsys):
    assert _select(["enter"], caps_unicode_dark) == 0
    capsys.readouterr()


def test_abort_returns_none(caps_unicode_dark, capsys):
    assert _select(["abort"], caps_unicode_dark) is None
    capsys.readouterr()


def test_digit_jump_then_enter(caps_unicode_dark, capsys):
    assert _select(["2", "enter"], caps_unicode_dark) == 1
    capsys.readouterr()


def test_up_wraps_to_last(caps_unicode_dark, capsys):
    assert _select(["up", "enter"], caps_unicode_dark, default=0) == 2
    capsys.readouterr()


# ---- _default_idx -------------------------------------------------------- #
def test_default_idx_found():
    assert _default_idx([("x", "X", ""), ("y", "Y", "")], "y", 0) == 1


def test_default_idx_missing_uses_fallback():
    assert _default_idx([("x", "X", ""), ("y", "Y", "")], "z", 7) == 7


# ---- run_wizard non-tty -------------------------------------------------- #
def test_run_wizard_non_tty_returns_none(tmp_path, capsys):
    # under pytest stdin/stdout are not ttys, so the wizard short-circuits.
    assert run_wizard({}, str(tmp_path / "config.toml")) is None
    capsys.readouterr()
