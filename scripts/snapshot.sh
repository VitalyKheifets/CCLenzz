#!/usr/bin/env bash
#
# snapshot.sh — publish a bleeding-edge SNAPSHOT prerelease, locally, no CI.
#
#   scripts/snapshot.sh
#
# Snapshots let early testers track `main` between stable releases. This script:
#   1. Verifies preconditions (on main, clean tree, synced with origin, gh
#      authed) — same as release.sh minus the version argument.
#   2. Runs the local test gate by default (snapshots are for testers but must
#      not be broken); pass --no-tests to skip.
#   3. Builds the .pyz stamped `X.Y.Z-dev+<shortsha>` by *temporarily* patching
#      the version in pyproject.toml + the __init__.py fallback (restored on
#      exit — nothing is committed; the tag points at the clean HEAD).
#   4. Pushes tag `snapshot-YYYYMMDD-<shortsha>` and publishes a GitHub
#      PRERELEASE with the .pyz + SHA256SUMS. install.sh's snapshot channel
#      (first prerelease in /releases) then picks it up.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

info() { printf '%s\n' "$*" >&2; }
die()  { printf 'snapshot.sh: %s\n' "$*" >&2; exit 1; }

RUN_TESTS=1
for arg in "$@"; do
  case "$arg" in
    --no-tests) RUN_TESTS=0 ;;
    *) die "unknown argument: $arg (usage: scripts/snapshot.sh [--no-tests])" ;;
  esac
done

# --- Pick interpreters (same policy as release.sh) ---------------------------
pick_python() {
  local c ver
  for c in "${CCLENZZ_PYTHON:-}" python3.13 python3.12 python3.11 python3; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || continue
    ver="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)" || continue
    case "$ver" in 3.1[1-9]|3.[2-9][0-9]|[4-9].*) command -v "$c"; return 0 ;; esac
  done
  return 1
}
PY="$(pick_python)" || die "Python >= 3.11 required (set CCLENZZ_PYTHON to point at one)"

pick_test_python() {
  local c
  for c in "${CCLENZZ_PYTHON:-}" "$PY" "$REPO_DIR/.venv/bin/python" \
           python3.13 python3.12 python3.11 python3; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || [ -x "$c" ] || continue
    "$c" -c 'import sys; assert sys.version_info >= (3,11); import pytest, pytest_cov' >/dev/null 2>&1 \
      && { echo "$c"; return 0; }
  done
  return 1
}

# --- Preconditions -----------------------------------------------------------
command -v gh >/dev/null 2>&1 || die "the GitHub CLI 'gh' is required"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated — run: gh auth login"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "main" ] || die "must be on 'main' (currently on '$BRANCH')"
[ -z "$(git status --porcelain)" ] \
  || die "working tree is not clean — commit or stash changes first"

info "snapshot.sh: fetching origin/main ..."
git fetch --quiet origin main || die "git fetch origin main failed"
[ "$(git rev-parse @)" = "$(git rev-parse origin/main)" ] \
  || die "local main is not in sync with origin/main — pull/push first"

# --- Test gate (default on) --------------------------------------------------
if [ "$RUN_TESTS" -eq 1 ]; then
  TESTPY="$(pick_test_python)" \
    || die "no Python >= 3.11 with pytest + pytest-cov found — run: pip install -e '.[dev]' (or --no-tests)"
  info "snapshot.sh: running the test gate ($("$TESTPY" --version 2>&1)) ..."
  "$TESTPY" -m pytest || die "tests failed — aborting snapshot"
else
  info "snapshot.sh: skipping tests (--no-tests)"
fi

# --- Compute tag + dev version -----------------------------------------------
SHORTSHA="$(git rev-parse --short HEAD)"
TAG="snapshot-$(date -u +%Y%m%d)-${SHORTSHA}"
CURRENT="$("$PY" - <<'PY'
import tomllib
with open("pyproject.toml", "rb") as fh:
    print(tomllib.load(fh)["project"]["version"])
PY
)"
[ -n "$CURRENT" ] || die "could not read the current version from pyproject.toml"
DEV_VERSION="${CURRENT}-dev+${SHORTSHA}"
info "snapshot.sh: building $DEV_VERSION as prerelease $TAG"

# --- Temporarily stamp the dev version, restore on exit ----------------------
# build.sh reads the version from pyproject.toml and the .pyz reports the
# __init__.py fallback (zipapps carry no *.dist-info), so both must carry the
# dev string for the artifact — and the smoke test — to agree. These edits are
# never committed; the trap restores the clean HEAD versions no matter what.
RESTORE=0
restore_versions() {
  [ "$RESTORE" -eq 1 ] || return 0
  git checkout -- pyproject.toml src/cclenzz/__init__.py 2>/dev/null || true
}
trap restore_versions EXIT

RESTORE=1
"$PY" - "$CURRENT" "$DEV_VERSION" <<'PY'
import pathlib, sys
cur, new = sys.argv[1], sys.argv[2]
for path, needle in (("pyproject.toml", f'version = "{cur}"'),
                     ("src/cclenzz/__init__.py", f'__version__ = "{cur}"')):
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8")
    if needle not in text:
        sys.stderr.write(f"could not find {needle!r} in {path}\n")
        sys.exit(2)
    p.write_text(text.replace(needle, needle.replace(cur, new, 1), 1), encoding="utf-8")
PY

# --- Build (dev-stamped), then restore before touching origin ----------------
rm -rf "$REPO_DIR/dist"
info "snapshot.sh: building the .pyz ..."
bash "$REPO_DIR/scripts/build.sh"
PYZ="$REPO_DIR/dist/cclenzz-${DEV_VERSION}.pyz"
[ -f "$PYZ" ] || die "expected build artifact $PYZ was not produced"
[ -f "$REPO_DIR/dist/SHA256SUMS" ] || die "expected dist/SHA256SUMS was not produced"

restore_versions
RESTORE=0

# --- Push tag + publish prerelease -------------------------------------------
info "snapshot.sh: pushing tag $TAG ..."
git tag "$TAG"
git push origin "$TAG"

info "snapshot.sh: publishing prerelease $TAG ..."
gh release create "$TAG" \
  "$PYZ" "$REPO_DIR/dist/SHA256SUMS" \
  --prerelease \
  --title "$TAG" \
  --notes "Snapshot build for testing (${DEV_VERSION}). Bleeding-edge; not a stable release."

info "snapshot.sh: done — $TAG is live on the snapshot channel."
