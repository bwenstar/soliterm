import sys, traceback
sys.path.insert(0, "/home/bta")
from sol import Game, Card

def count_cards(g):
    return len(g.stock)+len(g.waste)+sum(len(f) for f in g.foundations)+sum(len(t) for t in g.tableau)

def fresh():
    g = Game(draw_count=1, seed=3); g.new_game(); return g

reports = []

# 1) Out-of-range indices via move() — do they crash?
for spec in [("w","t7"),("w","f4"),("t7","t0"),("t0","f9"),("w","t99")]:
    g = fresh()
    try:
        r = g.move(*spec)
        print(f"move{spec} -> {r} (no crash) cards={count_cards(g)}")
    except Exception as e:
        print(f"move{spec} CRASH: {e!r}")
        reports.append(f"move{spec} crashes: {e!r}")

# 2) Explicit foundation index pointing at a DIFFERENT suit's pile.
# can_place_on_foundation checks suit match against that pile's top, so it
# should reject placing e.g. a heart onto the spade foundation. But what about
# placing an Ace onto an empty foundation index that is "reserved"? Two aces
# could both go to f0 if we call f0 twice? Let's test wrong-suit Ace stacking.
g = fresh()
g.foundations = [[Card(1,"S",True)], [], [], []]
g.waste = [Card(1,"H",True)]
# try to put Ace of hearts onto f0 (already has Ace spades). Should fail.
r = g.move("w","f0")
print("Ace H onto spade foundation f0:", r, "f0=", [str(c) for c in g.foundations[0]])
if r:
    reports.append("can stack wrong-suit onto explicit foundation index f0")

# 3) Duplicate-suit foundations: can we end up with same suit on two foundation
# piles using explicit indices? Put Ace S on f0 via auto, then Ace S again? only
# one exists. Instead: place 2S on empty f1 directly (rank!=1) - must fail.
g = fresh()
g.waste = [Card(2,"S",True)]
r = g.move("w","f1")
print("2S onto empty foundation f1 (should fail):", r)
if r:
    reports.append("non-Ace placed on empty foundation via explicit index")

# 4) move_to_tableau with count larger than pile / face_up; negative
g = fresh()
g.tableau[0] = [Card(13,"S",True)]
r1 = g.move("t0","t1",0)   # count 0
r2 = g.move("t0","t1",99)  # huge count
print("count0:", r1, "count99:", r2, "cards:", count_cards(g))

# 5) FALSE WIN probe: can is_won() be True with <52 distinct or duplicated cards?
# is_won just sums foundation lengths == 52. If a bug let a card be appended to
# a foundation twice (duplication) while also living elsewhere, count would
# exceed 52 elsewhere. But is_won could be satisfied by 52 cards in foundations
# even if some are dups. Try to drive duplication into a foundation via the
# explicit-index path combined with autofinish.
g = fresh()
# Build: foundation f0 = full spades A..K (13), f1 hearts A..K, f2 diamonds A..K,
# f3 clubs A..Q (12). One club King on tableau. Total foundations=51, +1 = 52.
g.stock=[]; g.waste=[]
g.foundations=[[Card(r,"S",True) for r in range(1,14)],
               [Card(r,"H",True) for r in range(1,14)],
               [Card(r,"D",True) for r in range(1,14)],
               [Card(r,"C",True) for r in range(1,13)]]
g.tableau=[[] for _ in range(7)]
g.tableau[0]=[Card(13,"C",True)]
print("pre-finish cards:", count_cards(g), "won:", g.is_won())
n=g.autofinish()
print("finish moved:", n, "won:", g.is_won(), "cards:", count_cards(g))
if count_cards(g)!=52:
    reports.append(f"card count drift after finish: {count_cards(g)}")

# 6) Try to trigger duplication: move same waste card via explicit index twice
# (history not involved). After a successful move the card leaves waste, so a
# second call should fail. Verify no duplication.
g = fresh()
g.waste=[Card(1,"S",True)]
g.foundations=[[],[],[],[]]
a=g.move("w","f0"); b=g.move("w","f0")
allf=sum(g.foundations,[])
print("double move w->f0:", a, b, "foundations cards:", [str(c) for c in allf], "cards:", count_cards(g))

print("\nReports:", reports if reports else "none")
