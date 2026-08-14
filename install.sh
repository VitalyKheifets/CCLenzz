#!/usr/bin/env bash
#
# install.sh — one-command installer for CCLenzz.
#
#   curl -fsSL https://raw.githubusercontent.com/VitalyKheifets/CCLenzz/main/install.sh | bash
#
# What it does, in order:
#   1. Hard Python preflight — pick a Python >= 3.11 or abort (logged).
#   2. Confirm a supported OS (macOS / Linux; Windows -> WSL hint).
#   3. Resolve a release for the chosen channel (stable | snapshot | pinned)
#      off the GitHub API, parsed with the chosen Python (no jq/grep).
#   4. Download the cclenzz-<ver>.pyz + SHA256SUMS, verify the checksum.
#   5. Install the payload to ~/.cclenzz/cclenzz.pyz and an executable wrapper
#      to ~/.local/bin/cclenzz that execs the chosen interpreter against it.
#
# No sudo, ever. CCLenzz owns one directory (~/.cclenzz); the wrapper is the
# only file placed outside it, because it must be on PATH. `rm -rf ~/.cclenzz`
# plus that wrapper fully uninstalls.
#
# Overrides (env):
#   CCLENZZ_CHANNEL=snapshot   track prereleases (same as --snapshot arg)
#   CCLENZZ_VERSION=vX.Y.Z      pin an exact release tag (overrides channel)
#   CCLENZZ_HOME=<dir>          data dir (default ~/.cclenzz)
#   CCLENZZ_BIN_DIR=<dir>       wrapper dir (default ~/.local/bin)
set -euo pipefail

REPO="VitalyKheifets/CCLenzz"
API="https://api.github.com/repos/${REPO}"

CCLENZZ_HOME="${CCLENZZ_HOME:-$HOME/.cclenzz}"
CCLENZZ_BIN_DIR="${CCLENZZ_BIN_DIR:-$HOME/.local/bin}"
LOG="$CCLENZZ_HOME/install.log"

# Channel: default stable; --snapshot arg or CCLENZZ_CHANNEL=snapshot opts in.
CHANNEL="${CCLENZZ_CHANNEL:-stable}"
for arg in "$@"; do
  case "$arg" in
    --snapshot) CHANNEL="snapshot" ;;
    --stable)   CHANNEL="stable" ;;
    *) echo "install.sh: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

info()  { printf '%s\n' "$*" >&2; }
die()   { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

# Append a timestamped diagnostic line under ~/.cclenzz (NEVER ~/.claude).
log_line() {
  mkdir -p "$CCLENZZ_HOME" 2>/dev/null || true
  printf '%s\t%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG" 2>/dev/null || true
}

# --- 1. Python preflight — the hard gate -------------------------------------
# Probe newest-first and pick the first interpreter reporting >= 3.11. The
# user's bare `python3` may be an older system build, so we never trust the name.
PYBIN=""
HIGHEST="none"
for candidate in python3.13 python3.12 python3.11 python3; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  ver="$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)" || continue
  HIGHEST="$ver"
  case "$ver" in
    3.1[1-9]|3.[2-9][0-9]|[4-9].*)
      PYBIN="$(command -v "$candidate")"
      break ;;
  esac
done

OS="$(uname -s 2>/dev/null || echo unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"

if [ -z "$PYBIN" ]; then
  log_line "preflight FAILED: Python 3.11+ required (highest found: $HIGHEST) os=$OS arch=$ARCH"
  info "cclenzz needs Python 3.11 or newer, but the highest available is: $HIGHEST"
  info ""
  info "Install a newer Python, then re-run the installer:"
  info "  macOS:         brew install python@3.12"
  info "  Debian/Ubuntu: sudo apt install python3.12"
  info "  or use pyenv:  https://github.com/pyenv/pyenv"
  die "Python 3.11+ required"
fi
info "cclenzz: using $("$PYBIN" --version 2>&1) ($PYBIN)"

# --- 2. OS gate --------------------------------------------------------------
case "$OS" in
  Darwin|Linux) : ;;
  *)
    log_line "preflight FAILED: unsupported OS '$OS' arch=$ARCH (curses needs macOS/Linux)"
    info "cclenzz uses the stdlib 'curses' module, which native Windows lacks."
    info "On Windows, install and run cclenzz inside WSL (Windows Subsystem for Linux)."
    die "unsupported OS: $OS (use WSL on Windows)" ;;
esac

# --- 3. Resolve the release --------------------------------------------------
# CCLENZZ_VERSION pins an exact tag and overrides the channel.
if [ -n "${CCLENZZ_VERSION:-}" ]; then
  RELEASE_URL="${API}/releases/tags/${CCLENZZ_VERSION}"
  info "cclenzz: resolving pinned release ${CCLENZZ_VERSION}"
elif [ "$CHANNEL" = "snapshot" ]; then
  RELEASE_URL="${API}/releases"     # first prerelease element (parsed below)
  info "cclenzz: resolving latest snapshot (prerelease)"
else
  RELEASE_URL="${API}/releases/latest"
  info "cclenzz: resolving latest stable release"
fi

# Parse the GitHub JSON with $PYBIN (stdlib json) — robust, dependency-free.
# Emits two tab-separated lines: the tag, then the cclenzz-*.pyz asset URL.
# CHANNEL is passed in the environment so a pinned/latest single-object payload
# and the snapshot list are both handled by one parser.
read_release() {
  CCLENZZ_CHANNEL="$CHANNEL" CCLENZZ_PIN="${CCLENZZ_VERSION:-}" \
  "$PYBIN" - "$RELEASE_URL" <<'PY'
import json, os, sys, urllib.request

url = sys.argv[1]
req = urllib.request.Request(
    url, headers={"User-Agent": "cclenzz-install",
                  "Accept": "application/vnd.github+json"})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
except Exception as e:               # network / HTTP / decode
    sys.stderr.write("could not reach the GitHub release API: %s\n" % e)
    sys.exit(3)

# The list endpoint (snapshot channel) returns an array; pick the first
# prerelease. Everything else returns a single release object.
if isinstance(data, list):
    rel = next((r for r in data if r.get("prerelease")), None)
    if rel is None:
        sys.stderr.write("no snapshot prerelease is published yet\n")
        sys.exit(4)
else:
    rel = data
    if "tag_name" not in rel:
        sys.stderr.write("release not found\n")
        sys.exit(4)

pyz = None
for a in rel.get("assets", []):
    n = a.get("name", "")
    if n.startswith("cclenzz-") and n.endswith(".pyz"):
        pyz = a.get("browser_download_url")
        break
if not pyz:
    sys.stderr.write("release %s has no cclenzz-*.pyz asset\n" % rel.get("tag_name"))
    sys.exit(4)

# SHA256SUMS lives beside the .pyz in the same release; derive its URL from the
# .pyz URL so a single asset lookup suffices.
sums = pyz.rsplit("/", 1)[0] + "/SHA256SUMS"
print(rel["tag_name"])
print(pyz)
print(sums)
PY
}

RELEASE_INFO="$(read_release)" || die "could not resolve a release on the '$CHANNEL' channel"
TAG="$(printf '%s\n' "$RELEASE_INFO" | sed -n '1p')"
PYZ_URL="$(printf '%s\n' "$RELEASE_INFO" | sed -n '2p')"
SUMS_URL="$(printf '%s\n' "$RELEASE_INFO" | sed -n '3p')"
PYZ_NAME="$(basename "$PYZ_URL")"
[ -n "$TAG" ] && [ -n "$PYZ_URL" ] || die "release resolution returned no asset"
info "cclenzz: found $TAG ($PYZ_NAME)"

# --- 4. Download + verify ----------------------------------------------------
TMPDIR="$(mktemp -d 2>/dev/null || mktemp -d -t cclenzz)"
trap 'rm -rf "$TMPDIR"' EXIT

download() {  # download <url> <dest>
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" "$1"
  else
    die "need curl or wget to download the release"
  fi
}

download "$PYZ_URL"  "$TMPDIR/$PYZ_NAME" || die "failed to download $PYZ_NAME"
download "$SUMS_URL" "$TMPDIR/SHA256SUMS" || die "failed to download SHA256SUMS"

# Verify from inside the temp dir so the checksum file's relative name matches.
(
  cd "$TMPDIR"
  # SHA256SUMS may list other releases' files; check only the one we fetched.
  grep " ${PYZ_NAME}\$" SHA256SUMS > SHA256SUMS.one 2>/dev/null || \
    grep "  ${PYZ_NAME}\$" SHA256SUMS > SHA256SUMS.one 2>/dev/null || \
    { echo "no checksum for $PYZ_NAME"; exit 1; }
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c SHA256SUMS.one >/dev/null
  else
    shasum -a 256 -c SHA256SUMS.one >/dev/null
  fi
) || {
  log_line "checksum verification FAILED for $PYZ_NAME ($TAG)"
  die "checksum verification failed for $PYZ_NAME — aborting"
}
info "cclenzz: checksum verified"

# --- 5. Install payload + wrapper --------------------------------------------
mkdir -p "$CCLENZZ_HOME" "$CCLENZZ_BIN_DIR"

# Atomic payload swap: copy to a temp name in the data dir, then mv into place.
PAYLOAD="$CCLENZZ_HOME/cclenzz.pyz"
cp "$TMPDIR/$PYZ_NAME" "$CCLENZZ_HOME/.cclenzz.pyz.new"
mv -f "$CCLENZZ_HOME/.cclenzz.pyz.new" "$PAYLOAD"

# Wrapper bakes in the chosen interpreter — the payload shebang is ignored, so
# an older default python3 on PATH never gets a chance to run it.
WRAPPER="$CCLENZZ_BIN_DIR/cclenzz"
cat > "$TMPDIR/cclenzz.wrapper" <<EOF
#!/usr/bin/env bash
# cclenzz launcher — generated by install.sh. Execs the interpreter chosen at
# install time against the payload in \$CCLENZZ_HOME (default ~/.cclenzz).
exec "$PYBIN" "\${CCLENZZ_HOME:-\$HOME/.cclenzz}/cclenzz.pyz" "\$@"
EOF
chmod +x "$TMPDIR/cclenzz.wrapper"
mv -f "$TMPDIR/cclenzz.wrapper" "$WRAPPER"

# Record the channel so `cclenzz update` follows it by default.
printf '%s\n' "$CHANNEL" > "$CCLENZZ_HOME/channel"
log_line "installed $TAG ($PYZ_NAME) channel=$CHANNEL py=$PYBIN os=$OS arch=$ARCH"

# --- 6. PATH hint + summary --------------------------------------------------
case ":$PATH:" in
  *":$CCLENZZ_BIN_DIR:"*) ON_PATH=1 ;;
  *) ON_PATH=0 ;;
esac

INSTALLED_VER="$("$WRAPPER" --version 2>/dev/null || echo "cclenzz $TAG")"
info ""
info "cclenzz installed: $INSTALLED_VER"
info "  payload: $PAYLOAD"
info "  wrapper: $WRAPPER"
info "  channel: $CHANNEL"

if [ "$ON_PATH" -eq 0 ]; then
  info ""
  info "$CCLENZZ_BIN_DIR is not on your PATH. Add it:"
  info "  zsh:  echo 'export PATH=\"$CCLENZZ_BIN_DIR:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
  info "  bash: echo 'export PATH=\"$CCLENZZ_BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
fi

info ""
info "Run:      cclenzz"
info "Update:   cclenzz update            (track the latest $CHANNEL build)"
info "Snapshot: cclenzz update --snapshot (try the newest prerelease)"
info "Stable:   cclenzz update --stable   (back to full releases)"
