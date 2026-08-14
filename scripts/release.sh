#!/usr/bin/env bash
#
# release.sh <X.Y.Z> — cut a full STABLE release, locally, no CI.
#
#   scripts/release.sh 1.0.1
#
# This script is the entire stable-release mechanism. It:
#   1. Verifies preconditions (on main, clean, synced with origin, gh authed,
#      the arg is SemVer and greater than the current version).
#   2. Runs the full local test/coverage gate — abort on any failure.
#   3. Bumps the version in pyproject.toml + the __init__.py fallback string.
#   4. Moves CHANGELOG.md's [Unreleased] entries under [X.Y.Z] - <today>.
#   5. Builds + smoke-tests the .pyz (before touching origin, so a broken build
#      never leaves a pushed tag with no artifact behind it).
#   6. Commits `release: vX.Y.Z`, tags vX.Y.Z, pushes commit + tag.
#   7. Publishes a GitHub release with the .pyz + SHA256SUMS, using the moved
#      CHANGELOG section as the release notes. install.sh's stable channel
#      (/releases/latest) then picks it up.
#
# The .pyz is platform-independent, so building on the maintainer's Mac is safe
# and complete — there is nothing to cross-compile or sign.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

info() { printf '%s\n' "$*" >&2; }
die()  { printf 'release.sh: %s\n' "$*" >&2; exit 1; }

# --- Args --------------------------------------------------------------------
[ $# -eq 1 ] || die "usage: scripts/release.sh <X.Y.Z>"
NEW_VERSION="$1"
printf '%s' "$NEW_VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' \
  || die "version must be SemVer X.Y.Z (got '$NEW_VERSION')"

# --- Pick interpreters -------------------------------------------------------
# Tooling (tomllib, build) needs Python >= 3.11; the same gate install.sh
# applies, because the maintainer's bare `python3` may be an older system build.
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

# The test gate additionally needs pytest + pytest-cov importable (the coverage
# gate rides on plain `pytest` via addopts). Prefer the tooling interpreter,
# then a project virtualenv, then a bare interpreter that has them.
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
TESTPY="$(pick_test_python)" \
  || die "no Python >= 3.11 with pytest + pytest-cov found — run: pip install -e '.[dev]'"

# --- Preconditions -----------------------------------------------------------
command -v gh >/dev/null 2>&1 || die "the GitHub CLI 'gh' is required"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated — run: gh auth login"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "main" ] || die "must be on 'main' (currently on '$BRANCH')"

[ -z "$(git status --porcelain)" ] \
  || die "working tree is not clean — commit or stash changes first"

info "release.sh: fetching origin/main ..."
git fetch --quiet origin main || die "git fetch origin main failed"
[ "$(git rev-parse @)" = "$(git rev-parse origin/main)" ] \
  || die "local main is not in sync with origin/main — pull/push first"

CURRENT="$("$PY" - <<'PY'
import tomllib
with open("pyproject.toml", "rb") as fh:
    print(tomllib.load(fh)["project"]["version"])
PY
)"
[ -n "$CURRENT" ] || die "could not read the current version from pyproject.toml"
if ! "$PY" - "$CURRENT" "$NEW_VERSION" <<'PY'
import sys
def parse(v): return tuple(int(x) for x in v.split("-", 1)[0].split("."))
sys.exit(0 if parse(sys.argv[2]) > parse(sys.argv[1]) else 1)
PY
then
  die "new version $NEW_VERSION is not greater than current $CURRENT"
fi
info "release.sh: $CURRENT -> $NEW_VERSION"

# --- 1. Test gate ------------------------------------------------------------
# Plain pytest also enforces the coverage gate: addopts wires in --cov and
# [tool.coverage.report] fail_under fails the run below the threshold.
info "release.sh: running the test gate ($("$TESTPY" --version 2>&1)) ..."
"$TESTPY" -m pytest || die "tests failed — aborting release"

# --- 2. Bump version ---------------------------------------------------------
"$PY" - "$CURRENT" "$NEW_VERSION" <<'PY'
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

# --- 3. CHANGELOG: move [Unreleased] -> [X.Y.Z] - <today> --------------------
TODAY="$(date -u +%Y-%m-%d)"
NOTES_FILE="$(mktemp -t cclenzz-notes.XXXXXX)"
trap 'rm -f "$NOTES_FILE"' EXIT
"$PY" - "$NEW_VERSION" "$TODAY" "$NOTES_FILE" <<'PY'
import pathlib, sys
new, date, notes_path = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path("CHANGELOG.md")
lines = p.read_text(encoding="utf-8").splitlines()
try:
    ui = next(i for i, l in enumerate(lines)
              if l.strip().lower().startswith("## [unreleased]"))
except StopIteration:
    sys.stderr.write("CHANGELOG.md has no '## [Unreleased]' section\n"); sys.exit(2)
ni = next((i for i in range(ui + 1, len(lines)) if lines[i].startswith("## [")), len(lines))
body = lines[ui + 1:ni]
while body and not body[0].strip(): body.pop(0)
while body and not body[-1].strip(): body.pop()
if not body:
    sys.stderr.write("no entries under '## [Unreleased]' — add changelog notes "
                     "before releasing\n"); sys.exit(3)
out = lines[:ui + 1] + ["", f"## [{new}] - {date}", ""] + body + [""] + lines[ni:]
p.write_text("\n".join(out) + "\n", encoding="utf-8")
pathlib.Path(notes_path).write_text("\n".join(body) + "\n", encoding="utf-8")
PY

# --- 4. Build + smoke test (before we touch origin) --------------------------
rm -rf "$REPO_DIR/dist"
info "release.sh: building the .pyz ..."
bash "$REPO_DIR/scripts/build.sh"
PYZ="$REPO_DIR/dist/cclenzz-${NEW_VERSION}.pyz"
[ -f "$PYZ" ] || die "expected build artifact $PYZ was not produced"
[ -f "$REPO_DIR/dist/SHA256SUMS" ] || die "expected dist/SHA256SUMS was not produced"

# --- 5. Commit, tag, push ----------------------------------------------------
git add pyproject.toml src/cclenzz/__init__.py CHANGELOG.md
git commit -m "release: v${NEW_VERSION}"
git tag "v${NEW_VERSION}"
info "release.sh: pushing commit + tag v${NEW_VERSION} ..."
git push origin main
git push origin "v${NEW_VERSION}"

# --- 6. Publish the GitHub release -------------------------------------------
info "release.sh: publishing GitHub release v${NEW_VERSION} ..."
gh release create "v${NEW_VERSION}" \
  "$PYZ" "$REPO_DIR/dist/SHA256SUMS" \
  --title "v${NEW_VERSION}" \
  --notes-file "$NOTES_FILE"

info "release.sh: done — v${NEW_VERSION} is live on the stable channel."
