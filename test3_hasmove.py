import sys
sys.path.insert(0, "/home/bta")
from sol import Game, Card

def count_cards(g):
    n = len(g.stock) + len(g.waste)
    n += sum(len(f) for f in g.foundations)
    n += sum(len(t) for t in g.tableau)
    return n

# ---- Case A: contrived STUCK board, no legal move and no stock/waste draw ----
# Build a board where:
#  - stock and waste are empty (so draw() returns False, has_any_move excludes draws)
#  - tableau tops cannot go to any foundation, nor onto each other, nor empty col
#  - no foundation move possible
# We need all 52 cards present and unique.
g = Game(draw_count=1, seed=0)
g.new_game()
g.stock = []
g.waste = []
g.foundations = [[] for _ in range(4)]
g.tableau = [[] for _ in range(7)]

# Strategy: make 7 piles, all face-up but arranged so no tableau->tableau,
# no ->foundation works, and no empty columns.
# Foundations empty => only Aces could go up. So keep all 4 aces buried
# (not on top of any pile). Tops should not be placeable on each other.
# A simple stuck arrangement: each pile is a single non-Ace card such that
# none can stack on another (need rank diff 1 and alt color to stack).
# Put all aces at the BOTTOM of piles, buried under other cards.
# Build 7 piles manually. Track used cards.
used = set()
def C(r, s):
    used.add((r, s))
    return Card(r, s, True)

# Piles: each bottom buried, tops chosen so no stacking possible.
# Tops: we want a set of 7 cards where no one is rank exactly one less and
# opposite color of another, and none is an Ace (Ace->empty foundation),
# and no empty piles.
# Use tops: KS, KH, KD, KC (kings can't go anywhere, no empty col), plus 3 more
# distinct non-stacking tops.
g.tableau[0] = [C(2, "C"), C(13, "S")]   # top KS
g.tableau[1] = [C(2, "D"), C(13, "H")]   # top KH
g.tableau[2] = [C(2, "H"), C(13, "D")]   # top KD
g.tableau[3] = [C(2, "S"), C(13, "C")]   # top KC
# remaining piles tops also kings? only 4 kings. Use other cards that can't stack.
# Put aces buried, tops = e.g. 5C,5D,5H. None is rank one below a king top, and
# 5C/5D/5H among themselves: 5 vs 5 no; can't stack same rank. Good.
g.tableau[4] = [C(1, "S"), C(5, "C")]
g.tableau[5] = [C(1, "H"), C(5, "D")]
g.tableau[6] = [C(1, "D"), C(5, "H")]

# We still need to place all remaining cards somewhere. count so far:
# bury the rest into pile bottoms (below the buried bottom). Put remaining cards
# face up but UNDER everything so they aren't tops. Actually they will be in
# middle; valid_tableau_run for tableau->tableau source only matters for the
# face-up run from first_up. Since all face up, the WHOLE pile is the run and
# must be a valid descending alt-color run for tableau->tableau moves to be
# considered. If piles are not valid runs, move_to_tableau returns False for
# that source. But has_any_move checks per-card placement of any face-up card.
# To be safe and truly stuck, make remaining buried cards FACE DOWN so they
# are not movable and not tops.
remaining = []
for s in "SHDC":
    for r in range(1, 14):
        if (r, s) not in used:
            remaining.append((r, s))
# distribute remaining as face-DOWN cards at the BOTTOM of piles
import itertools
piles = [g.tableau[i] for i in range(7)]
pi = 0
for (r, s) in remaining:
    piles[pi % 7].insert(0, Card(r, s, False))  # face down at bottom
    pi += 1

print("cards:", count_cards(g))
assert count_cards(g) == 52, count_cards(g)
# Verify uniqueness
allc = []
for t in g.tableau: allc += t
cs = [(c.rank, c.suit) for c in allc]
assert len(set(cs)) == 52, "dup/missing in stuck board"

# Sanity: draw must be impossible (no stock, no waste)
assert g.draw() is False, "draw should be impossible"

stuck = not g.has_any_move()
print("has_any_move on stuck board:", g.has_any_move())
# Double check: there should genuinely be no legal move. Verify by brute force.
def brute_has_move(g):
    # foundation from waste/tableau
    import copy
    # try every tableau top -> foundation
    for col in range(7):
        gg = Game.deserialize(g.serialize())
        if gg.move_to_foundation(f"t{col}"):
            return ("t->f", col)
    gg = Game.deserialize(g.serialize())
    if gg.move_to_foundation("w"):
        return ("w->f",)
    # waste -> tableau
    for col in range(7):
        gg = Game.deserialize(g.serialize())
        if gg.move("w", f"t{col}"):
            return ("w->t", col)
    # tableau -> tableau, all counts
    for src in range(7):
        for dst in range(7):
            if src == dst: continue
            for cnt in range(1, 14):
                gg = Game.deserialize(g.serialize())
                if gg.move(f"t{src}", f"t{dst}", cnt):
                    # ensure it's not a degenerate full-pile-to-empty no-op shuffle
                    return ("t->t", src, dst, cnt)
    return None

bm = brute_has_move(g)
print("brute force found move:", bm)
if stuck and bm is not None:
    print("BUG: has_any_move()==False but a legal move exists:", bm)
elif not stuck and bm is None:
    print("BUG: has_any_move()==True but NO legal move exists (false positive)")
else:
    print("Case A consistent: stuck=%s brute=%s" % (stuck, bm))

# ---- Case B: obvious available move ----
g2 = Game(draw_count=1, seed=0)
g2.new_game()
g2.stock = []
g2.waste = []
g2.foundations = [[] for _ in range(4)]
g2.tableau = [[] for _ in range(7)]
# Put an Ace of spades face up on a tableau top => obvious move to foundation
usedB = set()
def CB(r, s):
    usedB.add((r, s)); return Card(r, s, True)
g2.tableau[0] = [CB(1, "S")]
# fill the rest validly (face down bottoms) to keep 52
rem = [(r, s) for s in "SHDC" for r in range(1,14) if (r,s) not in usedB]
for i, (r, s) in enumerate(rem):
    g2.tableau[(i % 6) + 1].append(Card(r, s, False))
# flip nothing; t0 top is Ace face up
print("Case B cards:", count_cards(g2))
assert count_cards(g2) == 52
print("Case B has_any_move (expect True):", g2.has_any_move())
if not g2.has_any_move():
    print("BUG: has_any_move()==False but Ace->foundation is available")
else:
    print("Case B OK")

print("TEST3 DONE")
