"""Regression tests for the round of improvements: clamped score, restart-this-
deal, stuck detection, layout overflow handling, and tiny-terminal guard.

Run from the game folder: `python3 test14_improvements.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aisle
import aisle_tui
from aisle import new_solitaire, Card, GAME_ORDER


# -- score is clamped at 0 (no negative scores; AisleRiot fidelity) ----------
g = new_solitaire("klondike", seed=1)
fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
for s in g.slots:
    s.cards = []
g.slots[fids[0]].cards = [Card(1, "C", True)]
g.slots[tids[0]].cards = [Card(2, "H", True)]
g.score = 0
assert g.attempt_move(fids[0], tids[0])      # AC off foundation -> would be -1
assert g.score == 0, f"score went negative: {g.score}"
g.score = 3
g.score -= 10
assert g.score == 0
print("OK score never goes below 0")

# -- restart() replays the exact same deal; new_game varies it ---------------
g = new_solitaire("klondike")            # no fixed seed
def board(gg):
    return [[(c.rank, c.suit, c.face_up) for c in s.cards] for s in gg.slots]
snap = board(g)
seed = g.current_seed
g.deal(); g.deal()
assert board(g) != snap
g.restart()
assert board(g) == snap, "restart did not reproduce the deal"
assert g.current_seed == seed
seeds = set()
for _ in range(6):
    g.new_game(); seeds.add(g.current_seed)
assert len(seeds) >= 2, "consecutive new deals should differ"
print("OK restart() replays the exact hand; new_game() varies it")

# -- has_any_move / is_stuck -------------------------------------------------
for key in GAME_ORDER:
    g = new_solitaire(key, seed=1)
    assert g.has_any_move(), f"{key}: fresh deal reports no moves"
    assert not g.is_stuck()
# contrived stuck board (no stock, no legal move)
g = new_solitaire("bakersdozen", seed=1)
for s in g.slots:
    s.cards = []
for i, t in enumerate(g.ids_of("tableau")):
    g.slots[t].cards = [Card(5, "S", True), Card(13, "SHDC"[i % 4], True)]
assert g.is_stuck(), "contrived dead board not detected as stuck"
# board with an obvious move is not stuck
g.slots[g.ids_of("tableau")[0]].cards = [Card(1, "S", True)]
assert not g.is_stuck()
print("OK has_any_move / is_stuck detect live vs dead boards")


class Grid:
    def __init__(self, h, w):
        self.h, self.w = h, w

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        pass

    def refresh(self):
        pass

    def addnstr(self, *a):
        pass

    def getch(self):
        return -1

    def keypad(self, *a):
        pass


# -- wide waste does not push foundations off-screen / unclickable -----------
g = new_solitaire("fortythieves", seed=1)
w = g.ids_of("waste")[0]
g.slots[w].cards = [Card((i % 13) + 1, "SHDC"[i % 4], True) for i in range(40)]
ui = aisle_tui.BoardUI(Grid(40, 80), g, symbols=False, has_color=False)
ui.draw(None, 1, 0, None, 1.0, "x")
on_screen = {sid for (y, x), (sid, idx) in ui.hit.items() if x < 80}
for f in g.ids_of("foundation"):
    assert f in on_screen, f"foundation {f} pushed off-screen by a long waste"
print("OK long waste keeps all foundations on-screen and clickable")

# -- tall column compresses so the top (playable) card stays clickable -------
g = new_solitaire("spider", seed=1)
col = g.ids_of("tableau")[0]
g.slots[col].cards = [Card((i % 13) + 1, "S", True) for i in range(34)]
ui = aisle_tui.BoardUI(Grid(24, 100), g, symbols=False, has_color=False)
ui.draw(None, 1, col, None, 1.0, "x")
top = len(g.slots[col].cards) - 1
cells = [(y, x) for (y, x), (sid, idx) in ui.hit.items() if sid == col and idx == top]
assert cells, "top card of a tall column is unclickable"
assert all(y < 24 - 3 for (y, x) in cells), "top card collides with the status bar"
print("OK tall column compresses; top card stays clickable above the status bar")

# -- tiny terminal shows a guard instead of crashing -------------------------
ui = aisle_tui.BoardUI(Grid(8, 30), new_solitaire("klondike", seed=1),
                       symbols=False, has_color=False)
ui.draw(None, 1, 0, None, 1.0, "x")     # must not raise
print("OK tiny terminal handled by the minimum-size guard")

# -- dead code removed -------------------------------------------------------
import aisle as _a
assert not hasattr(_a, "follows_up") and not hasattr(_a, "follows_down")
assert not hasattr(_a, "SLOT_KINDS")
print("OK dead helpers removed")

print("\nTEST14 PASS")
