"""Regression test for the 'sub-run drop' fix.

Bug: when a pile's top is itself a movable run (e.g. 4S-3S in Spider) and you
drop it on an anchor that only accepts the smaller sub-run (a 4H accepts the 3S
but not the whole 4S-3S), the UI reported 'illegal move' because the default
selection grabbed the whole run and never tried a smaller one.

The TUI's drop_on now retries smaller sub-runs (largest first) for a
default (non-exact) selection. This reproduces that exact logic against the
engine so the behaviour stays correct.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aisle import new_solitaire, Card


def drop_on(game, src, dst, selected_n, selected_exact):
    """Mirror of aisle_tui.play().drop_on (the move-resolution policy)."""
    ok = game.attempt_move(src, dst, selected_n)
    if not ok and not selected_exact:
        for n in range(selected_n - 1, 0, -1):
            if game.attempt_move(src, dst, n):
                ok = True
                break
    return ok


def spider_board(top_a, top_b):
    g = new_solitaire("spider")
    g.options["suits"] = 4
    t = g.ids_of("tableau")
    for s in g.slots:
        if g.kind(s.sid) == "tableau":
            s.cards = []
    g.slots[t[0]].cards = top_a
    g.slots[t[1]].cards = top_b
    return g, t[0], t[1]


# -- the reported bug: move a 3 onto a 4 when the 3 sits atop a run ----------
g, a, b = spider_board([Card(9, "H", True), Card(4, "S", True), Card(3, "S", True)],
                       [Card(4, "H", True)])
n = g.default_pickup(a)
assert n == 2, f"default pickup should grab the whole 4S-3S run, got {n}"
assert g.attempt_move(a, b, 2) is False, "whole run onto 4H must be illegal"
# reset and use the UI policy
g, a, b = spider_board([Card(9, "H", True), Card(4, "S", True), Card(3, "S", True)],
                       [Card(4, "H", True)])
assert drop_on(g, a, b, g.default_pickup(a), False), "3S should drop onto 4H"
assert [str(c) for c in g.cards(b)] == ["4H", "3S"]
assert [str(c) for c in g.cards(a)] == ["9H", "4S"]
print("OK 3 onto 4 works even when the 3 sits atop a run (the reported bug)")

# -- a genuine whole-run move is unaffected ----------------------------------
g, a, b = spider_board([Card(9, "H", True), Card(4, "S", True), Card(3, "S", True)],
                       [Card(5, "H", True)])
assert drop_on(g, a, b, g.default_pickup(a), False)
assert [str(c) for c in g.cards(b)] == ["5H", "4S", "3S"]
print("OK whole 4S-3S run still moves onto a 5")

# -- an explicit split (selected_exact) is never silently downsized ----------
g, a, b = spider_board([Card(9, "H", True), Card(4, "S", True), Card(3, "S", True)],
                       [Card(9, "D", True)])
assert drop_on(g, a, b, 2, True) is False, "exact selection must not be shrunk"
print("OK explicit split selection is not silently downsized")

# -- Klondike: a 3 onto a 4 of opposite colour, 3 atop an alt-colour run -----
g = new_solitaire("klondike", seed=1)
t = g.ids_of("tableau")
for s in g.slots:
    s.cards = []
g.slots[t[0]].cards = [Card(9, "C", True), Card(4, "S", True), Card(3, "H", True)]  # 4S-3H run
g.slots[t[1]].cards = [Card(4, "D", True)]   # 3H (red) onto 4D? no - need black 3 on red 4
# correct alt-colour: a red 3 lands on a black 4. Put a black 4 to receive 3H.
g.slots[t[1]].cards = [Card(4, "C", True)]
assert drop_on(g, t[0], t[1], g.default_pickup(t[0]), False)
assert [str(c) for c in g.cards(t[1])] == ["4C", "3H"]
print("OK Klondike: 3H onto 4C works when 3H sits atop a 4S-3H run")

print("\nTEST17 PASS")
