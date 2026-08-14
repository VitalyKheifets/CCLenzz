from __future__ import annotations

"""``cclenzz update`` — self-update the installed ``.pyz`` payload.

CCLenzz ships as a single platform-independent zipapp installed by
``install.sh`` to ``~/.cclenzz/cclenzz.pyz`` (see ``docs/DESIGN.md`` §
"Distribution"). This module re-downloads that payload from the same GitHub
release channel the installer used and atomically swaps it in place — the
wrapper at ``~/.local/bin/cclenzz`` and its baked-in interpreter are never
touched.

Stdlib-only, like everything else (constraint #1): ``urllib.request`` for the
network, ``json`` to parse the GitHub API, ``hashlib`` to verify the checksum,
``os.replace`` for the atomic swap. There is no live network in tests — the
release resolution and version-compare logic take an injected ``fetcher`` seam
(any object with ``.json(url)`` and ``.bytes(url)``), so the pure logic is
exercised with a fake. Failures degrade to a one-line message and ``exit 1``,
never a traceback (constraint #4 — this is the *user's* machine, treat network
weather like other people's data).
"""

import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

from . import __version__

# --- Release source (must match install.sh) ---------------------------------
REPO = "VitalyKheifets/CCLenzz"
API = f"https://api.github.com/repos/{REPO}"
INSTALL_ONE_LINER = (
    "curl -fsSL "
    "https://raw.githubusercontent.com/VitalyKheifets/CCLenzz/main/install.sh | bash"
)


class UpdateError(Exception):
    """A recoverable, user-facing update failure. Rendered as one stderr line;
    never surfaces as a traceback."""


class _HttpFetcher:
    """Default network seam. Tests inject a fake with the same two methods."""

    _HEADERS = {"User-Agent": "cclenzz-update", "Accept": "application/vnd.github+json"}

    def json(self, url):
        req = urllib.request.Request(url, headers=self._HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (https only)
            return json.load(resp)

    def bytes(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "cclenzz-update"})
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            return resp.read()


# --- Paths -------------------------------------------------------------------
def default_home():
    """The CCLenzz data dir. Mirrors install.sh: ``CCLENZZ_HOME`` overrides,
    else ``~/.cclenzz``. This is the *only* place a payload ever lives."""
    return os.environ.get("CCLENZZ_HOME") or os.path.join(
        os.path.expanduser("~"), ".cclenzz")


def payload_path(home):
    return os.path.join(home, "cclenzz.pyz")


def channel_path(home):
    return os.path.join(home, "channel")


# --- Channel -----------------------------------------------------------------
_CHANNELS = ("stable", "snapshot")


def read_channel(home):
    """Channel recorded by the installer (``~/.cclenzz/channel``). Anything
    missing or unrecognised degrades to ``stable`` — never crash on a hand-edited
    sidecar."""
    try:
        with open(channel_path(home), encoding="utf-8") as fh:
            val = fh.read().strip()
    except OSError:
        return "stable"
    return val if val in _CHANNELS else "stable"


def write_channel(home, channel):
    """Persist the channel so later ``cclenzz update`` runs follow it by
    default. Best-effort: a write failure must not abort an otherwise-fine
    update, so callers ignore errors here."""
    os.makedirs(home, exist_ok=True)
    tmp = channel_path(home) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(channel + "\n")
    os.replace(tmp, channel_path(home))


# --- Release resolution ------------------------------------------------------
class Release:
    """A resolved release: the tag, the ``cclenzz-<ver>.pyz`` asset, and the
    ``SHA256SUMS`` asset. ``version`` is parsed from the asset name — the same
    string ``__version__`` reports — so an equality check tells us if we are
    already current on either channel."""

    __slots__ = ("tag", "pyz_name", "pyz_url", "sums_url")

    def __init__(self, tag, pyz_name, pyz_url, sums_url):
        self.tag = tag
        self.pyz_name = pyz_name
        self.pyz_url = pyz_url
        self.sums_url = sums_url

    @property
    def version(self):
        # `cclenzz-<version>.pyz` — the pattern install.sh also parses.
        return self.pyz_name[len("cclenzz-"):-len(".pyz")]


def _pick_release_json(fetcher, channel):
    if channel == "snapshot":
        releases = fetcher.json(f"{API}/releases")
        for rel in releases:
            if rel.get("prerelease"):
                return rel
        raise UpdateError("no snapshot prerelease is published yet")
    # stable — /releases/latest already excludes prereleases and drafts.
    return fetcher.json(f"{API}/releases/latest")


def resolve_release(fetcher, channel):
    """Resolve the newest release on ``channel`` to a :class:`Release`.

    stable → ``/releases/latest``; snapshot → first ``prerelease`` in
    ``/releases``. Raises :class:`UpdateError` if the expected assets
    (``cclenzz-*.pyz`` + ``SHA256SUMS``) are absent."""
    rel = _pick_release_json(fetcher, channel)
    tag = rel.get("tag_name") or "?"
    assets = {}
    for a in rel.get("assets", []):
        name = a.get("name")
        url = a.get("browser_download_url")
        if name and url:
            assets[name] = url

    pyz_name = next(
        (n for n in assets
         if n.startswith("cclenzz-") and n.endswith(".pyz")), None)
    if pyz_name is None or "SHA256SUMS" not in assets:
        raise UpdateError(
            f"release {tag} is missing the cclenzz .pyz or SHA256SUMS asset")
    return Release(tag, pyz_name, assets[pyz_name], assets["SHA256SUMS"])


# --- Checksums ---------------------------------------------------------------
def expected_sha(sums_text, pyz_name):
    """Pull the digest for ``pyz_name`` out of a ``SHA256SUMS`` body
    (``<hex>  <filename>`` per line, as ``sha256sum``/``shasum -a 256`` emit)."""
    for line in sums_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0], parts[1].strip().lstrip("*")
        if os.path.basename(name) == pyz_name:
            return digest.lower()
    raise UpdateError(f"SHA256SUMS has no entry for {pyz_name}")


def download_payload(fetcher, release):
    """Fetch the ``.pyz`` bytes and verify them against ``SHA256SUMS``.
    Returns the verified bytes; raises :class:`UpdateError` on mismatch."""
    data = fetcher.bytes(release.pyz_url)
    sums = fetcher.bytes(release.sums_url)
    if isinstance(sums, bytes):
        sums = sums.decode("utf-8", "replace")
    want = expected_sha(sums, release.pyz_name)
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise UpdateError(
            f"checksum mismatch for {release.pyz_name} "
            f"(expected {want[:12]}…, got {got[:12]}…)")
    return data


def atomic_install(data, dest):
    """Write ``data`` to a temp file in ``dest``'s dir, then ``os.replace`` it
    into place — an interrupted update never leaves a half-written payload."""
    d = os.path.dirname(dest) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".cclenzz-", suffix=".pyz")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- Command -----------------------------------------------------------------
def _parse_args(argv):
    """The update sub-flag surface: ``--snapshot`` / ``--stable`` (override the
    recorded channel and rewrite it). Returns the override or ``None``."""
    override = None
    for a in argv:
        if a == "--snapshot":
            override = "snapshot"
        elif a == "--stable":
            override = "stable"
        else:
            raise UpdateError(
                f"unknown option {a!r} — usage: cclenzz update [--snapshot | --stable]")
    return override


def cmd_update(argv, *, home=None, fetcher=None, current_version=None,
               out=None, err=None):
    """Entry point for ``cclenzz update``. Pure-logic seams (``home``,
    ``fetcher``, ``current_version``) default to production values but are
    injected by the unit tests, which never touch the network."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    home = home if home is not None else default_home()
    current_version = current_version if current_version is not None else __version__

    dest = payload_path(home)
    # Nothing to update when there is no installed payload (e.g. a source
    # checkout or the .pyz run directly) — point at the installer instead of
    # inventing a target. Checked before any network I/O so this path is offline.
    if not os.path.exists(dest):
        err.write(
            "cclenzz update: no installed payload at "
            f"{_tilde(dest)} — install with:\n  {INSTALL_ONE_LINER}\n")
        return 1

    try:
        override = _parse_args(argv)
        channel = override or read_channel(home)
        if override:
            try:
                write_channel(home, override)
            except OSError:
                pass  # a read-only channel sidecar must not block the update

        release = resolve_release(fetcher or _HttpFetcher(), channel)
        if release.version == current_version:
            out.write(
                f"cclenzz is already up to date ({current_version}, {channel}).\n")
            return 0

        data = download_payload(fetcher or _HttpFetcher(), release)
        atomic_install(data, dest)
    except UpdateError as e:
        err.write(f"cclenzz update: {e}\n")
        return 1
    except (urllib.error.URLError, OSError) as e:
        err.write(f"cclenzz update: could not reach the release server ({e})\n")
        return 1

    out.write(
        f"cclenzz updated {current_version} → {release.version} "
        f"({channel}).\n")
    return 0


def _tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path
