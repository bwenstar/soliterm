"""Regression tests for sharing statistics with the installed GNOME AisleRiot.

Run from the game folder: `python3 test12_aisleriot_sync.py`.
Everything runs against a TEMP XDG_CONFIG_HOME so the real AisleRiot keyfile is
never touched. Verifies: the keyfile reader/writer is surgical, stats sync both
ways, the one-time local->keyfile merge is additive and idempotent, and reset
only zeroes managed games.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def fresh_env(keyfile_text=None, local_json=None, cfg=None):
    """Build a temp XDG_CONFIG_HOME/XDG_DATA_HOME and (re)import the modules."""
    root = tempfile.mkdtemp(prefix="arsync_")
    cfgdir = os.path.join(root, "cfg")
    datadir = os.path.join(root, "data")
    os.makedirs(os.path.join(cfgdir, "gnome-games"))
    os.makedirs(os.path.join(cfgdir, "aisle-cli"))
    os.makedirs(os.path.join(datadir, "aisle-cli"))
    if keyfile_text is not None:
        with open(os.path.join(cfgdir, "gnome-games", "aisleriot"), "w") as fh:
            fh.write(keyfile_text)
    if local_json is not None:
        with open(os.path.join(datadir, "aisle-cli", "stats.json"), "w") as fh:
            json.dump(local_json, fh)
    if cfg is not None:
        with open(os.path.join(cfgdir, "aisle-cli", "config.json"), "w") as fh:
            json.dump(cfg, fh)
    os.environ["XDG_CONFIG_HOME"] = cfgdir
    os.environ["XDG_DATA_HOME"] = datadir
    # re-import fresh so module-level path helpers pick up the env
    for m in ("aisle_aisleriot", "aisle_store"):
        sys.modules.pop(m, None)
    import aisle_aisleriot as ar
    import aisle_store as store
    return ar, store, root


KEYFILE = """\
[Aisleriot Config]
Recent=spider;klondike;
Theme=tigullio.svgz

[spider.scm]
Statistic=20;112;591;1966;
Options=2

[klondike.scm]
Statistic=3;10;200;400;
Options=1
"""

# -- 1. surgical read/write preserves the rest of the file -------------------
ar, store, root = fresh_env(KEYFILE)
assert ar.available()
assert ar.read_stat("spider.scm") == {"wins": 20, "total": 112, "best": 591, "worst": 1966}
ar.write_stat("spider.scm", {"wins": 21, "total": 113, "best": 480, "worst": 1966})
text = open(os.path.join(root, "cfg", "gnome-games", "aisleriot")).read()
assert "Recent=spider;klondike;" in text and "Theme=tigullio.svgz" in text
assert "Options=2" in text and "Options=1" in text       # per-game options kept
assert "Statistic=21;113;480;1966;" in text
shutil.rmtree(root)
print("OK keyfile read/write is surgical (Config/Recent/Theme/Options preserved)")

# -- 1b. robustness: whitespace/duplicate, trailing blanks, idempotency, atomic
ar, store, root = fresh_env("[spider.scm]\nStatistic = 20;112;591;1966;\nOptions=2\n")
ar.write_stat("spider.scm", {"wins": 21, "total": 113, "best": 580, "worst": 1966})
out = open(os.path.join(root, "cfg", "gnome-games", "aisleriot")).read()
assert out.count("Statistic") == 1, f"duplicate Statistic key:\n{out}"
assert ar.read_stat("spider.scm") == {"wins": 21, "total": 113, "best": 580, "worst": 1966}
assert "Options=2" in out
shutil.rmtree(root)

orig = "[spider.scm]\nStatistic=1;1;1;1;\nOptions=2\n\n\n"
ar, store, root = fresh_env(orig)
kf = os.path.join(root, "cfg", "gnome-games", "aisleriot")
ar.write_stat("spider.scm", {"wins": 2, "total": 2, "best": 2, "worst": 2})
b1 = open(kf).read()
ar.write_stat("spider.scm", {"wins": 2, "total": 2, "best": 2, "worst": 2})
b2 = open(kf).read()
assert b1.endswith("Options=2\n\n\n"), "trailing blank lines eroded"
assert b1 == b2, "repeated identical write is not idempotent"
# writing the value already present is a byte-identical no-op
fresh = "[spider.scm]\nStatistic=1;1;1;1;\nOptions=2\n\n\n"
open(kf, "w").write(fresh)
ar.write_stat("spider.scm", {"wins": 1, "total": 1, "best": 1, "worst": 1})
assert open(kf).read() == fresh, "no-op write mutated the file"
import inspect
wsrc = inspect.getsource(ar._write_text)
assert "os.replace" in wsrc and "mkstemp" in wsrc, "write is not atomic"
shutil.rmtree(root)
print("OK robust: no duplicate keys, trailing blanks kept, idempotent, atomic write")

# -- 2. read direction: our game sees AisleRiot's existing wins --------------
ar, store, root = fresh_env(KEYFILE)
assert store.syncing()
assert store.get_stat("spider")["wins"] == 20
assert store.get_stat("spider")["total"] == 112
shutil.rmtree(root)
print("OK read direction: AisleRiot wins are visible in our game")

# -- 3. write direction: our result lands in AisleRiot's keyfile -------------
ar, store, root = fresh_env(KEYFILE)
new = store.record_result("spider", won=True, seconds=300)
assert new == {"wins": 21, "total": 113, "best": 300, "worst": 1966}
assert ar.read_stat("spider.scm") == new
# a loss only bumps total
store.record_result("klondike", won=False, seconds=99)
assert ar.read_stat("klondike.scm") == {"wins": 3, "total": 11, "best": 200, "worst": 400}
shutil.rmtree(root)
print("OK write direction: our games update AisleRiot's stats")

# -- 4. one-time local->keyfile merge is additive AND idempotent -------------
ar, store, root = fresh_env(
    KEYFILE,
    local_json={"spider": {"wins": 5, "total": 30, "best": 400, "worst": 1500},
                "golf": {"wins": 2, "total": 8, "best": 120, "worst": 300}},
    cfg={"sync_aisleriot": True, "merged_into_aisleriot": False})
store.record_result("klondike", won=True, seconds=100)   # triggers the merge
assert ar.read_stat("spider.scm") == {"wins": 25, "total": 142, "best": 400, "worst": 1966}
assert ar.read_stat("golf.scm") == {"wins": 2, "total": 8, "best": 120, "worst": 300}
# second record must not re-add the local totals
store.record_result("spider", won=False, seconds=10)
assert ar.read_stat("spider.scm")["total"] == 143       # only +1, not +30 again
shutil.rmtree(root)
print("OK one-time merge folds local history in once (additive, idempotent)")

# -- 5. reset zeroes only managed games, leaves other AisleRiot games alone --
ar, store, root = fresh_env(
    "[Aisleriot Config]\nRecent=spider;\n\n"
    "[spider.scm]\nStatistic=20;112;591;1966;\n\n"
    "[poker.scm]\nStatistic=5;50;0;0;\n")
n = store.reset_stats()
assert n == 1                                            # only spider had a record
assert ar.read_stat("spider.scm") == {"wins": 0, "total": 0, "best": 0, "worst": 0}
assert ar.read_stat("poker.scm") == {"wins": 5, "total": 50, "best": 0, "worst": 0}
shutil.rmtree(root)
print("OK reset zeroes managed games only; unmanaged AisleRiot games untouched")

# -- 6. when AisleRiot config is absent, we fall back to local JSON ----------
root = tempfile.mkdtemp(prefix="arsync_")
os.makedirs(os.path.join(root, "cfg"))            # no gnome-games dir at all
os.makedirs(os.path.join(root, "data"))
os.environ["XDG_CONFIG_HOME"] = os.path.join(root, "cfg")
os.environ["XDG_DATA_HOME"] = os.path.join(root, "data")
for m in ("aisle_aisleriot", "aisle_store"):
    sys.modules.pop(m, None)
import aisle_aisleriot as ar
import aisle_store as store
assert not ar.available()
assert not store.syncing()
s = store.record_result("freecell", won=True, seconds=120)
assert s == {"wins": 1, "total": 1, "best": 120, "worst": 120}
assert store.get_stat("freecell")["wins"] == 1            # from local JSON
shutil.rmtree(root)
print("OK without AisleRiot installed, falls back to local JSON cleanly")

print("\nTEST12 PASS")
