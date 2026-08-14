#!/usr/bin/env bash
#
# build.sh — produce the single platform-independent distribution artifact:
#   dist/cclenzz-<version>.pyz   (a stdlib zipapp of the cclenzz package)
#   dist/SHA256SUMS              (checksum install.sh / cclenzz update verify)
#
# The .pyz runs on any Python >= 3.11 on any OS/arch — there is nothing to
# cross-compile. This script is standalone-runnable and is also the build step
# used by scripts/release.sh and scripts/snapshot.sh.
#
# The asset name is load-bearing: exactly `cclenzz-<version>.pyz`. install.sh
# parses this pattern — do not change it after the first public release.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

BUILD_DIR="$REPO/build"
DIST_DIR="$REPO/dist"
STAGE_DIR="$BUILD_DIR/stage"

# --- Pick a qualifying interpreter (>= 3.11) ---------------------------------
# The maintainer's default `python3` may be an older system build (this is the
# same >=3.11 gate install.sh applies), so probe explicitly rather than trust
# the bare name. zipapp, tomllib, and the smoke test all need 3.11+.
pick_python() {
  local candidate ver
  for candidate in python3.13 python3.12 python3.11 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    ver="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || continue
    case "$ver" in
      3.1[1-9]|3.[2-9][0-9]|[4-9].*) echo "$candidate"; return 0 ;;
    esac
  done
  return 1
}

PY="$(pick_python)" || {
  echo "build.sh: Python >= 3.11 required to build the .pyz (found none)" >&2
  exit 1
}
echo "build.sh: using $($PY --version) ($PY)"

# --- Resolve the version from the single source of truth (pyproject.toml) -----
VERSION="$("$PY" - <<'PY'
import tomllib
with open("pyproject.toml", "rb") as fh:
    print(tomllib.load(fh)["project"]["version"])
PY
)"
[ -n "$VERSION" ] || { echo "build.sh: could not read version from pyproject.toml" >&2; exit 1; }
PYZ="cclenzz-${VERSION}.pyz"
echo "build.sh: building $PYZ"

# --- Stage a clean copy of the package ---------------------------------------
# zipapp archives a directory tree; stage `cclenzz/` alone so the artifact holds
# exactly the package (no egg-info, no __pycache__) and imports resolve against
# a top-level `cclenzz` package inside the archive.
rm -rf "$BUILD_DIR"
mkdir -p "$STAGE_DIR" "$DIST_DIR"
cp -R "$REPO/src/cclenzz" "$STAGE_DIR/cclenzz"
find "$STAGE_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE_DIR" -name '*.pyc' -delete

# Entry point `cclenzz.cli:main`. We write the archive's top-level __main__.py
# by hand instead of passing zipapp's `-m` flag: `-m` generates a stub that
# calls `main()` and discards its return value, which would silently collapse
# every exit code to 0 and break the CLI contract (unknown command -> 1,
# non-interactive -> 2). This stub propagates the code and mirrors the source
# launcher's KeyboardInterrupt handling.
cat > "$STAGE_DIR/__main__.py" <<'PY'
import sys

from cclenzz.cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
PY

# --- Build the zipapp ---------------------------------------------------------
# The shebang is only a fallback; the install wrapper execs the chosen
# interpreter against the .pyz directly (see Phase 2), so it never relies on it.
rm -f "$DIST_DIR/$PYZ"
"$PY" -m zipapp "$STAGE_DIR" \
  -p "/usr/bin/env python3" \
  -o "$DIST_DIR/$PYZ"

# --- Smoke test ---------------------------------------------------------------
OUT="$("$PY" "$DIST_DIR/$PYZ" --version)"
if [ "$OUT" != "cclenzz ${VERSION}" ]; then
  echo "build.sh: smoke test failed — expected 'cclenzz ${VERSION}', got '$OUT'" >&2
  exit 1
fi
echo "build.sh: smoke test OK — $OUT"

# --- Checksums ----------------------------------------------------------------
# Prefer sha256sum (Linux); fall back to shasum -a 256 (macOS). Write paths
# relative to dist/ so `-c` verifies from inside that directory.
cd "$DIST_DIR"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$PYZ" > SHA256SUMS
else
  shasum -a 256 "$PYZ" > SHA256SUMS
fi

echo "build.sh: wrote dist/$PYZ and dist/SHA256SUMS"
