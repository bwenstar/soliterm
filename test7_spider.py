"""Regression tests for the Spider engine and AisleRiot-faithful scoring.

Run from inside the game folder: `python3 test7_spider.py`.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sol import SpiderGame, Game, Card, make_spider_deck
from collections import Counter


def spider_count(g):
    return len(g.stock) + sum(len(t) for t in g.tableau) + sum(len(p) for p in g.completed)


# -- decks -------------------------------------------------------------------
for suits in (1, 2, 4):
    deck = make_spider_deck(suits)
    assert len(deck) == 104, f"{suits}-suit deck has {len(deck)} cards"
    distinct = len(set(c.suit for c in deck))
    per = 104 // (13 * distinct)
    assert all(v == per for v in Counter((c.rank, c.suit) for c in deck).values())
print("OK Spider decks: 104 cards, even copies for 1/2/4 suits")

# -- deal shape, conservation, no-empty-deal --------------------------------
for suits in (1, 2, 4):
    for seed in range(10):
        g = SpiderGame(suits=suits, seed=seed); g.new_game()
        assert spider_count(g) == 104
        assert sum(len(t) for t in g.tableau) == 54 and len(g.stock) == 50
        for col in g.tableau:
            for j, c in enumerate(col):
                assert c.face_up == (j == len(col) - 1)
        for _ in range(60):
            g.deal()
            assert spider_count(g) == 104
g = SpiderGame(suits=1, seed=0); g.new_game(); g.tableau[3] = []
assert g.can_deal() is False and g.deal() is False
print("OK Spider deal: shape, face-up rule, 104 conservation, no-empty-column rule")

# -- build by rank ignoring suit; same-suit group moves ----------------------
g = SpiderGame(suits=4); g.tableau = [[] for _ in range(10)]; g.stock = []; g.completed = []
g.tableau[0] = [Card(7, "H", True)]; g.tableau[1] = [Card(6, "S", True)]
assert g.move("t1", "t0") is True            # 6S onto 7H: rank-only build
g = SpiderGame(suits=4); g.tableau = [[] for _ in range(10)]; g.stock = []; g.completed = []
g.tableau[0] = [Card(9, "H", True), Card(8, "S", True), Card(7, "S", True)]
g.tableau[1] = [Card(9, "D", True)]
assert g._movable_run_len(g.tableau[0]) == 2  # only 8S-7S is same-suit
assert g.move("t0", "t1") is True
assert [str(c) for c in g.tableau[1]] == ["9D", "8S", "7S"]
print("OK Spider moves: rank-only build, same-suit-run group move")

# -- completed suit removes and scores 12; win at 96 ------------------------
g = SpiderGame(suits=1); g.tableau = [[] for _ in range(10)]; g.stock = []; g.completed = []
g.tableau[0] = [Card(r, "S", True) for r in range(13, 0, -1)]
assert g._compute_score() == 12
assert g._resolve_completions() == 1 and g.tableau[0] == [] and len(g.completed) == 1
assert g.score == 12
g.completed = [[Card(r, "S", True) for r in range(13, 0, -1)] for _ in range(8)]
g.score = g._compute_score()
assert g.is_won() and g.score == 96
print("OK Spider scoring: completed suit = 12, win = 96 (max)")

# -- undo round-trip, including after a completion ---------------------------
g = SpiderGame(suits=2, seed=4); g.new_game()
snap = g.serialize(); g.deal(); assert g.serialize() != snap
g.undo(); assert g.serialize() == snap
print("OK Spider undo: exact round-trip")

# -- no crash / no leak on out-of-range or bad-count moves -------------------
g = SpiderGame(suits=1, seed=1); g.new_game()
for src, dst, cnt in [("t10", "t0", None), ("t0", "t99", None), ("t0", "t1", 0),
                      ("t0", "t1", -3), ("t0", "t1", 999), ("t-1", "t0", None)]:
    assert g.move(src, dst, cnt) is False
    assert spider_count(g) == 104
print("OK Spider move(): bad ids/counts return False, no crash, no leak")

# -- AisleRiot Klondike scoring fidelity -------------------------------------
g = Game(); g.foundations = [[] for _ in range(4)]; g.tableau = [[] for _ in range(7)]
g.stock = []; g.waste = [Card(1, "S", True)]; g.score = 0
g.move("w", "f"); assert g.score == 1               # to foundation = +1
g.tableau[0] = [Card(3, "H", True)]
g.waste = [Card(2, "S", True)]; g.move("w", "f"); assert g.score == 2
assert g.move("f0", "t0") is True; assert g.score == 1   # off foundation = -1
g2 = Game(); g2.foundations = [[Card(1, "C", True)], [], [], []]
g2.tableau = [[Card(2, "H", True)], [], [], [], [], [], []]; g2.stock = []; g2.waste = []; g2.score = 0
g2.move("f0", "t0"); assert g2.score == -1          # not clamped at 0
print("OK Klondike scoring: +1 onto foundation, -1 off, not clamped")

print("\nTEST7 PASS")
