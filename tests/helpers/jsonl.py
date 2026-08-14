"""Fixture materializer: copy a session fixture into a tmp dir, substituting
placeholders like {OUTPUT_FILE} for the subagent-transcript tests (§10.2)."""

import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSIONS = os.path.join(REPO, "tests", "fixtures", "sessions")


def fixture_path(name):
    return os.path.join(SESSIONS, name)


def materialize(name, dest_dir, subs=None, dest_name=None):
    """Read fixture `name`, apply `subs` (placeholder→value), write into
    dest_dir. Returns the written path."""
    with open(fixture_path(name), "r", encoding="utf-8") as fh:
        text = fh.read()
    for k, v in (subs or {}).items():
        text = text.replace("{" + k + "}", v)
    out = os.path.join(dest_dir, dest_name or name.replace(".tmpl", ""))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return out
