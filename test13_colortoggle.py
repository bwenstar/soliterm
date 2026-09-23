"""Regression tests for the live colour toggle and UI-preference persistence.

Run from the game folder: `python3 test13_colortoggle.py`.
Uses a temp XDG config dir; never touches real user data.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def fresh_store():
    root = tempfile.mkdtemp(prefix="coltog_")
    os.makedirs(os.path.join(root, "cfg"))
    os.makedirs(os.path.join(root, "data"))
    os.environ["XDG_CONFIG_HOME"] = os.path.join(root, "cfg")
    os.environ["XDG_DATA_HOME"] = os.path.join(root, "data")
    sys.modules.pop("aisle_store", None)
    import aisle_store as store
    return store, root


# -- UI-preference keys persist across reloads (the toggle depends on this) --
store, root = fresh_store()
cfg = store.load_config()
assert "color" not in cfg, "color is unset until the player toggles it"
cfg["color"] = False
cfg["code_skin"] = True
cfg["camo_theme"] = "docker"
assert store.save_config(cfg)
c2 = store.load_config()
assert c2["color"] is False, "color preference did not persist"
assert c2["code_skin"] is True, "code_skin preference did not persist"
assert c2["camo_theme"] == "docker", "camo_theme did not persist"
# flipping it back also persists
c2["color"] = True
store.save_config(c2)
assert store.load_config()["color"] is True
shutil.rmtree(root)
print("OK color / code_skin / camo_theme persist across reloads")

# -- monochrome rendering path is crash-free, CP() returns 0 -----------------
import aisle
import aisle_tui
from aisle import new_solitaire, GAME_ORDER


class FakeScr:
    def getmaxyx(self):
        return (40, 140)

    def erase(self):
        pass

    def refresh(self):
        pass

    def addnstr(self, *a):
        pass

    def getch(self):
        return -1

    def keypad(self, *a):
        pass


for key in GAME_ORDER:
    g = new_solitaire(key, seed=2)
    ui = aisle_tui.BoardUI(FakeScr(), g, symbols=True, has_color=False)
    assert ui.CP(1) == 0 and ui.CP(8) == 0, "CP must be 0 when colour is off"
    cur = g.ids_of("tableau")[0] if g.ids_of("tableau") else 0
    ui.draw(None, 1, cur, g.hint(), 5.0, "colour off")     # must not raise
    ui.code_skin = True
    ui.draw(None, 1, cur, None, 5.0, "mono code skin")      # also in code skin
print("OK monochrome render works for all 9 games (plain and code-skin)")

# -- the toggle is wired in run(): capability vs preference, persisted -------
src = open(os.path.join(HERE, "aisle_tui.py")).read()
assert "color_capable = curses.has_colors()" in src, "no capability/preference split"
assert "nonlocal has_color" in src, "has_color not made live-mutable in play()"
assert 'ord("v")' in src, "'v' key not bound"
assert 'cfg["color"] = has_color' in src, "toggle not persisted to config"
assert "if color_capable:" in src, "pairs must init on capability, not preference"
assert "ui.has_color = has_color" in src, "renderer flag not updated on toggle"
assert "toggle colour" in src, "help text missing the toggle"
print("OK 'v' colour toggle wired: capability/preference split, persisted, in help")

print("\nTEST13 PASS")
