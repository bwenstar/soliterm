"""Regression tests for the board-view toggle (expanded card boxes vs legacy
single-line cells) in aisle_tui.BoardUI, plus its config persistence.

Run from the game folder: `python3 test18_viewtoggle.py`.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aisle
import aisle_tui
from aisle import new_solitaire, GAME_ORDER


class Scr:
    def __init__(self, h, w):
        self.h, self.w = h, w
        self.g = [[" "] * w for _ in range(h)]

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        self.g = [[" "] * self.w for _ in range(self.h)]

    def refresh(self):
        pass

    def addnstr(self, y, x, text, nmax, attr=0):
        if not (0 <= y < self.h):
            return
        for i, ch in enumerate(text[:nmax]):
            if 0 <= x + i < self.w:
                self.g[y][x + i] = ch

    def getch(self):
        return -1

    def keypad(self, *a):
        pass

    def text(self):
        return "\n".join("".join(r).rstrip() for r in self.g)


def draw(g, view, h=36, w=120):
    scr = Scr(h, w)
    ui = aisle_tui.BoardUI(scr, g, symbols=True, has_color=False, view=view)
    cur = g.ids_of("tableau")[0] if g.ids_of("tableau") else 0
    ui.draw(None, 1, cur, g.hint(), 1.0, view)
    return ui, scr


# -- 1. expanded uses multi-row boxes; legacy uses single-line cells ---------
g = new_solitaire("klondike", seed=5)
g.deal()
ui_e, scr_e = draw(g, "expanded")
ui_l, scr_l = draw(g, "legacy")
assert ui_e.card_h == 4 and "┌" in scr_e.text(), "expanded view not drawing boxes"
assert ui_l.card_h == 1 and "┌" not in scr_l.text() and "[" in scr_l.text(), \
    "legacy view not drawing compact cells"
print("OK expanded draws card boxes; legacy draws single-line cells")

# -- 2. both views expose the SAME clickable (slot, card) targets ------------
e_targets = set(ui_e.hit.values())
l_targets = set(ui_l.hit.values())
assert e_targets == l_targets, "view changes which cards are clickable!"
print("OK both views expose identical clickable card targets")

# -- 3. set_view switches geometry and rejects bad values --------------------
ui = ui_e
ui.set_view("legacy")
assert ui.view == "legacy" and ui.card_h == 1
ui.set_view("expanded")
assert ui.view == "expanded" and ui.card_h == 4
ui.set_view("nonsense")
assert ui.view == "expanded", "an invalid view should fall back to expanded"
print("OK set_view toggles geometry and rejects garbage")

# -- 4. all 9 games render in BOTH views without error -----------------------
for key in GAME_ORDER:
    gg = new_solitaire(key, seed=2)
    for view in ("expanded", "legacy"):
        draw(gg, view)
print("OK all 9 games render in both views")

# -- 5. the view preference persists in config -------------------------------
import importlib
root = tempfile.mkdtemp(prefix="viewtog_")
os.makedirs(os.path.join(root, "cfg"))
os.makedirs(os.path.join(root, "data"))
os.environ["XDG_CONFIG_HOME"] = os.path.join(root, "cfg")
os.environ["XDG_DATA_HOME"] = os.path.join(root, "data")
sys.modules.pop("aisle_store", None)
import aisle_store as store
cfg = store.load_config()
assert "view" not in cfg                      # unset until toggled (default expanded)
cfg["view"] = "legacy"
store.save_config(cfg)
assert store.load_config()["view"] == "legacy"
cfg["view"] = "expanded"
store.save_config(cfg)
assert store.load_config()["view"] == "expanded"
# a corrupt value is ignored, not crashed on
p = store.config_path()
d = json.load(open(p))
d["view"] = "garbage"
json.dump(d, open(p, "w"))
assert store.load_config().get("view", "expanded") == "expanded"
print("OK view preference persists across reloads; bad values ignored")

print("\nTEST18 PASS")
