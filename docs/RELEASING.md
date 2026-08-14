# Releasing CCLenzz

This is the operator runbook for cutting releases and snapshots. It's for the
maintainer — contributors never need it. **There is no CI:** the entire release
mechanism is two local scripts (`scripts/release.sh`, `scripts/snapshot.sh`)
that build the artifact on your machine and publish it via the `gh` CLI. See
[`docs/DESIGN.md §13`](DESIGN.md) for the design rationale behind the
distribution model.

## What ships

A single **platform-independent `cclenzz-<ver>.pyz`** — a stdlib
[`zipapp`](https://docs.python.org/3/library/zipapp.html) of the `cclenzz`
package. One file runs on any Python ≥ 3.11 on any OS/arch; there is nothing to
cross-compile or sign, so building on the maintainer's Mac is complete and
correct. `scripts/build.sh` produces it plus a `dist/SHA256SUMS`.

> **Asset naming is load-bearing.** The published asset must be exactly
> `cclenzz-<version>.pyz`. `install.sh` and `cclenzz update` parse that pattern
> off the GitHub API. Do not change it after the first public release.

## Prerequisites

- **Python ≥ 3.11** with `pytest` + `pytest-cov` importable (`pip install -e
  ".[dev]"`). The scripts probe `python3.13/3.12/3.11/python3` and a project
  `.venv`, so the maintainer's bare `python3` being older is fine. Override with
  `CCLENZZ_PYTHON`.
- The **[`gh` CLI](https://cli.github.com/)**, authenticated as the repo owner
  (`gh auth status`).
- A **clean tree on `main`, in sync with `origin/main`.** Both scripts refuse to
  run otherwise.

## The two channels

| Channel | What it tracks | Cut by | GitHub API endpoint |
|---|---|---|---|
| **stable** (default) | latest full release | `scripts/release.sh` | `/releases/latest` |
| **snapshot** | latest prerelease | `scripts/snapshot.sh` | first `prerelease` in `/releases` |

Users choose a channel at install time (`install.sh --snapshot` /
`CCLENZZ_CHANNEL=snapshot`, or `CCLENZZ_VERSION=vX.Y.Z` to pin) and switch after
the fact with `cclenzz update --snapshot` / `--stable`. The chosen channel is
recorded in `~/.cclenzz/channel` so updates follow it.

## Cut a stable release

Before you start, make sure `CHANGELOG.md`'s `## [Unreleased]` section actually
lists the changes going out — the script uses that section as the release notes
and **aborts if it's empty**.

```bash
scripts/release.sh X.Y.Z      # e.g. scripts/release.sh 1.0.1
```

The version must be valid SemVer, must not already be tagged (a `vX.Y.Z` tag
means it is already released — refused), and must not be older than the current
`pyproject.toml` baseline. Releasing the baseline itself (`X.Y.Z` equal to the
current version) is allowed — that is how the **first** release is cut, since
the baseline names the *next* version to ship. The script then, in order:

1. **Runs the full test gate** (`python3 -m pytest`, coverage gate included via
   `addopts`) — aborts on any failure.
2. **Bumps the version** in `pyproject.toml` and the `__version__` fallback in
   `src/cclenzz/__init__.py`.
3. **Moves the changelog**: `## [Unreleased]` entries become
   `## [X.Y.Z] - <today>`, and that section is captured as the release notes.
4. **Builds + smoke-tests** the `.pyz` *before touching `origin`*, so a broken
   build never leaves a pushed tag with no artifact behind it.
5. **Commits** `release: vX.Y.Z`, **tags** `vX.Y.Z`, and **pushes** the commit +
   tag.
6. **Publishes** a full GitHub release with `cclenzz-X.Y.Z.pyz` + `SHA256SUMS`,
   using the changelog section as the notes. `install.sh`'s stable channel
   (`/releases/latest`) picks it up.

The version-bump commit is pushed directly to `main` — the branch ruleset grants
admin bypass for exactly this.

## Cut a snapshot (prerelease)

Snapshots let early testers track `main` between stable releases. Nothing is
committed and the version files are restored on exit.

```bash
scripts/snapshot.sh           # runs the test gate by default
scripts/snapshot.sh --no-tests   # skip the gate (not recommended)
```

The script verifies the same preconditions (minus a version arg), **temporarily**
stamps the version `X.Y.Z-dev+<shortsha>` (patching `pyproject.toml` +
`__init__.py`, restored on exit), builds the `.pyz` + `SHA256SUMS`, pushes a tag
`snapshot-YYYYMMDD-<shortsha>`, and publishes a **prerelease**. `install.sh
--snapshot` / `cclenzz update --snapshot` pick up the newest prerelease.

## After publishing — verify

```bash
# Stable one-liner installs the new release:
curl -fsSL https://raw.githubusercontent.com/VitalyKheifets/CCLenzz/main/install.sh | bash
cclenzz --version

# Snapshot channel installs the prerelease:
curl -fsSL https://raw.githubusercontent.com/VitalyKheifets/CCLenzz/main/install.sh | bash -s -- --snapshot
```

Confirm the release page lists both `cclenzz-<ver>.pyz` and `SHA256SUMS`, and
that the notes match the changelog section.
