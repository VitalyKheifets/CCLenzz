# Changelog

All notable changes to CCLenzz are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut locally by `scripts/release.sh` (no CI); that script moves the
`## [Unreleased]` entries below into a dated version section and uses them as
the GitHub release notes. Keep new entries under `## [Unreleased]`.

## [Unreleased]

## [1.0.0] - 2026-08-14

### Added
- Read-only, tabbed curses TUI that tails Claude Code session transcripts
  (`~/.claude/projects/*/*.jsonl`), one row per prompt / tool call, with
  fold/expand, flagging, and logged-input diffs.
- Optional LLM "intent audit" that scores whether Claude's actions matched the
  user's intent, shelled out to the user's own `claude` CLI — CCLenzz holds no
  API key and never calls an endpoint itself.
- Single platform-independent `.pyz` zipapp distribution: `scripts/build.sh`,
  the `install.sh` one-liner (Python ≥ 3.11 preflight, stable/snapshot
  channels, checksum-verified download), and the `cclenzz update` self-update
  subcommand.

