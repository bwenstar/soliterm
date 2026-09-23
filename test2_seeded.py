import sys
sys.path.insert(0, "/home/bta")
from sol import Game

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

def check(g, where):
    assert count_cards(g) == 52, f"{where}: count={count_cards(g)}"
    cs = [(c.rank, c.suit) for c in all_cards(g)]
    assert len(set(cs)) == 52, f"{where}: duplicate/missing cards"

for seed in range(20):
    g = Game(draw_count=1, seed=seed)
    g.new_game()
    check(g, f"seed{seed} initial")
    # Loop: draw and autofinish many times. Use an iteration cap to detect
    # infinite loops in autofinish (it returns int, but verify it terminates).
    for it in range(500):
        moved = g.autofinish()
        check(g, f"seed{seed} it{it} after autofinish")
        if g.is_won():
            break
        drew = g.draw()
        check(g, f"seed{seed} it{it} after draw")
        if not drew and moved == 0:
            # truly stuck on this naive strategy; stop
            break
    print(f"seed {seed}: moves={g.moves} redeals={g.redeals} won={g.is_won()} cards={count_cards(g)}")

print("TEST2 PASS")
