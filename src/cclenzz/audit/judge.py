from __future__ import annotations

"""The Judge seam: shell out to ``claude -p`` as a pure judge (audit) or prose
explainer. ``ui/jobs.py`` and tests depend on the ``Judge`` protocol, never on
subprocess details. Return-dict shapes and every error string are preserved."""

import json
import subprocess
import time
from typing import Protocol

from ..textutil import _trunc
from .explain import _clip_explain
from .prompts import (AUDIT_RUBRIC, AUDIT_SCHEMA, AUDIT_TASK_PREFIX,
                      EXPLAIN_SYSTEM, EXPLAIN_TASK_PREFIX)

AUDIT_TIMEOUT = 600              # seconds before we give up on the `claude` call
EXPLAIN_TIMEOUT = 120           # seconds; a single item is fast — fail loud, not slow

_DISALLOWED_TOOLS = "Bash,Edit,Write,Read,Grep,Glob,WebFetch,WebSearch,Agent,Task"


def _looks_like_auth_error(msg):
    """True when `claude` failed because we're not authenticated (401 / expired
    or missing OAuth token / invalid key), rather than a transcript problem."""
    if not msg:
        return False
    m = str(msg).lower()
    if "401" in m or "unauthorized" in m:
        return True
    signals = (
        "authentication_error", "authentication error", "invalid api key",
        "invalid x-api-key", "oauth token has expired", "token has expired",
        "please run /login", "run `/login`", "not logged in", "please log in",
        "please sign in", "log in with", "credentials",
    )
    return any(s in m for s in signals)


def _auth_error_result(model, claude_bin, cost=None):
    """A run_audit result telling the user to log in, with the exact command."""
    return {
        "ok": False, "auth": True,
        "error": (f"Not logged in to claude. {claude_bin} auth login  to sign in, "
                  f"{claude_bin} auth status  to check."),
        "verdicts": [], "cost": cost, "model": model, "cancelled": False,
    }


def _kill_group(proc):
    try:
        import os
        import signal
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


class Judge(Protocol):
    def audit(self, transcript: str, model: "str | None",
              cancel: "object | None") -> dict: ...

    def explain(self, context: str, model: "str | None",
                cancel: "object | None") -> dict: ...


class ClaudeCliJudge:
    """The production ``Judge``: runs the ``claude`` CLI found on PATH (reusing
    its login — cclenzz holds no API key)."""

    def __init__(self, claude_bin, audit_model_default, explain_model_default):
        self.claude_bin = claude_bin
        self.audit_model_default = audit_model_default
        self.explain_model_default = explain_model_default

    def audit(self, transcript, model=None, cancel=None):
        """Shell out to `claude -p` as a pure judge and parse its verdicts. Never
        raises. When `cancel` is set, terminate the subprocess group and return a
        cancelled result."""
        cancel_event = cancel
        claude_bin = self.claude_bin
        model = model or self.audit_model_default
        cmd = [
            claude_bin, "-p",
            "--model", model,
            "--output-format", "json",
            "--json-schema", json.dumps(AUDIT_SCHEMA),
            "--disallowedTools",
            _DISALLOWED_TOOLS,
            "--append-system-prompt", AUDIT_RUBRIC,
            "--no-session-persistence",
        ]
        stdin = AUDIT_TASK_PREFIX + transcript
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, start_new_session=True)
        except FileNotFoundError:
            return {"ok": False, "error": f"`{claude_bin}` not found on PATH.",
                    "verdicts": [], "cost": None, "model": model, "cancelled": False}

        try:
            proc.stdin.write(stdin)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        deadline = time.time() + AUDIT_TIMEOUT
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    _kill_group(proc)
                    return {"ok": False, "error": "cancelled", "verdicts": [],
                            "cost": None, "model": model, "cancelled": True}
                if time.time() > deadline:
                    _kill_group(proc)
                    return {"ok": False, "error": f"audit timed out after {AUDIT_TIMEOUT}s.",
                            "verdicts": [], "cost": None, "model": model, "cancelled": False}

        out = (proc.stdout.read() if proc.stdout else "").strip()
        err = (proc.stderr.read() if proc.stderr else "").strip()
        if not out:
            msg = err or f"claude exited {proc.returncode}."
            if _looks_like_auth_error(msg):
                return _auth_error_result(model, claude_bin)
            return {"ok": False, "error": _trunc(msg, 200),
                    "verdicts": [], "cost": None, "model": model, "cancelled": False}
        try:
            env = json.loads(out)
        except (ValueError, json.JSONDecodeError):
            return {"ok": False, "error": "could not parse claude's JSON envelope.",
                    "verdicts": [], "cost": None, "model": model, "cancelled": False}
        if env.get("is_error"):
            emsg = str(env.get("result") or "claude reported an error.")
            if _looks_like_auth_error(emsg) or _looks_like_auth_error(err):
                return _auth_error_result(model, claude_bin, cost=env.get("total_cost_usd"))
            return {"ok": False,
                    "error": _trunc(emsg, 200),
                    "verdicts": [], "cost": env.get("total_cost_usd"),
                    "model": model, "cancelled": False}
        payload = env.get("result")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, json.JSONDecodeError):
                return {"ok": False, "error": "structured verdict was not valid JSON.",
                        "verdicts": [], "cost": env.get("total_cost_usd"),
                        "model": model, "cancelled": False}
        verdicts = (payload or {}).get("verdicts") if isinstance(payload, dict) else None
        if not isinstance(verdicts, list):
            return {"ok": False, "error": "no verdicts in the model's reply.",
                    "verdicts": [], "cost": env.get("total_cost_usd"),
                    "model": model, "cancelled": False}
        return {"ok": True, "error": None, "verdicts": verdicts,
                "cost": env.get("total_cost_usd"), "model": model, "cancelled": False}

    def explain(self, context, model=None, cancel=None):
        """Shell out to `claude -p` to explain ONE tool call in plain language.
        Near-clone of `audit`: no `--json-schema` (we want prose), a different
        system prompt, and a shorter timeout. Never raises. Returns
        {"ok": bool, "text": str|None, "error": str|None, "cost": float|None,
         "model": str, "cancelled": bool}."""
        cancel_event = cancel
        claude_bin = self.claude_bin
        model = model or self.explain_model_default
        cmd = [
            claude_bin, "-p",
            "--model", model,
            "--output-format", "json",
            "--disallowedTools",
            _DISALLOWED_TOOLS,
            "--append-system-prompt", EXPLAIN_SYSTEM,
            "--no-session-persistence",
        ]
        stdin = EXPLAIN_TASK_PREFIX + context

        def _fail(error, cost=None, cancelled=False):
            return {"ok": False, "text": None, "error": error, "cost": cost,
                    "model": model, "cancelled": cancelled}

        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, start_new_session=True)
        except FileNotFoundError:
            return _fail("claude not on PATH")

        try:
            proc.stdin.write(stdin)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        deadline = time.time() + EXPLAIN_TIMEOUT
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    _kill_group(proc)
                    return _fail("cancelled", cancelled=True)
                if time.time() > deadline:
                    _kill_group(proc)
                    return _fail(f"timed out after {EXPLAIN_TIMEOUT}s")

        out = (proc.stdout.read() if proc.stdout else "").strip()
        err = (proc.stderr.read() if proc.stderr else "").strip()
        if not out:
            msg = err or f"claude exited {proc.returncode}."
            if _looks_like_auth_error(msg):
                return _fail("run `claude` once to log in")
            return _fail(_trunc(msg, 200))
        try:
            env = json.loads(out)
        except (ValueError, json.JSONDecodeError):
            return _fail("could not parse claude's JSON envelope.")
        if env.get("is_error"):
            emsg = str(env.get("result") or "claude reported an error.")
            if _looks_like_auth_error(emsg) or _looks_like_auth_error(err):
                return _fail("run `claude` once to log in", cost=env.get("total_cost_usd"))
            return _fail(_trunc(emsg, 200), cost=env.get("total_cost_usd"))
        # No --json-schema: env["result"] is the final prose, not nested JSON.
        text = env.get("result")
        if not isinstance(text, str) or not text.strip():
            return _fail("empty explanation.", cost=env.get("total_cost_usd"))
        return {"ok": True, "text": _clip_explain(text), "error": None,
                "cost": env.get("total_cost_usd"), "model": model, "cancelled": False}
