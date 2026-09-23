"""Regression tests for the overlapping card-box rendering (aisle_tui.BoardUI).

Run from the game folder: `python3 test16_cardart.py`.
Cards are drawn as multi-row boxes: the top card of a pile full-size, covered
cards peeking with their rank visible. This checks the look holds up and stays
clickable: top card always reachable, covered cards individually clickable when
there's room, tall piles compress, wide boards auto-fit the card width.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aisle
import aisle_tui
from aisle import new_solitaire, Card, GAME_ORDER


class Scr:
    def __init__(self, h, w):
        self.h, self.w = h, w
        self.g = [[" "] * w for _ in range(h)]

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        self.g = [[" "] * self.w for _ in range(self.h)]

    def refresh(self):
        pass

    def addnstr(self, y, x, text, nmax, attr=0):
        if not (0 <= y < self.h):
            return
        for i, ch in enumerate(text[:nmax]):
            if 0 <= x + i < self.w:
                self.g[y][x + i] = ch

    def getch(self):
        return -1

    def keypad(self, *a):
        pass

    def text(self):
        return "\n".join("".join(r).rstrip() for r in self.g)


def draw(g, h=40, w=120, **kw):
    scr = Scr(h, w)
    ui = aisle_tui.BoardUI(scr, g, symbols=kw.get("symbols", False), has_color=False)
    cur = g.ids_of("tableau")[0] if g.ids_of("tableau") else 0
    ui.draw(None, 1, cur, None, 1.0, "x")
    return ui, scr


# -- 1. every game renders as multi-row card boxes without error -------------
for key in GAME_ORDER:
    g = new_solitaire(key, seed=3)
    ui, scr = draw(g)
    assert "+--" in scr.text(), f"{key}: no card boxes drawn"
print("OK all 9 games render as card boxes")

# -- 2. a covered card shows its rank (peek), top card is full height --------
g = new_solitaire("klondike", seed=1)
tids = g.ids_of("tableau")
for s in g.slots:
    s.cards = []
g.slots[tids[0]].cards = [Card(13, "S", True), Card(12, "H", True),
                          Card(11, "S", True), Card(10, "H", True)]
ui, scr = draw(g)
txt = scr.text()
for label in ("KS", "QH", "JS", "10H"):       # every card's rank is visible
    assert label in txt, f"covered card {label} not visible in the fan"
print("OK covered cards peek with their rank; top card shows full")

# -- 3. all cards in a column are individually clickable when there's room ---
clickable = {idx for (y, x), (sid, idx) in ui.hit.items() if sid == tids[0]}
assert clickable == {0, 1, 2, 3}, f"not all cards clickable: {clickable}"
print("OK every card in a column is individually clickable (roomy screen)")

# -- 4. tall pile compresses; the TOP (playable) card stays on-screen --------
g = new_solitaire("spider", seed=1)
col = g.ids_of("tableau")[0]
g.slots[col].cards = [Card((i % 13) + 1, "S", True) for i in range(34)]
ui, scr = draw(g, h=24, w=110)
top = len(g.slots[col].cards) - 1
top_rows = [y for (y, x), (sid, idx) in ui.hit.items() if sid == col and idx == top]
assert top_rows, "top card of a tall pile is unclickable"
assert max(top_rows) < 24 - 3, "top card collides with the status bar"
print(f"OK 34-card pile on 24 rows: top card stays clickable (row {max(top_rows)})")

# -- 5. wide board (13 cols) auto-fits the card width on an 80-col screen -----
g = new_solitaire("bakersdozen", seed=1)
ui, scr = draw(g, h=40, w=80)
cols = set(g.ids_of("tableau"))
on = {sid for (y, x), (sid, idx) in ui.hit.items() if sid in cols and x < 80}
assert on == cols, f"only {len(on)}/13 columns fit on screen"
assert aisle_tui.MIN_CARD_W <= ui._cw <= aisle_tui.MAX_CARD_W
print(f"OK 13-column board fits on 80 cols (card width auto-set to {ui._cw})")

# -- 6. waste fan: each fanned card is clickable, top card full-width ---------
g = new_solitaire("fortythieves", seed=1)
wst = g.ids_of("waste")[0]
g.slots[wst].cards = [Card((i % 13) + 1, "SHDC"[i % 4], True) for i in range(5)]
ui, scr = draw(g, h=30, w=120)
wc = {idx for (y, x), (sid, idx) in ui.hit.items() if sid == wst}
assert len(wc) == 5, f"waste fan: only {len(wc)}/5 cards clickable"
print("OK right waste fan: all fanned cards clickable, top card full-width")

# -- 7. unicode mode draws rounded borders --------------------------------- -
g = new_solitaire("klondike", seed=1)
ui, scr = draw(g, symbols=True)
assert "┌" in scr.text() and "│" in scr.text(), "unicode card borders missing"
print("OK unicode mode draws box-drawing card borders")

print("\nTEST16 PASS")
