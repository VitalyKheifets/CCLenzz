"""``cclenzz update`` self-update logic (Phase 2).

Everything network-facing runs through an injected ``fetcher`` seam (``.json`` /
``.bytes``), so release resolution, the version-compare short-circuit, checksum
verification, the atomic swap, and channel bookkeeping are all exercised with a
fake — no live network, mirroring the FakeScreen/fake-judge seams elsewhere.
"""

import hashlib
import os

import pytest

from cclenzz import update as U


# --- fake fetcher seam -------------------------------------------------------
class FakeFetcher:
    """Serves canned JSON and bytes keyed by URL; records what was fetched."""

    def __init__(self, json_by_url=None, bytes_by_url=None):
        self.json_by_url = json_by_url or {}
        self.bytes_by_url = bytes_by_url or {}
        self.json_calls = []
        self.bytes_calls = []

    def json(self, url):
        self.json_calls.append(url)
        return self.json_by_url[url]

    def bytes(self, url):
        self.bytes_calls.append(url)
        return self.bytes_by_url[url]


def _release_obj(tag, pyz_name, prerelease=False):
    base = "https://dl.example/%s" % tag
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "assets": [
            {"name": pyz_name, "browser_download_url": f"{base}/{pyz_name}"},
            {"name": "SHA256SUMS", "browser_download_url": f"{base}/SHA256SUMS"},
        ],
    }


# --- channel resolution ------------------------------------------------------
def test_read_channel_defaults_to_stable_when_absent(tmp_path):
    assert U.read_channel(str(tmp_path)) == "stable"


def test_read_channel_reads_recorded_value(tmp_path):
    U.write_channel(str(tmp_path), "snapshot")
    assert U.read_channel(str(tmp_path)) == "snapshot"


def test_read_channel_degrades_on_garbage(tmp_path):
    with open(os.path.join(str(tmp_path), "channel"), "w") as fh:
        fh.write("bleeding-edge\n")   # not a known channel
    assert U.read_channel(str(tmp_path)) == "stable"


def test_write_channel_is_atomic_and_roundtrips(tmp_path):
    U.write_channel(str(tmp_path), "snapshot")
    assert U.read_channel(str(tmp_path)) == "snapshot"
    U.write_channel(str(tmp_path), "stable")
    assert U.read_channel(str(tmp_path)) == "stable"
    # no leftover temp file
    assert sorted(os.listdir(str(tmp_path))) == ["channel"]


# --- release resolution ------------------------------------------------------
def test_resolve_stable_hits_latest_endpoint():
    f = FakeFetcher(json_by_url={
        f"{U.API}/releases/latest": _release_obj("v1.2.3", "cclenzz-1.2.3.pyz")})
    rel = U.resolve_release(f, "stable")
    assert rel.tag == "v1.2.3"
    assert rel.pyz_name == "cclenzz-1.2.3.pyz"
    assert rel.version == "1.2.3"
    assert f.json_calls == [f"{U.API}/releases/latest"]


def test_resolve_snapshot_picks_first_prerelease():
    f = FakeFetcher(json_by_url={f"{U.API}/releases": [
        _release_obj("v1.0.0", "cclenzz-1.0.0.pyz", prerelease=False),
        _release_obj("snapshot-20260815-abc1234",
                     "cclenzz-1.0.0-dev+abc1234.pyz", prerelease=True),
        _release_obj("snapshot-20260101-old0000",
                     "cclenzz-0.9.0-dev+old0000.pyz", prerelease=True),
    ]})
    rel = U.resolve_release(f, "snapshot")
    assert rel.tag == "snapshot-20260815-abc1234"
    assert rel.version == "1.0.0-dev+abc1234"


def test_resolve_snapshot_none_published_raises():
    f = FakeFetcher(json_by_url={f"{U.API}/releases": [
        _release_obj("v1.0.0", "cclenzz-1.0.0.pyz", prerelease=False)]})
    with pytest.raises(U.UpdateError, match="no snapshot"):
        U.resolve_release(f, "snapshot")


def test_resolve_missing_assets_raises():
    bad = {"tag_name": "v1.0.0", "prerelease": False,
           "assets": [{"name": "notes.txt", "browser_download_url": "x"}]}
    f = FakeFetcher(json_by_url={f"{U.API}/releases/latest": bad})
    with pytest.raises(U.UpdateError, match="missing"):
        U.resolve_release(f, "stable")


# --- checksums ---------------------------------------------------------------
def test_expected_sha_parses_two_space_format():
    body = "deadbeef  cclenzz-1.0.0.pyz\n"
    assert U.expected_sha(body, "cclenzz-1.0.0.pyz") == "deadbeef"


def test_expected_sha_matches_by_basename_and_skips_others():
    body = ("aaaa  some/other-1.0.0.pyz\n"
            "BBBB  ./cclenzz-1.0.0.pyz\n")
    assert U.expected_sha(body, "cclenzz-1.0.0.pyz") == "bbbb"


def test_expected_sha_missing_entry_raises():
    with pytest.raises(U.UpdateError, match="no entry"):
        U.expected_sha("aaaa  other.pyz\n", "cclenzz-1.0.0.pyz")


def test_download_payload_verifies_and_rejects_tamper():
    data = b"payload-bytes"
    digest = hashlib.sha256(data).hexdigest()
    rel = U.Release("v1.0.0", "cclenzz-1.0.0.pyz",
                    "https://dl/pyz", "https://dl/sums")
    good = FakeFetcher(bytes_by_url={
        "https://dl/pyz": data,
        "https://dl/sums": f"{digest}  cclenzz-1.0.0.pyz\n".encode()})
    assert U.download_payload(good, rel) == data

    bad = FakeFetcher(bytes_by_url={
        "https://dl/pyz": data,
        "https://dl/sums": b"0" * 64 + b"  cclenzz-1.0.0.pyz\n"})
    with pytest.raises(U.UpdateError, match="checksum mismatch"):
        U.download_payload(bad, rel)


# --- atomic install ----------------------------------------------------------
def test_atomic_install_replaces_in_place(tmp_path):
    dest = os.path.join(str(tmp_path), "cclenzz.pyz")
    with open(dest, "wb") as fh:
        fh.write(b"old")
    U.atomic_install(b"new-payload", dest)
    with open(dest, "rb") as fh:
        assert fh.read() == b"new-payload"
    # temp file cleaned up — only the payload remains
    assert os.listdir(str(tmp_path)) == ["cclenzz.pyz"]


# --- cmd_update end to end (through the seam) --------------------------------
class _Buf:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s


def _installed_home(tmp_path, version_of_payload=b"OLD"):
    home = str(tmp_path)
    with open(U.payload_path(home), "wb") as fh:
        fh.write(version_of_payload)
    return home


def test_update_no_payload_prints_install_one_liner(tmp_path):
    out, err = _Buf(), _Buf()
    rc = U.cmd_update([], home=str(tmp_path), fetcher=FakeFetcher(),
                      current_version="1.0.0", out=out, err=err)
    assert rc == 1
    assert "no installed payload" in err.text
    assert "install.sh | bash" in err.text


def test_update_already_current_short_circuits(tmp_path):
    home = _installed_home(tmp_path)
    f = FakeFetcher(json_by_url={
        f"{U.API}/releases/latest": _release_obj("v1.0.0", "cclenzz-1.0.0.pyz")})
    out, err = _Buf(), _Buf()
    rc = U.cmd_update([], home=home, fetcher=f, current_version="1.0.0",
                      out=out, err=err)
    assert rc == 0
    assert "already up to date" in out.text
    # payload untouched, no download attempted
    assert f.bytes_calls == []
    with open(U.payload_path(home), "rb") as fh:
        assert fh.read() == b"OLD"


def test_update_downloads_and_swaps_payload(tmp_path):
    home = _installed_home(tmp_path)
    new = b"NEW-PYZ-BYTES"
    digest = hashlib.sha256(new).hexdigest()
    f = FakeFetcher(
        json_by_url={f"{U.API}/releases/latest":
                     _release_obj("v1.1.0", "cclenzz-1.1.0.pyz")},
        bytes_by_url={
            "https://dl.example/v1.1.0/cclenzz-1.1.0.pyz": new,
            "https://dl.example/v1.1.0/SHA256SUMS":
                f"{digest}  cclenzz-1.1.0.pyz\n".encode()})
    out, err = _Buf(), _Buf()
    rc = U.cmd_update([], home=home, fetcher=f, current_version="1.0.0",
                      out=out, err=err)
    assert rc == 0
    assert "1.0.0 → 1.1.0" in out.text
    with open(U.payload_path(home), "rb") as fh:
        assert fh.read() == new


def test_update_snapshot_flag_records_channel(tmp_path):
    home = _installed_home(tmp_path)
    new = b"SNAP"
    digest = hashlib.sha256(new).hexdigest()
    f = FakeFetcher(
        json_by_url={f"{U.API}/releases": [
            _release_obj("snapshot-20260815-abc1234",
                         "cclenzz-1.1.0-dev+abc1234.pyz", prerelease=True)]},
        bytes_by_url={
            "https://dl.example/snapshot-20260815-abc1234/"
            "cclenzz-1.1.0-dev+abc1234.pyz": new,
            "https://dl.example/snapshot-20260815-abc1234/SHA256SUMS":
                f"{digest}  cclenzz-1.1.0-dev+abc1234.pyz\n".encode()})
    out, err = _Buf(), _Buf()
    rc = U.cmd_update(["--snapshot"], home=home, fetcher=f,
                      current_version="1.0.0", out=out, err=err)
    assert rc == 0
    # the override was persisted so later plain `update` follows snapshot
    assert U.read_channel(home) == "snapshot"


def test_update_unknown_flag_errors(tmp_path):
    home = _installed_home(tmp_path)
    out, err = _Buf(), _Buf()
    rc = U.cmd_update(["--bogus"], home=home, fetcher=FakeFetcher(),
                      current_version="1.0.0", out=out, err=err)
    assert rc == 1
    assert "unknown option" in err.text


def test_update_network_failure_is_clean_exit_1(tmp_path):
    home = _installed_home(tmp_path)

    class Boom:
        def json(self, url):
            import urllib.error
            raise urllib.error.URLError("name resolution failed")

        def bytes(self, url):
            raise AssertionError("should not reach download")

    out, err = _Buf(), _Buf()
    rc = U.cmd_update([], home=home, fetcher=Boom(), current_version="1.0.0",
                      out=out, err=err)
    assert rc == 1
    assert "could not reach" in err.text
    assert "Traceback" not in err.text
