<p align="center">
  <img src="assets/cclenzz-logo.png" alt="CCLenzz" width="360">
</p>

<p align="center">
  <a href="https://github.com/VitalyKheifets/CCLenzz/releases/latest"><img src="https://img.shields.io/github/v/release/VitalyKheifets/CCLenzz?sort=semver" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License: Apache-2.0"></a>
  <a href="#requirements"><img src="https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux-lightgrey" alt="Platforms: macOS · Linux"></a>
  <a href="#requirements"><img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+"></a>
</p>

CCLenzz renders a live, tabbed terminal view of your Claude Code sessions,
read straight from `~/.claude/projects/*/*.jsonl`. Every prompt and tool call
is one line. New sessions open automatically as tabs. On top of the live
view, it can run an optional **LLM intent audit** that scores, per prompt,
whether what Claude *did* matched what you *asked for* — plus a one-key
**explain** for any single row.

```
┌─ 1 my-project ● ──┬─ 2 other-repo ○ ─────────────────────────┐
│ ▸ you: refactor the parser to stream input                   │
│   ├─ read  parser.py                                         │
│   ├─ edit  parser.py                          aligned · 92   │
│   └─ bash  python3 -m pytest                                 │
│ ▸ you: now add a --json flag                    partial · 64 │
└──────────────────────────────────────────────────────────────┘
```

- **Zero dependencies.** Python 3.11+ standard library only. No `pip`
  install required, no daemon.
- **Read-only.** CCLenzz never writes anything under `~/.claude` — not even
  the audit runs (`--no-session-persistence`). Its own state lives in
  `~/.cclenzz`.
- **No secrets.** The audit reuses the `claude` login already on your
  `PATH` — CCLenzz holds no API key.
- **Crash-proof.** Malformed or schema-drifted transcripts degrade
  gracefully; the parser never throws.
- **Any terminal.** Truecolor + Nerd Font look best, but everything degrades
  cleanly to 256-color, 16-color, and monochrome/ASCII.

## Requirements

- **Python ≥ 3.11** (standard library only).
- A terminal.
- For the audit/explain features only: the [`claude`](https://claude.com/claude-code)
  CLI on your `PATH`, already logged in.

## Install

CCLenzz needs **Python ≥ 3.11** already on your machine — the installer
hard-stops without it. If you don't have it: `brew install python@3.12`
(macOS) or `apt install python3.12` (Debian/Ubuntu), or use `pyenv`. Windows
is supported via WSL (stdlib `curses` doesn't exist on native Windows).

One-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/VitalyKheifets/CCLenzz/main/install.sh | bash
```

This downloads a single `cclenzz-<ver>.pyz` — a plain Python
[zipapp](https://docs.python.org/3/library/zipapp.html), inspectable and with
no unsigned-binary/Gatekeeper step — verifies its checksum, and installs it to
`~/.cclenzz/cclenzz.pyz` with a wrapper at `~/.local/bin/cclenzz`. Everything
CCLenzz owns lives under `~/.cclenzz`; `rm -rf ~/.cclenzz` (plus that one
wrapper) fully uninstalls. The install is idempotent — re-run it any time to
upgrade in place.

**Update**: `cclenzz update`.

**Try snapshots** (bleeding-edge prereleases): install with `--snapshot`
(`curl … | bash -s -- --snapshot`) or run `cclenzz update --snapshot` to track
the latest prerelease; return to the release channel with
`cclenzz update --stable`.

**Run from source** — equivalent, no install step:

```bash
git clone https://github.com/VitalyKheifets/CCLenzz
cd CCLenzz
./cclenzz
```

The first run opens a short setup wizard (theme, icons, color, auto-audit)
and writes `~/.cclenzz/config.toml`. Then the TUI opens on your newest
Claude Code session; start a session in another terminal and it appears as a
new tab automatically.

## Commands

```bash
./cclenzz            # open the live tabbed TUI
./cclenzz setup      # (re)run the setup wizard
./cclenzz doctor     # print detected terminal capabilities + environment checks
./cclenzz --version
```

## Keys

| Key | Action |
|---|---|
| `j`/`k`, arrows, `Ctrl-D`/`Ctrl-U`, `g`/`G` | move / half-page / top / bottom |
| `{` / `}` | previous / next prompt |
| `→` / `Enter` / `Space` | open: unfold turn → expand details (follows audit citations) |
| `←` | close: collapse → fold → jump to parent |
| `z` | fold / unfold all turns |
| `[` / `]`, `Tab`, `1`–`9` | switch tabs |
| `l` | session picker (fuzzy search, live preview) |
| `d` | close tab (won't auto-reopen) |
| `f` / `p` | follow live / pause |
| `e`, `c`/`C` | filter: errors only / cycle category |
| `/`, `n`/`N` | search / next / previous match |
| `a` | run the intent audit on this session |
| `m` | toggle auto-audit for this run |
| `?` | explain the row under the cursor (press again to cancel) |
| `x` | cancel the running audit/explain |
| `y` / `Y` | yank the row's argument / full detail |
| `o` / `O` | open detail in `$PAGER` / file in `$EDITOR` |
| `t`, `w` | toggle timestamps / detail wrapping |
| `h` | help · `q` quit · `Esc` clears search/toast/filters (never quits) |

Mouse is supported where available: click to select, click tabs, middle-click
closes a tab, wheel scrolls, double-click expands.

## The intent audit

Press `a` (or set `auto_audit = true` to audit each turn as it completes).
CCLenzz distills the session — prompts, tool calls, results, sub-agents
inlined; never file bodies — and asks a judge model via your `claude` CLI for
one verdict per prompt:

- **alignment** 0–100, shown as `aligned` (≥85) / `partial` (≥60) / `drift`,
  with specific defects (ignored constraint, false claim, unrequested
  change, …) that cite the offending rows — press `→` on a citation to jump
  to it.
- **confidence** 0–100 — how much evidence the transcript actually contains;
  low-confidence verdicts render dimmed rather than shouty.

Verdicts, explanations, and accumulated cost are cached in
`~/.cclenzz/sessions/` and survive restarts; when a session grows past its
last audit, the badges dim until you re-audit.

**This costs money** — it runs real model calls through your `claude`
account. Defaults: `opus` for audits, `haiku` for explains; both
configurable. The judge runs with all tools disabled and leaves no session
history behind.

## Configuration

Everything lives in `~/.cclenzz/config.toml` (no env vars, no flags):

| Key | Default | Meaning |
|---|---|---|
| `theme` | `"auto"` | `auto` / `dark` / `light` |
| `icons` | `"auto"` | `auto` / `nerd` / `unicode` / `ascii` (nerd is opt-in) |
| `color` | `"auto"` | `auto` / `always` / `never` (`NO_COLOR` always wins) |
| `auto_audit` | `false` | audit each turn automatically as it completes |
| `audit_model` | `"opus"` | model for the intent audit |
| `explain_model` | `"haiku"` | model for `?` explanations |
| `interval` | `1.0` | base poll interval in seconds (adaptive around it) |
| `ambiwidth` | `1` | set `2` if your terminal renders ambiguous-width glyphs wide |
| `projects_glob` | `"~/.claude/projects/*/*.jsonl"` | where to find sessions |
| `claude_bin` | `"claude"` | the CLI used for audit/explain |
| `persist` | `true` | cache audit results under `~/.cclenzz/sessions/` |
| `state_retention_days` | unset | prune cached results older than N days |

`cclenzz setup` rewrites the file interactively without losing your
customizations; `cclenzz doctor` verifies the whole environment.

## Development

```bash
pip install -e ".[dev]"
python3 -m pytest
```

The architecture (module layout, data model, audit contract, testing seams)
is documented in [docs/DESIGN.md](docs/DESIGN.md). In short: a stdlib-only
core (`src/cclenzz/`) that incrementally tails session JSONL, a curses TUI
whose logic layer is curses-free and tested headless, and an audit layer
that shells out to the `claude` CLI with a golden-tested prompt and JSON
schema.

## Contributing

Contributions go through **fork → PR**. PRs are reviewed and merged by the
maintainer; direct pushes and in-repo branches are disabled. Start by reading
[CONTRIBUTING.md](CONTRIBUTING.md) — it covers the PR standard, the hard
constraints (stdlib-only, never write under `~/.claude`, degrade-never-crash,
byte-exact goldens), and the local test/coverage gate. There is **no CI**: the
maintainer runs `python3 -m pytest` before merging, so a PR that fails tests
locally will be sent back.
