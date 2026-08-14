<!--
Thanks for contributing! Keep PRs to one logical change with a
conventional-commit-style title (fix:/feat:/docs:/test:/refactor:/chore:) —
it becomes the squash commit. See CONTRIBUTING.md.
-->

## What & why

<!-- What does this change, and why? Link the issue it addresses. -->

Closes #

## Checklist

- [ ] One logical change; title is conventional-commit style.
- [ ] Tests added for every new code path, through the existing seams
      (FakeScreen / fake judge / AppPaths sandbox).
- [ ] `python3 -m pytest` is green locally, **including the coverage gate**
      (no `--no-cov`).
- [ ] No new runtime dependencies — `[project] dependencies` stays empty
      (stdlib only).
- [ ] No new write paths under `~/.claude` (all state under `~/.cclenzz`).
- [ ] Degrades, never crashes, on malformed / schema-drifted input.
- [ ] If a rubric / task prefix / explain prompt / schema changed, the
      byte-exact goldens under `tests/golden/reference/` were updated.
- [ ] `docs/DESIGN.md` updated for any structural change (module / CLI
      subcommand / seam).
- [ ] Ran `/pr-preflight` (or an equivalent review) before opening.

<!--
Reminder: there is no CI. The maintainer runs `python3 -m pytest` before
merging — a PR that fails the gate locally will be sent back.
-->
