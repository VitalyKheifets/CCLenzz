# CCLenzz — Design Document

This document describes the architecture of CCLenzz **as implemented** (v1.0.0,
package layout under `src/cclenzz/`). It is the reference for anyone changing
the code. User-facing usage lives in the top-level [README](../README.md).

> **Historical note on `§` references.** Some module docstrings cite section
> numbers (`§5.4`, `§14.1`, …) from the retired restructure spec
> (`docs/FEATURE-modular-restructure.md`, removed in commit `fab19a5`;
> recoverable via `git show 682a905:docs/FEATURE-modular-restructure.md`).
> Those numbers do **not** refer to this document.

---

## 1. What CCLenzz is

A flight recorder + heads-up display for Claude Code. It renders a live,
tabbed terminal view of Claude Code sessions read straight from
`~/.claude/projects/*/*.jsonl` — one line per prompt or tool call — and, on
demand, runs an **LLM intent audit** that scores per prompt whether what Claude
*did* matched what the user *asked for*.

Two model-backed features exist, both delegated to the user's own `claude` CLI:

- **audit** (`a` key or `auto_audit`) — whole-session verdicts, one per prompt.
- **explain** (`?` key) — a short prose explanation of a single row.

## 2. Hard constraints

These are invariants, not preferences. A change that violates one is wrong.

1. **Stdlib only.** `[project] dependencies = []` in pyproject.toml stays
   empty. The only runtime requirement is Python ≥ 3.11 (for `tomllib`).
2. **Read-only under `~/.claude`.** CCLenzz never writes anything there. All
   CCLenzz state lives under `~/.cclenzz`. Every persistence write path is
   joined only from `AppPaths.state_root` — never from the projects glob or a
   session path. The audit subprocess passes `--no-session-persistence` so
   even the judge run leaves no trace in the user's session history
   (integration-tested by hashing `~/.claude` before/after).
3. **No secrets.** CCLenzz holds no API key; the audit reuses the `claude`
   login already on `PATH`.
4. **Degrade, never crash — for *other people's* data.** Malformed JSONL
   lines, schema drift, corrupt sidecars, missing sub-agent files, failed
   cache writes: all are silently skipped or reset. The *user's own*
   `config.toml`, by contrast, fails hard (`exit 1`) — a typo there should be
   fixed, not ignored.
5. **Terminal honesty.** Capabilities are detected once at startup; the UI
   never probes mid-frame, degrades cleanly rgb → 256 → 16 → mono and
   nerd → unicode → ascii, and respects `NO_COLOR` unconditionally.

## 3. System overview

```
 ~/.claude/projects/*/*.jsonl        ~/.cclenzz/
 (Claude Code transcripts,           ├── config.toml     (user config)
  read-only)                         └── sessions/<slug>/<id>.json  (sidecars)
        │                                    ▲
        ▼                                    │ persist / rehydrate
 sessions.py ── discovery ──┐                │
 model.py ─── ItemStream ───┤          persist.py
 classify.py  diffs.py      ├──► ui/  (curses TUI) ──► screen
 subagents.py identity.py ──┘         │
                                      │ a / ?  (threads in ui/jobs.py)
                                      ▼
                         audit/  ── transcript → prompts → judge
                                      │
                                      ▼
                          `claude -p --json-schema …`  (subprocess)
```

`cli.main` is the single composition root: it builds the frozen records
(`AppPaths`, `Settings`, `Caps`) and the `ClaudeCliJudge` once and passes them
down. The keyword-only `paths=`/`judge=` parameters of `main()` exist for
in-process tests only.

### Module dependency layering (strictly downward)

```
paths, ansi, termcaps, configwrite, config      (stdlib only)
glyphs → termcaps          textutil → glyphs
classify → textutil        model → classify, textutil
sessions → model           diffs → classify     subagents → model
detail → diffs, subagents  identity → model, subagents
persist → configwrite, identity
doctor, wizard → ansi, termcaps/glyphs
cli → everything above; ui.tui and audit.judge imported lazily
```

## 4. Repository layout

```
cclenzz                  # launcher: version gate, sys.path insert, cli.main()
pyproject.toml           # zero deps; console script cclenzz = cclenzz.cli:main
src/cclenzz/
  cli.py                 # composition root, argparse, startup sequence
  paths.py               # AppPaths — the file-location / sandboxing seam
  sessions.py            # session discovery + metadata
  model.py               # Item, ItemStream (incremental JSONL tailing)
  classify.py            # tool_use → (category, tool, arg, arg_kind)
  diffs.py               # unified diffs from logged tool input (no fs reads)
  subagents.py           # child-transcript resolution and inlining
  identity.py            # stable cross-run item keys for persistence
  detail.py              # item → labeled detail blocks
  persist.py             # sidecar cache (audit verdicts, explanations)
  config.py, configwrite.py, wizard.py, doctor.py
  textutil.py, ansi.py, termcaps.py, glyphs.py
  audit/                 # transcript.py, prompts.py, judge.py, scoring.py, explain.py
  ui/                    # tui.py, controller.py, rows.py, draw.py, screen.py,
                         # keys.py, jobs.py, tabstate.py, picker.py, palette.py,
                         # help.py, external.py, style.py
tests/                   # unit / golden / integration + fixtures (see §12)
```

## 5. Core data layer

### 5.1 Paths (`paths.py`)

`AppPaths` (frozen dataclass) replaces mutable globals and is the sandboxing
seam for tests: `state_root` (default `~/.cclenzz`), `projects_glob` (default
`~/.claude/projects/*/*.jsonl`), derived `config_path` and
`sessions_state_dir()`. The glob is overridable only via the `projects_glob`
config key (`with_projects_glob`). No environment variables are consulted.

### 5.2 Discovery (`sessions.py`)

`discover_sessions(paths, max_sessions, fast)` globs, builds a `Session` per
file (skipping `OSError`), sorts by mtime descending, truncates to
`MAX_SESSIONS_DEFAULT = 40`, then reads metadata. `Session` carries
`path/mtime/size/session_id/dir_label/cwd/project/title/item_count`.

- `read_meta()` — full JSONL walk (first tab only at startup).
- `read_meta_fast()` — reads only the first and last 64 KiB; `item_count`
  stays `None`.
- Title precedence: `custom_title or ai_title or last_prompt or first_prompt
  or "(no prompt yet)"` (from `custom-title`/`ai-title`/`last-prompt` events
  and the first user prompt).
- `is_live(session, now, m)` — mtime within `LIVE_MINUTES_DEFAULT = 5` min.

### 5.3 Items and incremental tailing (`model.py`)

`CATEGORIES = ["prompt", "read", "edit", "bash", "search", "mcp", "agent",
"web", "skill", "artifact", "other"]`.

`Item` (`__slots__`) is one row: `kind` (`"prompt"`/`"tool"`), `category`,
`tool`, `arg`, `arg_kind` (`"path"`/`"text"`), `text`, `name`, `input`,
`result`, `is_error`, `tool_use_id`, `ts_start/ts_end`, `rev` (revision
counter bumped on any mutation — the staleness signal for persistence),
`children`, `agent_id`, `output_file`, `sub_kind`, `sub_stream`, `resolved`,
plus memoized `_diff`/`_churn`.

`ItemStream` tails one JSONL file **append-only** — items are never rebuilt,
which is what makes the UI's `id(item)`-keyed view state safe (§9.4).
`refresh()`:

1. `getsize`; **file shrank → full re-parse from offset 0** (truncation /
   rotation handling).
2. Read from stored byte `offset` to EOF in binary; consume only through the
   last `\n` — a trailing partial line is left for the next tick.
3. Decode UTF-8 with `errors="replace"`; blank or non-JSON lines skipped.

Ingestion: `user` events yield prompt items and resolve pending
`tool_result`s (back-filling `result`, `is_error`, `ts_end`); `assistant`
events yield tool items via `classify_tool` and record prose in `says`
(position-indexed, consumed by the audit transcript). Out-of-order results
(result seen before its `tool_use`) are held in `results` and attached at
creation.

**Turn-completion**: `is_turn_complete(idle_ok)` is `False` while the last
non-meta event is not `assistant`, `stop_reason == "tool_use"`, or any tool
result is pending. The 2-second idle debounce (`DONE_DEBOUNCE`) lives in the
UI, not here. `turns()` splits the flat list into
`(lead_items, [(prompt, children), …])`, cached by list length.

### 5.4 Classification (`classify.py`)

`classify_tool(name, input, cwd)` → `(category, tool, key_arg, arg_kind)`.
Highlights: `mcp__server__tool` → `mcp` with arg `server.tool`; Bash → first
line of the command; `Edit/MultiEdit/Write/NotebookEdit` → `edit` with a
cwd-relative path (`arg_kind="path"` → middle truncation preserving the
basename; everything else end-truncates); `Agent`/`Task*` → `agent`;
`Grep/Glob/ToolSearch` → `search`; `WebSearch/WebFetch` → `web`; unknown →
`other`.

### 5.5 Diffs (`diffs.py`)

Diffs are computed **purely from the logged tool input** (`old_string` vs
`new_string`, per-edit chunks for `MultiEdit`, empty-baseline for
`Write`/`NotebookEdit`) — the real file is never read, so the view is
faithful to what happened at the time, works for deleted files, and stays
read-only. `diff_churn` yields the `+A −B` counts shown in rows and sent to
the auditor (bodies are never sent).

### 5.6 Sub-agents (`subagents.py`)

A parent's `Agent`/`Task*` tool result text carries `agentId: …` and
`output_file: …` (regex-extracted). `resolve_subagent` classifies the launch:

| `sub_kind` | Meaning |
|---|---|
| `async` | `output_file` exists → a second `ItemStream` over the child transcript; its items become `item.children`, fully inlined |
| `sync` | result text only, no transcript on disk |
| `unavailable` | recorded path no longer exists (surfaced to the auditor as an evidence gap) |

Recursion is capped at `SUBAGENT_MAX_DEPTH = 5` with an `agent_id` cycle
guard. `refresh_subtree` keeps child streams tailed; `subtree_quiet` gates
turn-completion (and therefore auto-audit) on every descendant being idle.

### 5.7 Identity (`identity.py`)

Persistence needs keys that survive a restart, while the UI keys view state
by `id(object)`. `identity.py` is the bridge: tools →
`"t:" + tool_use_id`; prompts → `"p:{ordinal}:{sha1(text)[:8]}"`;
`item_sig` (sha1 of label + result head) + `item.rev` detect that a
persisted explanation refers to a changed row. `build_key_index(tab)` maps
key → live `Item` across the whole tree (resolving sub-agents on demand);
prompt numbering matches `build_audit_transcript` exactly.

## 6. Persistence (`persist.py`)

Sidecar per session: `~/.cclenzz/sessions/<slug>/<session_id>.json`, where
`<slug>` is Claude's own project directory name (never re-derived from cwd).
Document: `schema` (`SCHEMA_VERSION = 1`), `cclenzz_version`, `session_id`,
`project_slug`, `updated_at`, `cost_usd`, `audit`
(`{signature: {n_items, last_mtime}, verdicts: […]}` keyed by `prompt_key`),
`explain` (`{item_key: {status, text, model, item_rev, item_sig,
created_at}}`).

Rules:

- Writes go through `configwrite._atomic_write_text` (0700 dir, 0600 tmp,
  fsync, `os.replace`); sidecar write failures are swallowed — a cache must
  never crash the TUI.
- Corrupt / non-dict / unknown-or-newer schema → start fresh, don't merge.
- `rehydrate(tab)` restores verdicts, flags, cost, and explanations on tab
  open (explanations rebind to live `rev`/`sig` and gain a `stale` flag on
  mismatch); the whole call is wrapped in `except Exception` — a bad sidecar
  can never break tab creation. `audit_dirty` recomputes from signature
  mismatch, so stale badges render dimmed until re-audited.
- `"running"` explain records are never persisted.
- `prune_state` (startup only): delete sidecars whose session no longer
  exists in the glob, plus (opt-in via `state_retention_days`) age-based
  pruning; capped at `ORPHAN_PRUNE_CAP = 200` deletions per launch.
- `persist = false` disables the entire subsystem (load and store).

## 7. Configuration

Single surface: `~/.cclenzz/config.toml` (TOML via `tomllib`). No env vars,
no CLI tuning flags. Unknown keys warn and are ignored; malformed TOML is a
hard `exit 1`.

| Key | Default | Consumed by |
|---|---|---|
| `theme` | `auto` | `detect_caps` (bg via OSC 11 query, 50 ms) |
| `icons` | `auto` | `detect_caps` (nerd is opt-in only, never auto) |
| `color` | `auto` | `detect_caps` (`NO_COLOR` always wins) |
| `auto_audit` | `false` | `Settings` |
| `audit_model` | `"opus"` | `Settings` → judge |
| `explain_model` | `"haiku"` | `Settings` → judge |
| `interval` | `1.0` | `Settings` → poll cadence |
| `ambiwidth` | `1` | `detect_caps` (East-Asian ambiguous width) |
| `projects_glob` | `~/.claude/projects/*/*.jsonl` | `AppPaths` |
| `claude_bin` | `"claude"` | `Settings` → judge, doctor |
| `persist` | `true` | `Settings` |
| `state_retention_days` | unset | `Settings` → age pruning |

`configwrite.py` renders `CONFIG_TEMPLATE`: the four wizard keys active,
every other key present but commented with its default; on a `setup` re-run,
previously customized optional keys are re-emitted uncommented.

**Wizard** (`wizard.py`): raw-TTY inline picker (no curses), four questions
— theme, icons, color, auto-audit — each with a live preview rendered
against mutated `Caps`. Pure UI: returns answers or `None`; `cli` writes the
file. Runs on `cclenzz setup` or automatically on first launch (interactive
only; non-interactive without config exits 2).

### CLI surface and exit codes

`cclenzz` (TUI) · `cclenzz setup` · `cclenzz doctor` · `cclenzz update`
(`--snapshot` / `--stable`) · `--version`.
Exit codes: `0` ok · `1` bad config.toml, or a failed `update` · `2`
non-interactive without config, or not a TTY / `TERM=dumb` · `130` Ctrl-C or
wizard abort. `update` alone dispatches ahead of the config/terminal path (it
needs neither); see §13 Distribution.
`doctor` prints version/python/platform, sessions-glob health, terminal
caps, theme, `claude` binary + `--version` probe, models, config presence,
and state-dir size/writability — failing lines in the error color.

## 8. Terminal capability model

`detect_caps(cfg)` runs **once** at startup and produces a frozen `Caps`
record; nothing probes the terminal mid-frame.

- **color** ∈ `rgb / c256 / c16 / mono`: `NO_COLOR` → mono (wins over
  everything incl. `color="always"`); `COLORTERM=truecolor|24bit` → rgb;
  else curses `tigetnum("colors")`; config can force `never`/`always`.
- **glyphs** ∈ `nerd / unicode / ascii`: from config, else UTF-8 locale →
  unicode, else ascii. Every glyph in `glyphs.GLYPHS` occupies exactly one
  cell in its tier; the `AMBI_KEYS` set falls back to ascii *per glyph* when
  `ambiwidth = 2`.
- **bg** ∈ `dark / light`: config theme, else OSC 11 background query with
  luminance threshold (multiplexer or failure → dark).
- **mouse/osc8/osc52/title**: mouse = is-a-TTY; OSC 8 hyperlinks only on
  known terminals and never inside tmux/screen; OSC 52 clipboard always
  attempted as a fallback.

Two color systems share the `ansi.RGB_` token table (dark + light variants
across rgb/256/16-color): `ansi._ansi` emits raw escapes for the non-curses
surfaces (doctor, wizard), and `ui/palette.Palette` resolves the same tokens
to curses attributes, silently downgrading rgb → c256 when the terminal
can't redefine colors, and lazily allocating color pairs (exhaustion returns
pair 0 rather than raising).

## 9. TUI architecture (`ui/`)

### 9.1 The curses seam — the load-bearing decision

`rows.py`, `controller.py`, `keys.py`, `style.py`, `tabstate.py`, `jobs.py`
never import curses and are tested headless. Three mechanical
transformations make that possible: curses attributes → `Style` IntFlag
(`BOLD/DIM/REVERSE`, mapped back by `Palette.style_extra`); implicit
`time.time()` → an explicit per-frame `now` parameter; search-match
highlighting computed into row data rather than at draw time.
`screen.Screen` is a Protocol (`CursesScreen` in production, `FakeScreen` in
tests); `put()` is the single cell-clipping draw primitive. `KeySet`
snapshots the 13 curses key codes so the controller compares plain ints
(`FakeKeySet` hardcodes them for tests).

### 9.2 Main loop (`tui.py`)

`run_tabs` wraps `_loop` in `curses.wrapper`. The loop is **input-driven
with an adaptive timeout**, not frame-based: `getch()` blocks up to
`poll_interval(tab, interval, now)` — `interval × 0.25` when the session
changed within 5 s, `interval` within 60 s, `interval × 2` otherwise, floored
at 50 ms. A `-1` return is the idle tick, which:

1. discovers new sessions and opens them as tabs (focus is stolen only after
   5 s of keyboard inactivity; otherwise an unread badge increments);
   dismissed session ids are not reopened;
2. reloads the followed tab on mtime change and refreshes sub-agent streams;
3. evaluates auto-audit gating: turn complete (with 2 s debounce) ∧ session
   still live ∧ sub-tree quiet ∧ signature `(len(items), mtime)` changed →
   sets `audit_dirty`, and fires the audit when auto mode is on.

Rendering recomputes full layout every frame from `getmaxyx()` (resize is
absorbed naturally; `KEY_RESIZE` just repaints): tabstrip / header / body
rows / scrollbar / "new items" chip / footer. Terminals under 40×8 get a
compact mini view; no sessions at all gets an empty-state card that polls
until one appears. Spinners are wall-clock driven (10 fps) so they animate
correctly at any poll rate.

### 9.3 Controller and rows

`Controller.handle_key/handle_mouse` are pure transitions returning an
`Effect` (`NONE/QUIT/REPAINT/BEEP`). Modality is minimal: search input mode
(`tab.search_active` reroutes all keys), blocking sub-loops for the picker /
help / pager / editor, and the mini mode. Everything else is per-tab state
in `Tab` (`tabstate.py`): fold/expand sets, filters (`errors_only`,
`cat_filter`), follow/stick scroll model, search, audit results, explain
records, cost.

`RowBuilder.build_rows` turns `stream.turns()` into `RenderRow`s — kinds
`turn` (prompt header with folded digest `N tools · M edits(+a −r) · E ✗`),
`tool` (tree guides, category glyph + color, tool + arg, churn/duration/
timestamp on the right), `audit` (verdict digest under a prompt), `sub`
(detail block lines), `ptext` (wrapped prompt text). Progressive
open/close: `→` unfolds, then expands details; `←` reverses, then jumps to
the parent; audit rows fold independently of their turn; audit deduction
lines carry a `cite` pointer that `→` follows to the offending item.
Cursor identity survives reloads by remembering the owning `Item` object and
re-finding it.

**AI-callout card:** the two LLM-generated regions — the `?` explanation and
the intent-audit derivation — never render as plain detail blocks. `RowBuilder.
emit_ai_block` frames them as a card so machine-generated prose can't be
mistaken for logged transcript data: a violet `✦` sigil + `ai`/`ai.dim` color
tokens, a `╭─ ✦ <title> ─` header, a dashed `┊` left rail down every body line,
and a `╰─ ✦ <verb> by claude · <model>` provenance footer. The audit badge
row's `✦` uses the same `ai` violet; the score keeps its aligned/partial/drift
color. The card degrades with the glyph/color tiers like everything else
(`✦→*`, `┊→:`, `╭→+`, violet→magenta→mono). Raw tool `input`/`result`/`diff`
blocks stay on the flat `emit_blocks` treatment — the visual split *is* the
point.

### 9.4 View-state identity

All fold/expand/flag/explain state is keyed by `id(item)`. This is correct
only because `ItemStream` is append-only and `rehydrate`/`build_key_index`
translate persisted string keys back to live objects on tab open. A
rebuild-on-reload stream would silently drop all view state — do not change
one without the other.

### 9.5 Background jobs (`jobs.py`)

`AuditJob` and `ExplainJob` are single-flight managers around one daemon
`threading.Thread` each; no pool, no queue, **no locks**. The entire
synchronization contract is write ordering: the worker writes `self.result`
then `self.status = "done"`; the main loop polls `status` each frame and
performs *all* `Tab` mutation on the main thread in `consume_done`.
Cancellation is a cooperative `threading.Event` (`x` key), which also
SIGTERMs the judge's process group. Details:

- Audit: signature recorded at start; if the session changed mid-run
  (`audit_dirty`), the job re-fires exactly once on completion. Success
  stores verdicts (with per-prompt alignment deltas vs. the previous run),
  accrues `total_cost_usd` into the tab, and persists the sidecar. Auth
  failures beep and show a 20 s toast naming the configured binary.
- Explain: `?` on the in-flight item cancels (toggle); results for a tab
  closed mid-request are dropped; errors are stored inline as `status:
  "error"` records so the row shows the failure.

## 10. The intent audit (`audit/`)

Four seams: transcript distillation → prompt text → subprocess judge →
score presentation. CCLenzz holds no API key and never talks to an endpoint
itself.

### 10.1 Transcript (`transcript.py`)

`build_audit_transcript(items, stream)` renders the whole tree (sub-agents
inlined, indented) into a plain-text transcript and returns
`(text, index_map, prompt_map)` — the maps translate the judge's integers
back to live items. Line forms: `[prompt N] (item i) "…"`, positional agent
prose as `say "…"`, `tool (item i) LABEL → RESULT`, `↳ …` for sub-agent
steps, and a trailing `[session status]` line (`COMPLETE` / `IN PROGRESS` /
`UNKNOWN`).

**Deliberate lossiness:** file bodies and diffs are never sent — edits
compress to `applied edit (+A −B lines)`; results compress via `_gist`
(first lines joined with `⏎`). Truncation constants:
`AUDIT_PROMPT_LEN 2000 · AUDIT_LABEL_LEN 220 · AUDIT_RESULT_LEN 400 (4
lines) · AUDIT_SAY_LEN 700 · AUDIT_SUBREPORT_LEN 600`. The rubric explicitly
tells the judge this abbreviation is normal and must not lower confidence.

### 10.2 Judge (`judge.py`)

`Judge` is a Protocol (tests inject fakes); production is
`ClaudeCliJudge(claude_bin, audit_model, explain_model)`. Audit argv:

```
claude -p --model <model> --output-format json
       --json-schema <AUDIT_SCHEMA>
       --disallowedTools Bash,Edit,Write,Read,Grep,Glob,WebFetch,WebSearch,Agent,Task
       --append-system-prompt <AUDIT_RUBRIC>
       --no-session-persistence
```

with `AUDIT_TASK_PREFIX + transcript` on stdin. `start_new_session=True`
enables killing the whole process group on cancel. Timeouts:
`AUDIT_TIMEOUT = 600` s, `EXPLAIN_TIMEOUT = 120` s; the wait loop polls every
0.2 s checking the cancel event and deadline. **No retries** — every failure
is terminal and returned as a dict (`{ok, error, verdicts|text, cost, model,
cancelled}` + `auth: True` for login failures); neither method ever raises.
Parsing: envelope JSON → `is_error` check → `result` string re-parsed as
JSON → `verdicts` must be a list. Per-verdict validation is delegated
entirely to the CLI's `--json-schema`; downstream consumers defend with
`try/except`. `_looks_like_auth_error` matches 401/unauthorized/expired-
token/login phrasings and routes to a dedicated actionable error.

### 10.3 Rubric, schema, scoring (`prompts.py`, `scoring.py`)

The judge returns **raw numbers only**; CCLenzz owns the labels (the rubric
deliberately hides the band edges from the model). Per verdict:
`prompt_idx, ask, delivered, defects[], alignment, evidence_gaps[],
confidence, reason` (+ optional `flagged_items`, `scope`, `agentId`).
Arithmetic contract, stated redundantly in rubric, schema descriptions, and
task prefix: `alignment = 100 − Σ defect points` (floor 0);
`confidence = 100 − Σ gap points` (floor 1).

Defect codes (rubric point ranges): `IGNORED_CONSTRAINT` 25–60 ·
`MISSED_DELIVERABLE` 20–50 · `FALSE_CLAIM` 30–70 · `WRONG_TARGET` 20–50 ·
`UNREQUESTED_CHANGE` 10–40 · `SUBAGENT_DRIFT` 10–40 · `UNRESOLVED_FAILURE`
10–30 · `ABANDONED` 20–50. Gap codes: `PROMPT_UNCLEAR` 10–30 ·
`INTENT_OUTSIDE_TRANSCRIPT` 10–25 · `CLAIM_UNVERIFIABLE` 5–20 · `IN_FLIGHT`
5–15 · `SUBAGENT_OPAQUE` 5–20. The rubric also carries an explicit
anti-deduction list (exploration, verbosity, style, clarifying questions…),
in-progress rules (score trajectory; `MISSED_DELIVERABLE`/`ABANDONED`
forbidden; add `IN_FLIGHT`), calibration examples, and anti-round-number
anchoring.

`scoring.py` maps numbers to presentation:
`ALIGN_BANDS = [(85, "aligned"), (60, "partial"), (0, "drift")]`;
`CONF_LOW = 70` → badge renders dim. Non-numeric values degrade to
`drift`/dim, never raise.

**Prompt stability is golden-tested**: `tests/golden/test_prompts_verbatim.py`
byte-compares rubric, task prefixes, explain system prompt, schema, and code
tables against `tests/golden/reference/` — a one-character drift changes
model behavior, so any intentional prompt change must update the goldens.

### 10.4 Explain (`explain.py`)

Independent of the audit: prose (no schema), default model `haiku`, 120 s
timeout. `build_explain_context` sends ≤ 6000 chars: cwd, the owning
prompt's intent, tool/category, and the item's detail blocks (diff capped at
1500 chars). Output is clipped to 800 chars / 6 lines. Prompt rows get a
"restate the goal" mode instead of a command explanation.

## 11. Error-handling posture (summary)

| Input | Behavior |
|---|---|
| Malformed JSONL line / unknown event | skipped silently |
| Transcript file shrank | full re-parse |
| Partial trailing line | deferred to next tick |
| Sub-agent transcript missing | `unavailable`, surfaced as audit gap |
| Corrupt sidecar / newer schema | fresh doc; rehydrate never throws |
| Sidecar write failure | swallowed |
| Judge failure (any) | error dict → toast; auth gets beep + hint |
| Terminal too small | mini view |
| Bad config.toml | **hard exit 1** (the one deliberate exception) |

## 12. Testing strategy

- **Unit** (`tests/unit/`) — headless via the seams: `FakeScreen`,
  `FakeKeySet`, injected `Judge` fakes, `AppPaths` sandboxes.
- **Golden** (`tests/golden/`) — byte-exact references for audit/explain
  prompts and schema, transcript rendering per fixture session, doctor
  output, plus invariants for glyph tables and color tokens.
- **Integration** (`tests/integration/`) — real subprocesses and ptys:
  stub `claude` binaries in `tests/fixtures/bin/` (`fake_claude_ok/auth/
  garbage/empty/slow`) exercise the judge end-to-end, including captured
  argv, sidecar writes, badge rehydration across relaunch, and the
  `~/.claude`-untouched hash check. Fixture sessions in
  `tests/fixtures/sessions/` cover categories, edits, errors, unicode,
  malformed lines, in-progress turns, and parent/child agent linking.

Run with `python3 -m pytest` (dev dependencies: `pytest` + `pytest-cov`).

**Coverage gate.** `[tool.pytest.ini_options] addopts` wires
`--cov=src/cclenzz` into every plain `python3 -m pytest` run, so the gate is
enforced identically for maintainers, `scripts/release.sh`,
`scripts/snapshot.sh`, and contributors — there is no CI to enforce it
otherwise. `[tool.coverage.run]` measures **branch** coverage and omits
`tests/*`; `[tool.coverage.report] fail_under` is the threshold (currently 53
= the measured 55% baseline minus 2). The gate is **ratchet-only-up**: raise
`fail_under` via a dedicated PR once real coverage clears it by ≥ 3 points,
never lower it. A subset run reports low total coverage and trips the gate;
pass `--no-cov` to measure a slice without failing.

## 13. Distribution (`.pyz` + install/update)

CCLenzz ships as a **single platform-independent zipapp** — a stdlib
`zipapp` of the `cclenzz` package with a hand-written top-level `__main__`
(entry `cclenzz.cli:main`). One file, `cclenzz-<ver>.pyz`, runs on any Python
≥ 3.11 on any OS/arch; there is nothing to cross-compile or sign. `scripts/
build.sh` produces it plus a `SHA256SUMS`; releases and snapshots are cut
locally (no CI) and published as GitHub releases.

- **Install** (`install.sh`, repo root, POSIX-compatible bash) is a one-liner
  (`curl … | bash`). Its **first** step is the hard Python preflight: probe
  `python3.13/3.12/3.11/python3`, pick the first reporting ≥ 3.11, else log the
  reason to `~/.cclenzz/install.log` and abort — **never** writing under
  `~/.claude` (constraint #2). It resolves a release for the chosen channel off
  the GitHub API (parsed with the chosen Python — no jq/grep), verifies the
  checksum, installs the payload to `~/.cclenzz/cclenzz.pyz`, and writes an
  executable wrapper `~/.local/bin/cclenzz` that execs the *chosen* interpreter
  against the payload (the payload shebang is a fallback only). The wrapper is
  the sole file outside `~/.cclenzz`, because it must be on `PATH`. Data-dir and
  wrapper-dir overrides: `CCLENZZ_HOME` / `CCLENZZ_BIN_DIR`.
- **Channels.** `stable` (default, `/releases/latest`) and `snapshot` (first
  prerelease in `/releases`). Selected at install time (`--snapshot` /
  `CCLENZZ_CHANNEL`, or `CCLENZZ_VERSION=vX.Y.Z` to pin) and recorded in
  `~/.cclenzz/channel` so updates follow it.
- **Update** (`update.py`, stdlib only: `urllib`, `json`, `hashlib`,
  `tempfile`, `os.replace`). `cclenzz update` reads the recorded channel
  (`--snapshot`/`--stable` override and rewrite it), resolves the target
  release through an **injected fetcher seam** (`.json`/`.bytes` — a fake in
  tests, no live network), compares its `cclenzz-<ver>.pyz` version to
  `__version__`, and, if newer, downloads + checksum-verifies + atomically
  swaps `~/.cclenzz/cclenzz.pyz` (wrapper and interpreter untouched). No
  installed payload → it prints the install one-liner; network failure →
  a one-line error and exit 1, never a traceback (degrade-never-crash, this
  time on the user's own network weather).
- **Releasing (local, no CI).** Two `scripts/` drive the entire release
  mechanism; both refuse a dirty tree, require `main` synced with `origin`,
  and require `gh` authenticated. `scripts/release.sh <X.Y.Z>` runs the test
  gate, bumps the version in `pyproject.toml` + the `__init__.py` fallback,
  moves `CHANGELOG.md`'s `[Unreleased]` entries under `[X.Y.Z]`, builds +
  smoke-tests the `.pyz` before touching `origin`, then commits/tags `vX.Y.Z`,
  pushes, and publishes a full GitHub release (the changelog section becomes
  the notes) — the stable channel's `/releases/latest`. `scripts/snapshot.sh`
  temporarily stamps `X.Y.Z-dev+<shortsha>` (restored on exit; nothing
  committed), builds, and publishes a **prerelease** tagged
  `snapshot-YYYYMMDD-<shortsha>` — the snapshot channel's first prerelease.
  See `docs/RELEASING.md` for the operator runbook.
