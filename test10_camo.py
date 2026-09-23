"""Regression tests for camouflage / boss mode (aisle_camo.py + wiring).

Run from the game folder: `python3 test10_camo.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aisle_camo

# -- every theme streams endlessly without raising or repeating-exhausting ----
for theme in aisle_camo.THEMES:
    gen = aisle_camo.stream(theme, seed=5)
    lines = [next(gen) for _ in range(1000)]
    assert len(lines) == 1000
    assert all(isinstance(line, str) for line in lines), theme
print("OK every theme streams 1000+ str lines without exhaustion")

# -- screenful returns exactly the requested number of lines -----------------
for theme in aisle_camo.THEMES:
    for n in (1, 10, 40, 120):
        block = aisle_camo.screenful(theme, n, seed=2)
        assert len(block) == n, f"{theme}/{n}: got {len(block)}"
print("OK screenful() returns the exact requested line count")

# -- an unknown theme falls back to a default scene (no crash) ---------------
gen = aisle_camo.stream("nonsense-theme", seed=1)
assert isinstance(next(gen), str)
print("OK unknown theme falls back gracefully")

# -- output looks like work, not like a card game ----------------------------
sample = "\n".join(aisle_camo.screenful("mixed", 200, seed=3))
for tell in ("♠", "♥", "♦", "♣", "[##]", "score=", "Foundation"):
    assert tell not in sample, f"camo output leaked a game tell: {tell!r}"
assert any(k in sample for k in ("gcc", "pytest", "docker", "git", "INFO")), \
    "camo output does not look like developer work"
print("OK camo output contains no game tells and reads as developer work")

# -- the boss key / command are wired into both UIs --------------------------
tui = open(os.path.join(os.path.dirname(__file__), "aisle_tui.py")).read()
assert "camouflage_screen" in tui and "aisle_camo" in tui
assert "curses.KEY_F2" in tui
cli = open(os.path.join(os.path.dirname(__file__), "aisle_cli.py")).read()
assert "__boss__" in cli and "aisle_camo" in cli
print("OK boss mode wired into TUI (b / F2) and text mode (b / boss)")

print("\nTEST10 PASS")
