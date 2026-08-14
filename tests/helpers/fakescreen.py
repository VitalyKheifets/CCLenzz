"""FakeScreen — a headless cell grid implementing the ``Screen`` protocol for
draw tests. Records (char, attr) per cell; ``text()`` returns the rendered
lines with trailing blanks stripped."""


class FakeScreen:
    def __init__(self, h=24, w=80):
        self.h = h
        self.w = w
        self._reset()

    def _reset(self):
        self.grid = [[(" ", 0) for _ in range(self.w)] for _ in range(self.h)]

    def getmaxyx(self):
        return (self.h, self.w)

    def addstr(self, y, x, s, attr):
        if y < 0 or y >= self.h:
            return
        col = x
        for ch in s:
            if col < 0:
                col += 1
                continue
            if col >= self.w:
                break
            self.grid[y][col] = (ch, attr)
            col += 1

    def erase(self):
        self._reset()

    def refresh(self):
        pass

    def text(self):
        return "\n".join(
            "".join(c for c, _ in row).rstrip() for row in self.grid)

    def line(self, y):
        return "".join(c for c, _ in self.grid[y]).rstrip()

    def attr_at(self, y, x):
        return self.grid[y][x][1]
