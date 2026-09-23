"""Regression tests for code-skin play mode (aisle_tui.BoardUI + aisle_camo).

Run from the game folder: `python3 test11_codeskin.py`.
Verifies the board stays fully playable while wrapped in a code-editor frame:
positions shift into the file, the hit map stays valid and clears the gutter,
and the surrounding source renders for every game without exceptions.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aisle
import aisle_tui
import aisle_camo
from aisle import GAME_ORDER, new_solitaire


class FakeScr:
    def __init__(self, h=40, w=140):
        self.h, self.w = h, w
        self.grid = [[" "] * w for _ in range(h)]

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        self.grid = [[" "] * self.w for _ in range(self.h)]

    def refresh(self):
        pass

    def addnstr(self, y, x, text, nmax, attr=0):
        if not (0 <= y < self.h):
            return
        for i, ch in enumerate(text[:nmax]):
            if 0 <= x + i < self.w:
                self.grid[y][x + i] = ch

    def getch(self):
        return -1

    def keypad(self, *a):
        pass

    def render(self):
        return "\n".join("".join(r).rstrip() for r in self.grid)


# -- code_lines is deterministic and looks like source ----------------------
a = aisle_camo.code_lines(120, seed=1)
b = aisle_camo.code_lines(120, seed=1)
assert a == b and len(a) == 120, "code_lines not deterministic / wrong length"
joined = "\n".join(a)
assert "def " in joined and "import" in joined, "code_lines doesn't read as source"
print("OK code_lines: deterministic, 120 lines, reads as source")

# -- every game renders in code-skin mode without error; hit map stays valid -
for key in GAME_ORDER:
    g = new_solitaire(key, seed=3)
    scr = FakeScr()
    ui = aisle_tui.BoardUI(scr, g, symbols=False, has_color=False)
    ui.code_skin = True
    cursor = g.ids_of("tableau")[0] if g.ids_of("tableau") else 0
    ui.draw(None, 1, cursor, g.hint(), 12.0, "playing")
    assert ui.hit, f"{key}: empty hit map in code skin"
    minx = min(x for (_, x) in ui.hit)
    assert minx >= ui._gutter, f"{key}: board overlaps the line-number gutter"
    for (y, x), (sid, idx) in ui.hit.items():
        assert 0 <= sid < len(g.slots), f"{key}: hit map points at bad slot {sid}"
print("OK code-skin renders for all 9 games; hit map valid, clears the gutter")

# -- the skinned screen actually contains code framing ----------------------
g = new_solitaire("klondike", seed=5)
g.deal()
scr = FakeScr(44, 100)          # roomy enough for source above AND below the board
ui = aisle_tui.BoardUI(scr, g, symbols=False, has_color=False)
ui.code_skin = True
ui.draw(None, 1, g.ids_of("tableau")[0], None, 9.0, "your move")
screen = scr.render()
assert "solver.py" in screen, "no editor header"
assert "def " in screen, "no source lines around the board"
assert "  1  " in screen, "no line-number gutter"
assert "board snapshot" in screen, "no embedded-snapshot marker"
# the board is drawn as ASCII card boxes ('+----+') in --ascii / no-symbol mode
assert "+--" in screen, "card boxes missing from the skinned screen"
print("OK skinned screen shows editor header, gutter, source, and the board")

# -- toggling the skin shifts the board and back (still playable) ------------
g = new_solitaire("klondike", seed=1)
ui = aisle_tui.BoardUI(FakeScr(), g, symbols=False, has_color=False)
ui.code_skin = False
off = ui.compute_positions()
ui.code_skin = True
on = ui.compute_positions()
sid = next(iter(on))
assert on[sid][1] > off[sid][1], "skinned board should be indented further right"
assert on[sid][0] >= off[sid][0], "skinned board should sit no higher in the file"
print("OK toggling code skin shifts the board into the file and back")

print("\nTEST11 PASS")
