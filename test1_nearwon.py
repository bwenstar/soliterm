import sys
sys.path.insert(0, "/home/bta")
from sol import Game, Card

def count_cards(g):
    n = len(g.stock) + len(g.waste)
    n += sum(len(f) for f in g.foundations)
    n += sum(len(t) for t in g.tableau)
    return n

def all_cards(g):
    out = []
    out += g.stock + g.waste
    for f in g.foundations: out += f
    for t in g.tableau: out += t
    return out

# Construct a near-won game: all foundations at Queen (per suit), Kings available.
g = Game(draw_count=1, seed=1)
g.new_game()
# Wipe everything
g.stock = []
g.waste = []
g.foundations = [[] for _ in range(4)]
g.tableau = [[] for _ in range(7)]

# Foundations order in foundation_for_suit: it picks the foundation already
# holding that suit. We'll fill foundations f0..f3 with S,H,D,C up to Queen(12).
suits = ["S", "H", "D", "C"]
for fi, suit in enumerate(suits):
    g.foundations[fi] = [Card(r, suit, True) for r in range(1, 13)]  # A..Q (12 cards)

# Place the 4 Kings on tableau tops (face up), one per pile.
g.tableau[0] = [Card(13, "S", True)]
g.tableau[1] = [Card(13, "H", True)]
g.tableau[2] = [Card(13, "D", True)]
g.tableau[3] = [Card(13, "C", True)]

print("cards before:", count_cards(g))
assert count_cards(g) == 52, count_cards(g)
# Check uniqueness
cs = [(c.rank, c.suit) for c in all_cards(g)]
assert len(cs) == len(set(cs)) == 52, "duplicate/missing before autofinish"

print("is_won before:", g.is_won())
assert not g.is_won()

n = g.autofinish()
print("autofinish moved:", n)
print("cards after:", count_cards(g))
print("is_won after:", g.is_won())
print("foundation lens:", [len(f) for f in g.foundations])

assert count_cards(g) == 52, count_cards(g)
assert n == 4, f"expected to move 4 kings, moved {n}"
assert g.is_won(), "autofinish did NOT complete a near-won game"
print("TEST1 PASS")
