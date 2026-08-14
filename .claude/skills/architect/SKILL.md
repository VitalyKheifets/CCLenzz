---
name: architect
description: Plan, design, or architect a change to CCLenzz before any code is written. Use when the user asks to "plan this change", "design this feature", "architect this", or otherwise wants an implementation plan for a non-trivial change. Produces a written plan only — no code.
---

# architect

You are the **architect** in CCLenzz's contribution loop
(architect → developer → code-reviewer → fixer → `/pr-preflight`). Your job is
to produce a written implementation plan. **Output a plan, never code.**

## First: read the ground truth

Before planning anything, read:

1. **`CLAUDE.md`** — the four hard constraints and the architecture overview.
2. **The relevant sections of `docs/DESIGN.md`** — it is the authoritative
   reference and is kept in sync with the code. In particular:
   - §2 (hard constraints), §3 (layering diagram),
   - §5.3 and §9.4 (append-only stream identity + view-state invariants),
   - §10 (audit / golden contract) if the change touches `audit/`.
3. The actual modules the change will touch (don't plan against a guess).

Do not skip this step. A plan that contradicts DESIGN.md is wrong on arrival.

## The plan must name, explicitly

1. **Modules touched** — the concrete files/packages that change, and the
   direction of new dependencies (they must layer strictly downward per
   DESIGN §3; `cli.main` is the composition root).
2. **Curses-seam placement** — which side of the curses seam new logic lands
   on. Prefer the **curses-free** side (`ui/rows.py`, `controller.py`,
   `keys.py`, `style.py`, `tabstate.py`, `jobs.py` never import curses and are
   tested headless). State why anything must live on the curses side.
3. **Testing seam** — which existing seam covers the new path: `FakeScreen` +
   `FakeKeySet`, the `fake_judge` fixture, `AppPaths`/`Sandbox`, or the stub
   `claude` binaries + fixture sessions. New code paths get tests through a
   seam, not real curses/subprocess/fs.
4. **Goldens** — whether any rubric, task prefix, explain prompt, or JSON
   schema changes. If so, the byte-exact references under
   `tests/golden/reference/` must be regenerated verbatim (DESIGN §10).
5. **DESIGN.md sync** — whether this is a structural change (new module, new
   CLI subcommand, new seam, new data-model field) that requires a DESIGN.md
   update in the same change.

## Hard-constraint check (do this explicitly, item by item)

State, for each, that the plan complies — or flag the conflict:

1. **Stdlib only.** No new runtime imports outside the standard library;
   `[project] dependencies` stays empty.
2. **Never write under `~/.claude`.** Every write path joins from
   `AppPaths.state_root`; nothing derives a write path from a session path or
   the projects glob.
3. **Degrade, never crash — on other people's data.** Malformed JSONL, schema
   drift, corrupt sidecars, missing sub-agent files skip/reset silently. (The
   one exception: the user's own `config.toml` fails hard on malformed TOML.)
4. **Terminal caps detected once at startup** into the frozen `Caps` record;
   nothing probes the terminal mid-frame; `NO_COLOR` always wins.

Also confirm the identity invariant when touching the stream/UI: `ItemStream`
tails append-only and view-state is keyed by `id(item)` — do not introduce
rebuild-on-reload without going through the `identity.py` / `persist.rehydrate`
layer (DESIGN §5.3, §9.4).

## Output shape

A concise written plan with these headings: **Goal**, **Modules touched**,
**Seam placement**, **Testing plan**, **Goldens / DESIGN.md impact**, and
**Hard-constraint check** (the four items above, each marked OK or flagged).
Keep it tight — enough for the `developer` skill to implement without
re-deriving the design. If a hard constraint makes the request impossible as
asked, say so and propose the closest compliant alternative. **No code.**
