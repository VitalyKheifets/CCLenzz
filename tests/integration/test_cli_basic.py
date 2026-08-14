"""Sandboxed real-CLI behavior + exit codes (§11.9). The version-gate test runs
the real shim under a pre-3.11 interpreter when one is available."""

import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAUNCHER = os.path.join(REPO, "cclenzz")


def test_version(sandbox):
    sb = sandbox()
    r = sb.run_cli("--version")
    assert r.returncode == 0
    assert r.stdout.strip() == "cclenzz 1.0.0"


def test_help_exit_1(sandbox):
    sb = sandbox()
    r = sb.run_cli("-h")
    # argparse prints help to stdout, then the blanket SystemExit→1 quirk (§6.2)
    assert r.returncode == 1
    assert "usage: cclenzz" in r.stdout


def test_unknown_command(sandbox):
    sb = sandbox()
    r = sb.run_cli("bogus")
    assert r.returncode == 1
    assert "unknown command 'bogus'" in r.stderr
    assert "usage: cclenzz [setup | doctor | update] [--version]" in r.stderr


def test_doctor_no_config_exit_0(sandbox):
    sb = sandbox()
    os.remove(os.path.join(sb.state_dir, "config.toml"))
    r = sb.run_cli("doctor")
    assert r.returncode == 0
    assert "not present — run cclenzz setup" in r.stdout


def test_malformed_toml_exit_1(sandbox):
    sb = sandbox()
    with open(os.path.join(sb.state_dir, "config.toml"), "w") as fh:
        fh.write('theme = "dark\n')
    r = sb.run_cli("doctor")
    assert r.returncode == 1
    assert "bad config at" in r.stderr


def test_tui_no_config_non_interactive_exit_2(sandbox):
    sb = sandbox()
    os.remove(os.path.join(sb.state_dir, "config.toml"))
    r = sb.run_cli(input="")
    assert r.returncode == 2
    assert "no config found" in r.stderr


def test_tui_with_config_non_interactive_exit_2(sandbox):
    sb = sandbox()
    r = sb.run_cli(input="")
    assert r.returncode == 2
    assert "interactive terminal required" in r.stderr


def test_update_no_payload_prints_install_one_liner(sandbox):
    # The sandbox HOME has ~/.cclenzz but no installed cclenzz.pyz payload, so
    # `cclenzz update` short-circuits offline (before any network) with the
    # install one-liner and exit 1 — exercising the cli.py dispatch end to end.
    sb = sandbox()
    r = sb.run_cli("update")
    assert r.returncode == 1
    assert "no installed payload" in r.stderr
    assert "install.sh | bash" in r.stderr
    assert "Traceback" not in r.stderr


def test_update_unknown_flag_exit_1(sandbox):
    sb = sandbox()
    # Force the flag parse to run by placing a dummy payload so the no-payload
    # short-circuit doesn't fire first.
    open(os.path.join(sb.state_dir, "cclenzz.pyz"), "wb").close()
    r = sb.run_cli("update", "--bogus")
    assert r.returncode == 1
    assert "unknown option" in r.stderr


def test_unknown_config_key_warns_doctor_ok(sandbox):
    sb = sandbox(extra_config="bogus_key = 1\n")
    r = sb.run_cli("doctor")
    assert r.returncode == 0
    assert "unknown config key 'bogus_key'" in r.stderr


def _old_python():
    for name in ("python3.10", "python3.9", "python3.8", "python3"):
        p = shutil.which(name)
        if not p:
            continue
        try:
            out = subprocess.run([p, "-c", "import sys;print(sys.version_info[:2])"],
                                 capture_output=True, text=True, timeout=10)
            major, minor = eval(out.stdout.strip())
            if (major, minor) < (3, 11):
                return p
        except Exception:
            continue
    return None


def test_version_gate_pre_311():
    old = _old_python()
    if not old:
        pytest.skip("no pre-3.11 interpreter available")
    r = subprocess.run([old, LAUNCHER, "--version"], capture_output=True, text=True)
    assert r.returncode == 1
    assert r.stderr.strip() == "cclenzz: Python >= 3.11 required (for tomllib)"
    assert "Traceback" not in r.stderr and "Traceback" not in r.stdout
