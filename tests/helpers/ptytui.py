"""A pty driver for real-TUI smoke tests. Uses a small built-in cursor-tracking
screen model (no third-party terminal emulator) so assertions see the terminal's
actual on-screen layout, not the raw byte order — curses cell-diffing otherwise
splits words across cursor moves. Assertions remain substring-level."""

import os
import pty
import re
import select
import struct
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAUNCHER = os.path.join(REPO, "cclenzz")


class _Screen:
    """Minimal VT: CUP/CUU-D/ED/EL, CR/LF/BS, ignoring SGR/OSC/charset."""

    def __init__(self, h, w):
        self.h = h
        self.w = w
        self.grid = [[" "] * w for _ in range(h)]
        self.row = 0
        self.col = 0

    def _put(self, ch):
        if self.col >= self.w:
            self.col = self.w - 1
        if 0 <= self.row < self.h and 0 <= self.col < self.w:
            self.grid[self.row][self.col] = ch
        self.col += 1

    def feed(self, data):
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1b:  # ESC
                if i + 1 < n and data[i + 1] == ord('['):
                    m = re.match(rb'\x1b\[([0-9;?]*)([A-Za-z])', data[i:])
                    if m:
                        self._csi(m.group(1), m.group(2))
                        i += m.end()
                        continue
                    i += 2
                    continue
                if i + 1 < n and data[i + 1] == ord(']'):  # OSC ... BEL/ST
                    m = re.match(rb'\x1b\][^\x07\x1b]*(\x07|\x1b\\)', data[i:])
                    i += m.end() if m else 2
                    continue
                if i + 1 < n and data[i + 1] in (ord('('), ord(')')):
                    i += 3
                    continue
                i += 1
                continue
            if b == ord('\r'):
                self.col = 0
                i += 1
                continue
            if b == ord('\n'):
                self.row = min(self.h - 1, self.row + 1)
                i += 1
                continue
            if b == 0x08:  # backspace
                self.col = max(0, self.col - 1)
                i += 1
                continue
            if b in (0x0e, 0x0f, 0x07):  # SI/SO/BEL
                i += 1
                continue
            # decode one UTF-8 char
            j = i + 1
            while j < n and (data[j] & 0xC0) == 0x80:
                j += 1
            try:
                ch = data[i:j].decode("utf-8")
            except UnicodeDecodeError:
                ch = "?"
            if ch and ord(ch[0]) >= 0x20:
                self._put(ch)
            i = j

    def _csi(self, params, final):
        f = chr(final[0])
        p = params.decode()
        nums = [int(x) for x in p.split(";") if x.isdigit()]
        if f == "H":
            self.row = (nums[0] - 1) if len(nums) >= 1 else 0
            self.col = (nums[1] - 1) if len(nums) >= 2 else 0
            self.row = max(0, min(self.h - 1, self.row))
            self.col = max(0, min(self.w - 1, self.col))
        elif f in "ABCD":
            k = nums[0] if nums else 1
            if f == "A":
                self.row = max(0, self.row - k)
            elif f == "B":
                self.row = min(self.h - 1, self.row + k)
            elif f == "C":
                self.col = min(self.w - 1, self.col + k)
            elif f == "D":
                self.col = max(0, self.col - k)
        elif f == "J":
            mode = nums[0] if nums else 0
            if mode == 2:
                self.grid = [[" "] * self.w for _ in range(self.h)]
            elif mode == 0:
                for c in range(self.col, self.w):
                    self.grid[self.row][c] = " "
                for r in range(self.row + 1, self.h):
                    self.grid[r] = [" "] * self.w
        elif f == "K":
            mode = nums[0] if nums else 0
            if mode == 0:
                for c in range(self.col, self.w):
                    self.grid[self.row][c] = " "
            elif mode == 1:
                for c in range(0, self.col + 1):
                    self.grid[self.row][c] = " "
            elif mode == 2:
                self.grid[self.row] = [" "] * self.w
        # SGR (m) and everything else: ignore

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)


class PtySession:
    def __init__(self, env, args=(), cols=120, rows=40, python=None):
        self.env = env
        self.cols = cols
        self.rows = rows
        self.buf = b""
        python = python or sys.executable
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            try:
                import fcntl
                import termios
                fcntl.ioctl(1, termios.TIOCSWINSZ,
                            struct.pack("HHHH", rows, cols, 0, 0))
            except Exception:
                pass
            os.execvpe(python, [python, LAUNCHER, *args], env)

    def _poll(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            try:
                data = os.read(self.fd, 65536)
                if data:
                    self.buf += data
                    return True
            except OSError:
                pass
        return False

    def read_until(self, pattern, timeout=5.0):
        deadline = time.time() + timeout
        while True:
            if pattern in self.screen_text():
                return True
            if time.time() >= deadline:
                return pattern in self.screen_text()
            self._poll(0.1)

    def send(self, keys):
        if isinstance(keys, str):
            keys = keys.encode()
        os.write(self.fd, keys)

    def resize(self, cols, rows):
        try:
            import fcntl
            import termios
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:
            pass

    def screen_text(self):
        scr = _Screen(self.rows, self.cols)
        scr.feed(self.buf)
        return scr.text()

    def wait(self, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._poll(0.1)
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
            except OSError:
                return None
            if pid == self.pid:
                return os.waitstatus_to_exitcode(status)
        return None

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except OSError:
            pass
