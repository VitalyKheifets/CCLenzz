"""Temp-HOME sandbox builder (§10.1). Redirects both the config path and the
state root into a temp dir by setting HOME (an OS convention, not a cclenzz
knob), so the developer's real ~/.claude and ~/.cclenzz are never touched."""

import hashlib
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
LAUNCHER = os.path.join(REPO, "cclenzz")


class Sandbox:
    def __init__(self, tmp_path, slug="-home-u-proj", claude_stub="fake_claude_ok",
                 interval=0.05, color="never", extra_config=""):
        self.tmp = str(tmp_path)
        self.home = os.path.join(self.tmp, "home")
        self.bindir = os.path.join(self.tmp, "bin")
        self.slug = slug
        self.projects_dir = os.path.join(self.home, ".claude", "projects", slug)
        self.state_dir = os.path.join(self.home, ".cclenzz")
        os.makedirs(self.projects_dir, exist_ok=True)
        os.makedirs(self.bindir, exist_ok=True)
        os.makedirs(self.state_dir, exist_ok=True)
        self.claude_bin = os.path.join(self.bindir, "fake_claude")
        if claude_stub:
            shutil.copy(os.path.join(FIXTURES, "bin", claude_stub), self.claude_bin)
            os.chmod(self.claude_bin, 0o755)
        self.capture = os.path.join(self.tmp, "claude_capture.json")
        glob = os.path.join(self.home, ".claude", "projects", "*", "*.jsonl")
        cfg = (f'theme = "dark"\nicons = "unicode"\ncolor = "{color}"\n'
               f'auto_audit = false\ninterval = {interval}\n'
               f'projects_glob = "{glob}"\nclaude_bin = "{self.claude_bin}"\n'
               + extra_config)
        with open(os.path.join(self.state_dir, "config.toml"), "w") as fh:
            fh.write(cfg)

    def add_session(self, fixture_name, session_id="aaaa1111"):
        src = os.path.join(FIXTURES, "sessions", fixture_name)
        dst = os.path.join(self.projects_dir, f"{session_id}.jsonl")
        shutil.copy(src, dst)
        return dst

    def write_session(self, session_id, text):
        dst = os.path.join(self.projects_dir, f"{session_id}.jsonl")
        with open(dst, "w") as fh:
            fh.write(text)
        return dst

    def env(self):
        e = dict(os.environ)
        e["HOME"] = self.home
        e["TERM"] = "xterm-256color"
        e.pop("NO_COLOR", None)
        e["LANG"] = "en_US.UTF-8"
        e["PATH"] = self.bindir + os.pathsep + e.get("PATH", "")
        e["FAKE_CLAUDE_CAPTURE"] = self.capture
        return e

    def run_cli(self, *args, input=None, timeout=30):
        return subprocess.run(
            [sys.executable, LAUNCHER, *args],
            env=self.env(), capture_output=True, text=True,
            input=input, timeout=timeout)

    # --- read-only invariant guard over the fake ~/.claude tree ---
    def claude_hash(self):
        root = os.path.join(self.home, ".claude")
        h = hashlib.sha256()
        for dirpath, dirnames, filenames in sorted(os.walk(root)):
            dirnames.sort()
            for name in sorted(filenames):
                p = os.path.join(dirpath, name)
                h.update(os.path.relpath(p, root).encode())
                with open(p, "rb") as fh:
                    h.update(fh.read())
        return h.hexdigest()
