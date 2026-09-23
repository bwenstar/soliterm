"""Regression tests for the progress-based, loop-free hint (aisle.Solitaire).

Run from the game folder: `python3 test15_hint.py`.
The hint must (1) never suggest a reversible/no-progress shuffle, (2) suggest
productive moves (uncovering, foundation plays), and (3) be provably loop-free:
every best_move() strictly increases a bounded progress metric and never
revisits a board state.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aisle
from aisle import new_solitaire, Card, GAME_ORDER


def empty(g):
    for s in g.slots:
        s.cards = []


# -- 1. a board whose only move is a pointless shuffle yields no move-hint ----
g = new_solitaire("klondike", seed=1)
tids = g.ids_of("tableau")
empty(g)
g.slots[tids[0]].cards = [Card(8, "H", True), Card(7, "S", True)]  # 7S valid on 8H
g.slots[tids[1]].cards = [Card(8, "D", True)]                      # 7S->8D also valid (pointless)
assert g.best_move() is None, f"hint suggested a pointless shuffle: {g.best_move()}"
assert g.hint() is None, "hint should be None when only shuffles remain (no stock)"
print("OK hint refuses a reversible 7S 8H<->8D shuffle")

# -- 2. hint suggests a move that uncovers a face-down card ------------------
g = new_solitaire("klondike", seed=1)
empty(g)
g.slots[tids[0]].cards = [Card(9, "C", False), Card(6, "S", True)]
g.slots[tids[1]].cards = [Card(7, "H", True)]
mv = g.best_move()
assert mv is not None and mv[0] == tids[0] and mv[1] == tids[1], mv
print("OK hint suggests the uncovering move 6S -> 7H")

# -- 2b. hint suggests a genuine BUILD instead of conservatively dealing -----
# (the key improvement: a build that starts a sequence makes progress now)
g = new_solitaire("klondike", seed=1)
empty(g)
g.slots[tids[0]].cards = [Card(6, "S", True)]          # lone 6S, nothing under it
g.slots[tids[1]].cards = [Card(7, "H", True)]          # 6S builds onto 7H
g.slots[g.ids_of("stock")[0]].cards = [Card(9, "C", False)] * 5   # deal is available
mv = g.best_move()
assert mv is not None and mv[0] == tids[0] and mv[1] == tids[1], \
    f"expected the build 6S->7H, got {mv}"
print("OK hint suggests a real tableau build instead of telling you to deal")

# -- 2c. a lone King to an empty column is NOT suggested (AisleRiot's guard) --
g = new_solitaire("klondike", seed=1)
empty(g)
g.slots[tids[0]].cards = [Card(13, "S", True)]
g.slots[tids[1]].cards = []
assert g.best_move() is None, f"lone-King shuffle suggested: {g.best_move()}"
print("OK lone King -> empty column is not suggested (no progress)")

# -- 3. hint prefers a foundation play ---------------------------------------
g = new_solitaire("klondike", seed=1)
empty(g)
g.slots[tids[0]].cards = [Card(5, "H", True), Card(1, "S", True)]
mv = g.best_move()
assert mv is not None and g.kind(mv[1]) == "foundation", mv
print("OK hint suggests the Ace-to-foundation play")

# -- 4. the loop-free guarantee for every game -------------------------------
for key in GAME_ORDER:
    g = new_solitaire(key, seed=7)
    seen = set()
    deals = moves = 0
    for _ in range(900):
        mv = g.best_move()
        if mv is None:
            if g.deal_is_productive() and deals < 80:
                g.deal(); deals += 1; continue
            break
        src, dst, n = mv
        p0 = g.progress()
        st = g.serialize()
        assert st not in seen, f"{key}: best_move revisited a state (LOOP)"
        seen.add(st)
        assert g.attempt_move(src, dst, n), f"{key}: best_move illegal {mv}"
        assert g.progress() > p0, f"{key}: best_move did not progress"
        moves += 1
assert True
print("OK every best_move strictly progresses & never revisits (all 9 games)")

# -- 5. best_move returns a legal, exact move (with its pickup size) ----------
for key in GAME_ORDER:
    for sd in range(4):
        g = new_solitaire(key, seed=sd)
        mv = g.best_move()
        if mv is None:
            continue
        src, dst, n = mv
        sim = g.clone()
        assert sim.attempt_move(src, dst, n), f"{key}/{sd}: {mv} not legal"
print("OK best_move's (src,dst,n) is always a legal move")

print("\nTEST15 PASS")
