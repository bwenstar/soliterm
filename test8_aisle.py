"""Regression tests for the AisleRiot CLI engine (aisle.py) and all 9 games.

Run from the game folder: `python3 test8_aisle.py`.
Covers deal integrity, card conservation under random play, win detection,
undo/redo correctness (including the autoplay-as-one-step and failed-click
redo-preservation fixes), and the Canfield reserve face-up invariant.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aisle
from aisle import GAME_ORDER, new_solitaire, Card

EXPECTED = {"klondike": 52, "spider": 104, "freecell": 52, "eightoff": 52,
            "golf": 52, "yukon": 52, "bakersdozen": 52, "fortythieves": 104,
            "canfield": 52}


def count(g):
    return sum(len(s.cards) for s in g.slots)


def multiset(g):
    out = []
    for s in g.slots:
        out += [(c.rank, c.suit) for c in s.cards]
    return out


# -- deal integrity ----------------------------------------------------------
for key in GAME_ORDER:
    for seed in range(5):
        g = new_solitaire(key, seed=seed)
        assert count(g) == EXPECTED[key], f"{key}/{seed}: {count(g)}"
        assert not g.is_won(), f"{key}: fresh deal reports won"
print("OK deal integrity + no false win (9 games x 5 seeds)")

# -- random-play stress: no crash, no card leak, undo/redo safe --------------
bugs = []
for key in GAME_ORDER:
    for seed in range(15):
        rng = random.Random(seed * 977 + 5)
        g = new_solitaire(key, seed=seed)
        ns = len(g.slots)
        exp = EXPECTED[key]
        for op in range(200):
            r = rng.random()
            if r < 0.16 and g.can_deal():
                g.deal()
            elif r < 0.28:
                g.autoplay()
            elif r < 0.38:
                g.undo()
            elif r < 0.45:
                g.redo()
            elif r < 0.54:
                g.double_click(rng.randrange(ns))
            elif r < 0.61:
                g.click(rng.randrange(ns))
            else:
                g.attempt_move(rng.randrange(ns), rng.randrange(ns),
                               rng.choice([None, 1, 2, 3, 5, 13]))
            if count(g) != exp or len(multiset(g)) != exp:
                bugs.append(f"{key}/{seed} op{op}: count {count(g)}")
                break
assert not bugs, bugs[:5]
print("OK random-play stress: no crash, no leak (9 games x 15 seeds x 200 ops)")

# -- undo-all returns to the initial deal (autoplay is one undoable step) -----
for key in GAME_ORDER:
    g = new_solitaire(key, seed=11)
    initial = g.serialize()
    for _ in range(8):
        if g.can_deal():
            g.deal()
        else:
            g.autoplay()
    while g.can_undo():
        g.undo()
    assert g.serialize() == initial, f"{key}: undo-all mismatch"
print("OK undo-all returns every game to its initial deal")

# -- failed click/double_click preserves the redo stack ----------------------
g = new_solitaire("klondike", seed=42)
g.deal(); g.undo()
assert g.can_redo()
assert g.click(g.ids_of("foundation")[0]) is False
assert g.double_click(g.ids_of("foundation")[0]) is False
assert g.can_redo(), "failed click/dclick destroyed the redo stack"
assert g.redo()
print("OK failed click/double_click preserves redo")

# -- no-op autoplay leaves the undo stack unchanged --------------------------
g = new_solitaire("klondike", seed=1)
for s in g.slots:
    if s.kind in ("tableau", "waste"):
        s.cards = []
before = len(g._undo)
assert g.autoplay() == 0 and len(g._undo) == before
print("OK no-op autoplay leaves the undo stack unchanged")

# -- Canfield reserve top stays face-up through every removal path -----------
def reserve_ok(action):
    g = new_solitaire("canfield", seed=7)
    res = g.ids_of("reserve")[0]
    g.slots[res].cards[-1] = Card(g.base_val, "C", True)
    action(g, res)
    top = g.top(res)
    return top is None or top.face_up

assert reserve_ok(lambda g, r: g.double_click(r))
assert reserve_ok(lambda g, r: g.autoplay())
def _refill_path(g, r):
    t = g.ids_of("tableau")[0]
    g.slots[t].cards = []
    g.gamedef._refill(g)
assert reserve_ok(_refill_path)
print("OK Canfield reserve top stays face-up after every removal")

# -- win detection per representative game -----------------------------------
g = new_solitaire("klondike", seed=1)
fids = g.ids_of("foundation"); tids = g.ids_of("tableau")
for s in g.slots:
    s.cards = []
for i, suit in enumerate("SHDC"):
    g.slots[fids[i]].cards = [Card(r, suit, True) for r in range(1, 13)]
for i, suit in enumerate("SHDC"):
    g.slots[tids[i]].cards = [Card(13, suit, True)]
assert g.autoplay() == 4 and g.is_won()

g = new_solitaire("spider", seed=0)
fids = g.ids_of("foundation")
for s in g.slots:
    s.cards = []
for f in fids:
    g.slots[f].cards = [Card(r, "S", True) for r in range(13, 0, -1)]
g.gamedef.post_move(g)
assert g.is_won() and g.score == 96
print("OK win detection (Klondike autoplay finish, Spider 8 suits -> 96)")

print("\nTEST8 PASS")
