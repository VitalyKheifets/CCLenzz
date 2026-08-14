---
name: pr-preflight
description: Run CCLenzz's full pre-PR gate before opening a pull request. Invoked as /pr-preflight, or when the user asks to "get this PR ready", "run preflight", or "check this before I open a PR". Orchestrates code-reviewer → fixer → code-reviewer to zero findings, then runs the mechanical gate and prints a filled-in PR checklist.
---

# pr-preflight

You are the **orchestrator** of CCLenzz's contribution loop. Run the whole
pre-PR gate and report whether the change is ready to open as a PR. With no CI,
this is the paved road that makes a PR pass the maintainer's local gate on the
first try — but the maintainer running `python3 -m pytest` before merge remains
the actual law.

Assume the change is already implemented (by the `developer` skill or by hand).
If nothing has changed (`git diff` and `git diff --cached` both empty), say so
and stop.

## Step 1 — Review/fix loop (max 3 iterations)

Iterate:

1. Invoke **`code-reviewer`** on the current diff. It returns a numbered list
   labeled `blocker` / `should-fix` / `nit`.
2. If there are **zero blockers and zero should-fixes**, exit the loop
   (success).
3. Otherwise invoke **`fixer`** to resolve the blockers and should-fixes with
   the smallest possible diff, then re-review.

Stop after **3 iterations** even if findings remain. If you stop with findings
still open, report them and declare the PR **not ready** — do not proceed to the
mechanical gate as if it passed.

## Step 2 — Mechanical gate

Only after the loop reaches zero blockers/should-fixes, run each check and
record pass/fail:

1. **Full test suite + coverage gate:**
   ```bash
   python3 -m pytest
   ```
   Must be green, including the `fail_under` coverage gate (no `--no-cov`).
2. **Golden tests** (explicitly, in case a prompt/schema drifted):
   ```bash
   python3 -m pytest tests/golden --no-cov
   ```
   `tests/golden/test_prompts_verbatim.py` compares `tests/golden/reference/`
   byte-for-byte.
3. **Clean tree of stray files:**
   ```bash
   git status --porcelain
   ```
   Only the intended change should appear — no `dist/`, `build/`, `.coverage*`,
   `__pycache__`, or scratch files. (These are gitignored; flag anything that
   slipped through.)
4. **Commit-message / title format** — the change is one logical unit and its
   title is conventional-commit style (`fix:` / `feat:` / `docs:` / `test:` /
   `refactor:` / `chore:`), since it becomes the squash commit.

If any mechanical check fails, report exactly which one and stop — the PR is
**not ready**.

## Step 3 — Verdict

Only when the loop cleared **and** every mechanical check passed, print a
filled-in copy of the PR-template checklist
(`.github/PULL_REQUEST_TEMPLATE.md`) with each box ticked and a one-line
evidence note beside it (e.g. "pytest: 278 passed, coverage 55.9% ≥ gate"),
then state plainly: **the PR is ready to open.** Otherwise, print what blocked
it and what to do next. Never claim readiness when a check failed or the loop
stopped with findings open.
