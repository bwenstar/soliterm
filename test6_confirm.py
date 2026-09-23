import sys
sys.path.insert(0, "/home/bta")
from sol import Game, Card, apply_command

def count_cards(g):
    return len(g.stock)+len(g.waste)+sum(len(f) for f in g.foundations)+sum(len(t) for t in g.tableau)

print("=== Confirm case6 was test-setup artifact (not engine bug) ===")
g = Game(draw_count=1, seed=3); g.new_game()
print("fresh deal cards:", count_cards(g))  # should be 52
g.waste=[Card(1,"S",True)]  # injecting a duplicate AS that already exists in deal
print("after injecting AS into waste:", count_cards(g))
# So 53 in test5 case6 was MY injection on top of full deal. Confirm:
print("--> case6 53 is a TEST artifact, engine did not duplicate.\n")

print("=== Is the IndexError reachable through the real command parser? ===")
# apply_command parses src/dst from single chars; tableau only 1-7 -> t0..t6.
# foundation dest is only 'f' (auto), never 'f<idx>'. So t7/f9 are NOT reachable
# via text UI. Check curses: it uses move(pending, 't<col>') col 0..6, and 'f'.
g = Game(draw_count=1, seed=3); g.new_game()
for cmd in ["80", "08", "wf9", "t7t0", "9f"]:
    ok, msg = apply_command(g, cmd)
    print(f"apply_command({cmd!r}) -> ok={ok} msg={msg!r}")

print("\n=== Direct API: does move() with bad index crash? (already shown) ===")
g = Game(draw_count=1, seed=3); g.new_game()
import traceback
for spec in [("t7","t0"),("t0","f9"),("t9","t0"),("t-1","t0")]:
    try:
        r = g.move(*spec)
        print(f"move{spec} -> {r}")
    except Exception as e:
        print(f"move{spec} CRASH {type(e).__name__}: {e}")

print("\n=== Explicit foundation index: duplicate-suit foundation possible? ===")
# Place Ace S on f0 (auto would pick f0). Then place 2S but target f1 explicitly.
g = Game(draw_count=1, seed=3); g.new_game()
g.stock=[]; g.waste=[]; g.tableau=[[] for _ in range(7)]
g.foundations=[[Card(1,"S",True)],[],[],[]]
# Put 2S in waste, try to move to f1 (empty) explicitly
g.waste=[Card(2,"S",True)]
r = g.move("w","f1")
print("2S -> empty f1 while spades live on f0:", r, "f1=", [str(c) for c in g.foundations[1]])
# 2S onto empty f1 fails because empty foundation needs an Ace. Good.
# But what about a SECOND ace of a suit? Only one ace per suit exists, so a
# duplicate-suit foundation can't arise from legal cards. Confirm rejection of
# Ace of suit already foundationed elsewhere:
g.foundations=[[Card(1,"S",True)],[],[],[]]
g.waste=[Card(1,"S",True)]  # hypothetical duplicate ace
r2 = g.move("w","f1")
print("duplicate AceS -> empty f1:", r2, "(empty foundation accepts ANY ace, so a dup suit foundation IS creatable if a dup card existed; but no dup cards exist in a real deal)")
