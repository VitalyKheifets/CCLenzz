"""Byte-compare model-facing prompts and data tables against reference copies
captured from the current file (§11.6). When one of these fails, the port is
wrong — never edit the golden."""

import json
import os

from cclenzz.ansi import RGB_
from cclenzz.audit.prompts import (AUDIT_RUBRIC, AUDIT_SCHEMA, AUDIT_TASK_PREFIX,
                                   DEFECT_CODES, EXPLAIN_SYSTEM,
                                   EXPLAIN_TASK_PREFIX, GAP_CODES)
from cclenzz.configwrite import CONFIG_TEMPLATE
from cclenzz.glyphs import AMBI_KEYS, GLYPHS
from cclenzz.ui.help import HELP_LINES

REF = os.path.join(os.path.dirname(__file__), "reference")


def _ref(name):
    with open(os.path.join(REF, name), "r", encoding="utf-8") as fh:
        return fh.read()


def test_audit_rubric():
    assert AUDIT_RUBRIC == _ref("AUDIT_RUBRIC.txt")


def test_audit_task_prefix():
    assert AUDIT_TASK_PREFIX == _ref("AUDIT_TASK_PREFIX.txt")


def test_explain_system():
    assert EXPLAIN_SYSTEM == _ref("EXPLAIN_SYSTEM.txt")


def test_explain_task_prefix():
    assert EXPLAIN_TASK_PREFIX == _ref("EXPLAIN_TASK_PREFIX.txt")


def test_audit_schema():
    assert json.dumps(AUDIT_SCHEMA, sort_keys=True) == _ref("AUDIT_SCHEMA.json")


def test_defect_codes():
    assert json.dumps(DEFECT_CODES) == _ref("DEFECT_CODES.json")


def test_gap_codes():
    assert json.dumps(GAP_CODES) == _ref("GAP_CODES.json")


def test_glyphs():
    assert json.dumps(GLYPHS, sort_keys=True) == _ref("GLYPHS.json")


def test_ambi_keys():
    assert json.dumps(sorted(AMBI_KEYS)) == _ref("AMBI_KEYS.json")


def test_rgb_tokens():
    assert json.dumps(RGB_, sort_keys=True) == _ref("RGB_.json")


def test_config_template():
    assert CONFIG_TEMPLATE == _ref("CONFIG_TEMPLATE.txt")


def test_help_lines():
    assert json.dumps([list(x) for x in HELP_LINES]) == _ref("HELP_LINES.json")
