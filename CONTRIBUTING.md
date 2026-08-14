# Contributing to CCLenzz

Thanks for wanting to improve CCLenzz. It's a solo-maintained, stdlib-only
project with a deliberately small surface; the guidelines below keep it that
way. Read them before opening a PR — they're what a review checks against.

## How contribution works here

- **Fork → PR.** Nobody but the maintainer has push access. Direct pushes to
  `main` and in-repo branches are blocked by rulesets; the only way in is a
  pull request from your fork.
- **PRs are reviewed and merged by the maintainer.** Response is best-effort.
  Stale PRs (30 days of silence after a review) may be closed — reopen any
  time.
- **There is no CI.** The test/coverage gate is enforced by the maintainer
  running `python3 -m pytest` locally before merging. A PR that fails the gate
  locally will be sent back, so run it yourself first (see
  [Testing & coverage](#testing--coverage)).

## The PR standard

1. **Open an issue first for anything non-trivial** and agree on the approach
   before writing code. Bug fixes with an obvious cause are fine to send
   directly; features and refactors should be discussed first so effort isn't
   wasted.
2. **One logical change per PR.** Small PRs get merged; mega-PRs stall. Split
   unrelated changes.
3. **Conventional-commit-style titles** (`fix:`, `feat:`, `docs:`, `test:`,
   `refactor:`, `chore:`) — the title becomes the squash commit message, since
   the repo is squash-merge only.
4. **Tests are required** for every new code path, wired through the existing
   seams (see below). `python3 -m pytest` must be green — coverage gate
   included — before you push.
5. **Run the skill loop.** The expected dev workflow is
   [`/pr-preflight`](.claude/skills/) (architect → developer → code-reviewer →
   fixer): run it before opening the PR. It's convention, not an enforced gate,
   but it's the paved road that makes a PR pass review on the first try.

## Hard constraints (a PR that violates one is wrong)

These come from [`CLAUDE.md`](CLAUDE.md) and
[`docs/DESIGN.md §2`](docs/DESIGN.md). They are enforced invariants, not style
preferences:

1. **Stdlib only.** `[project] dependencies` stays empty forever. `pytest` and
   `pytest-cov` are the only dev dependencies. No runtime imports outside the
   standard library.
2. **Never write under `~/.claude`.** All CCLenzz state lives under
   `~/.cclenzz`. This is integration-tested by hashing `~/.claude` before and
   after a run.
3. **Degrade, never crash — on other people's data.** Malformed JSONL, schema
   drift, corrupt sidecars, and missing sub-agent files all skip/reset
   silently. The one deliberate exception is the user's own `config.toml`,
   which fails hard on malformed TOML.
4. **Goldens are byte-exact.** Any change to a rubric, task prefix, explain
   prompt, or schema must update the reference files under
   `tests/golden/reference/` verbatim — a one-character drift changes model
   behavior, and `tests/golden/test_prompts_verbatim.py` compares byte-for-byte.
5. **Keep `docs/DESIGN.md` in sync.** It's the authoritative architecture
   reference. Structural changes (new module, new CLI subcommand, new seam)
   update DESIGN.md in the same PR.

## Testing & coverage

Tests run **headless through injectable seams**, never real terminals or
models. When you add a code path, wire it through an existing seam rather than
reaching for real curses/subprocess/fs:

- `FakeScreen` + `FakeKeySet` for the curses layer,
- the `fake_judge` fixture for the audit,
- `AppPaths` / `Sandbox` for the filesystem,
- stub `claude` binaries in `tests/fixtures/bin/` and fixture sessions in
  `tests/fixtures/sessions/` for integration tests.

Run the full suite (it enforces the coverage gate via `addopts`):

```bash
pip install -e ".[dev]"
python3 -m pytest
```

`python3 -m pytest` measures **branch coverage** and fails if it drops below
the `fail_under` gate in `pyproject.toml` (`[tool.coverage.report]`). Notes:

- Running a **subset** (e.g. `python3 -m pytest tests/golden`) reports low
  total coverage and will trip the gate — pass `--no-cov` when you only want a
  slice.
- **Ratchet policy: the threshold only goes up.** Never lower `fail_under` to
  make a PR pass — add the missing test instead. When real coverage exceeds the
  gate by ≥ 3 points, a small PR bumping the threshold is welcome.
- **`python3 -m pytest` must be green before you open the PR.** With no CI, the
  maintainer re-runs it before merging; a red suite sends the PR back.

## Reporting bugs & requesting features

Use the issue templates. Bug reports should include your `cclenzz doctor`
output (terminal caps + environment) — it's usually what a diagnosis needs.
Security issues do **not** go in public issues — see [SECURITY.md](SECURITY.md).

By contributing you agree your contributions are licensed under the project's
[Apache-2.0](LICENSE) license.
