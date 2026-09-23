import sys, random, traceback
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
    c = count_cards(g)
    if c != 52:
        raise AssertionError(f"{where}: card count = {c} (expected 52)")
    cs = [(card.rank, card.suit) for card in all_cards(g)]
    if len(cs) != 52 or len(set(cs)) != 52:
        # find dups
        from collections import Counter
        cnt = Counter(cs)
        dups = [k for k, v in cnt.items() if v > 1]
        raise AssertionError(f"{where}: duplicate/missing cards. dups={dups} total={len(cs)} unique={len(set(cs))}")

bugs = []
for seed in range(50):
    rng = random.Random(seed * 7919 + 13)
    dc = rng.choice([1, 3])
    g = Game(draw_count=dc, seed=seed)
    g.new_game()
    try:
        check(g, f"seed{seed} initial")
    except AssertionError as e:
        bugs.append(str(e)); print("BUG:", e); continue

    last_op = "init"
    for op in range(200):
        choice = rng.random()
        try:
            if choice < 0.30:
                last_op = "draw"
                g.draw()
            elif choice < 0.45:
                last_op = "autofinish"
                g.autofinish()
            elif choice < 0.55:
                last_op = "autoplay_once"
                g.autoplay_once()
            elif choice < 0.62:
                last_op = "undo"
                g.undo()
            elif choice < 0.75:
                # waste -> tableau or foundation
                dest = rng.choice([f"t{rng.randint(0,6)}", "f", f"f{rng.randint(0,3)}"])
                last_op = f"move w {dest}"
                g.move("w", dest)
            else:
                # tableau -> tableau / foundation, random count sometimes
                src = f"t{rng.randint(0,6)}"
                dest = rng.choice([f"t{rng.randint(0,6)}", "f", f"f{rng.randint(0,3)}"])
                cnt = rng.choice([None, 1, 2, 3, 4, 5, 13])
                last_op = f"move {src} {dest} cnt={cnt}"
                g.move(src, dest, cnt)
        except Exception as e:
            tb = traceback.format_exc()
            bugs.append(f"seed{seed} op{op} CRASH on {last_op}: {e!r}\n{tb}")
            print(f"BUG CRASH seed{seed} op{op} {last_op}: {e!r}")
            break
        try:
            check(g, f"seed{seed} op{op} after {last_op}")
        except AssertionError as e:
            bugs.append(str(e) + f" [last_op={last_op}]")
            print("BUG INVARIANT:", e, "last_op=", last_op)
            break
    else:
        pass

print(f"\nTotal bugs found: {len(bugs)}")
if not bugs:
    print("TEST4 PASS (no crashes, no card leaks/dups across 50 seeds x 200 ops)")
