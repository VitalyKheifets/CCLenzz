# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CCLenzz is a read-only, tabbed curses TUI that tails Claude Code session
transcripts (`~/.claude/projects/*/*.jsonl`) one line per prompt/tool call,
and can run an optional LLM "intent audit" that scores whether what Claude did
matched what the user asked. It shells the audit out to the user's own
`claude` CLI — CCLenzz holds no API key and never calls an endpoint itself.

## Commands

```bash
./cclenzz                    # run the TUI (launcher; no install needed)
./cclenzz setup              # (re)run the config wizard
./cclenzz doctor             # print detected terminal caps + environment checks
pip install -e ".[dev]"      # install dev deps (pytest + pytest-cov)
python3 -m pytest            # run the full suite (enforces the coverage gate)
python3 -m pytest tests/unit/test_model.py::test_name   # single test
python3 -m pytest tests/golden                          # just the golden tests
```

No linter/formatter is configured. Python ≥ 3.11 (needs `tomllib`).

`python3 -m pytest` measures branch coverage and fails if it drops below the
`fail_under` gate in `pyproject.toml` (`[tool.coverage.report]`). The gate is
ratchet-only-up. A subset run (e.g. `tests/golden` alone) reports low total
coverage and will trip the gate; pass `--no-cov` when you only want a slice.

## Hard constraints (violating one means the change is wrong)

These are enforced invariants, not style preferences — see `docs/DESIGN.md §2`:

1. **Stdlib only.** `[project] dependencies` stays empty. `pytest` and
   `pytest-cov` are the only dev dependencies. Do not add runtime imports
   outside the standard library.
2. **Never write under `~/.claude`.** All CCLenzz state lives under
   `~/.cclenzz`. Every write path is joined from `AppPaths.state_root`, never
   from a session path or the projects glob. The audit subprocess passes
   `--no-session-persistence`. This is integration-tested by hashing
   `~/.claude` before/after a run.
3. **Degrade, never crash — on *other people's* data.** Malformed JSONL, schema
   drift, corrupt sidecars, missing sub-agent files all skip/reset silently.
   The one deliberate exception: the user's own `config.toml` fails hard
   (`exit 1`) on malformed TOML — a typo there should be fixed, not ignored.
4. **Terminal caps are detected once at startup** into a frozen `Caps` record;
   nothing probes the terminal mid-frame. Degrade rgb→256→16→mono and
   nerd→unicode→ascii; `NO_COLOR` always wins.

## Architecture

`docs/DESIGN.md` is the authoritative reference and is kept in sync with the
code (module layout, data model, audit contract, testing seams). Read it before
non-trivial changes. Key points:

- **Composition root:** `cli.main` builds the frozen `AppPaths`, `Settings`,
  `Caps`, and `ClaudeCliJudge` once and passes them down. `ui.tui` and
  `audit.judge` are imported lazily. Module dependencies layer strictly
  downward (see the layering diagram in DESIGN §3).

- **Append-only stream identity (load-bearing):** `model.ItemStream` tails one
  JSONL file append-only — `Item` objects are never rebuilt. This is *why* the
  UI can key all fold/expand/flag/explain view-state by `id(item)`, and why
  `identity.py` (stable string keys) + `persist.rehydrate` translate persisted
  keys back to live objects on tab open. Changing the stream to rebuild-on-
  reload without changing the identity layer would silently drop all view
  state. See DESIGN §5.3 and §9.4.

- **Diffs come from logged tool input, never the filesystem** (`diffs.py`) —
  `old_string` vs `new_string`. This keeps the view read-only and faithful to
  what happened at the time (works even for since-deleted files). File bodies
  are never read and never sent to the auditor.

- **The curses seam:** `ui/rows.py`, `controller.py`, `keys.py`, `style.py`,
  `tabstate.py`, `jobs.py` never import curses and are tested headless. curses
  attrs become a `Style` IntFlag, `time.time()` becomes an explicit per-frame
  `now` param, and `screen.Screen` is a Protocol (`FakeScreen` in tests). Keep
  new UI logic on the curses-free side of this seam where possible.

- **Background jobs have no locks** (`ui/jobs.py`). The whole synchronization
  contract is write ordering: a worker thread writes `self.result` then
  `self.status = "done"`; the main loop polls `status` and does *all* `Tab`
  mutation on the main thread in `consume_done`. Do not add cross-thread `Tab`
  writes.

- **The audit is prompt-golden-tested.** `audit/` distills the transcript
  (lossy by design — bodies/diffs compressed to counts), sends it to the
  `claude` CLI with a fixed rubric + JSON schema, and maps the judge's raw
  numbers to labels *on the CCLenzz side* (the rubric hides band edges from the
  model). Any change to a rubric, task prefix, explain prompt, or schema must
  update the byte-exact goldens under `tests/golden/reference/` —
  `tests/golden/test_prompts_verbatim.py` compares them verbatim because a
  one-character drift changes model behavior. See DESIGN §10.

## Testing seams

Tests run headless through injectable seams, not real terminals/models:
`FakeScreen` + `FakeKeySet` (curses), injected `Judge` fakes (the `fake_judge`
fixture in `conftest.py`), and `AppPaths`/`Sandbox` for the filesystem.
Integration tests use stub `claude` binaries in `tests/fixtures/bin/`
(`fake_claude_ok/auth/garbage/empty/slow`) and fixture sessions in
`tests/fixtures/sessions/`. When adding a code path, prefer wiring it through
an existing seam over reaching for real curses/subprocess/fs.

## Contribution workflow

Contributions should go through `/pr-preflight` before a PR is opened — the
`.claude/skills/` loop (architect → developer → code-reviewer → fixer →
`/pr-preflight`) is the expected dev workflow. There is no CI, so the maintainer
runs `python3 -m pytest` before merging; the skill loop is the paved road that
makes a PR pass that gate on the first try.
