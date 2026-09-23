"""soliterm.store - config + AisleRiot-style statistics persistence.

AisleRiot keeps PER-GAME statistics (not a score leaderboard): Wins, Total
games, win Percentage, and Best/Worst *winning time*. We persist the same set,
plus the player's chosen options per game, under XDG paths.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from typing import Dict, Iterator, List, Optional

from . import aisleriot as ar

try:
    import fcntl
except ImportError:     # Windows: no advisory locks, the lock is a no-op
    fcntl = None  # type: ignore[assignment]

APP_DIR_NAME = "aisle-cli"

# Things the player should hear about (say, a keyfile we could not read),
# collected here for the command line to print when the game is over.
_notices: List[str] = []


def notices() -> List[str]:
    """What went wrong with the stats files so far in this run, in order."""
    return list(_notices)


def _notice(msg: str) -> None:
    if msg not in _notices:
        _notices.append(msg)


def _xdg(env: str, default_rel: str) -> str:
    base = os.environ.get(env)
    if not base:
        base = os.path.join(os.path.expanduser("~"), default_rel)
    return base


def config_dir() -> str:
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), APP_DIR_NAME)


def data_dir() -> str:
    return os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def stats_path() -> str:
    return os.path.join(data_dir(), "stats.json")


# --------------------------------------------------------------------------- #
# Reading and writing our JSON files
# --------------------------------------------------------------------------- #

def _read_json(path: str) -> Optional[dict]:
    """The object in a JSON file: {} if there is no file, None if it is there
    but can't be read (and so must not be written over either).

    A file that doesn't hold a JSON object (cut short by a crash, say) is
    moved aside to <name>.corrupt-<time> and reads as {}, so the next save
    can't destroy what is left of it.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _notice(f"can't read {path} ({exc.strerror or exc}), "
                "so it is left alone and nothing is saved to it")
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        data = None
    if isinstance(data, dict):
        return data
    return {} if _set_aside(path) else None


def _set_aside(path: str) -> bool:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = f"{path}.corrupt-{stamp}"
    n = 1
    while os.path.exists(target):
        target = f"{path}.corrupt-{stamp}-{n}"
        n += 1
    try:
        os.rename(path, target)
    except FileNotFoundError:
        return True     # another copy of the game moved it first
    except OSError as exc:
        _notice(f"{path} is damaged and can't be moved aside "
                f"({exc.strerror or exc}), so nothing is saved to it")
        return False
    _notice(f"{path} was damaged; it is kept as {target} and a new one started")
    return True


def _write_json(path: str, obj: dict) -> bool:
    """Save `obj` to `path` whole or not at all.

    The JSON goes to a temp file in the same directory, which then replaces
    the old file in one step, so a crash or a full disk leaves the old file
    as it was rather than a truncated one.
    """
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
        text = json.dumps(obj, indent=2)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{os.path.basename(path)}.",
                                   suffix=".tmp")
    except (OSError, TypeError, ValueError):
        return False
    try:
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except FileNotFoundError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


# Reentrancy count for _locked(): record_result holds the lock while it
# calls helpers that take it too.
_lock_depth = 0


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """Hold the stats lock while reading, changing and saving the stats.

    Two copies of the game finishing at once would otherwise both read the
    same stats and the later save would drop the other's result. The lock is
    advisory (flock on stats.lock beside stats.json) and does nothing where
    there is no fcntl, or when the lock file can't be made.
    """
    global _lock_depth
    fh = None
    if _lock_depth == 0 and fcntl is not None:
        try:
            os.makedirs(data_dir(), exist_ok=True)
            fh = open(os.path.join(data_dir(), "stats.lock"), "a")
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            if fh is not None:
                fh.close()
            fh = None
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        if fh is not None:
            fh.close()      # which also lets go of the lock


DEFAULT_CONFIG = {
    "last_game": "klondike",
    "symbols": True,
    "options": {},          # per-game option overrides, keyed by game key
    # Share statistics with the installed GNOME AisleRiot. When on (and its
    # config dir exists) we read from and write to its keyfile, so games played
    # in either program are mirrored in both. Defaults on.
    "sync_aisleriot": True,
    # Where older versions kept the one-time merge flag. The flag now lives in
    # stats.json (see _merged); this copy is still honoured, and kept at True
    # once set, so an older version reading this file won't merge again.
    "merged_into_aisleriot": False,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["options"] = {}
    data = _read_json(config_path())
    if data:
        if isinstance(data.get("last_game"), str):
            cfg["last_game"] = data["last_game"]
        cfg["symbols"] = bool(data.get("symbols", True))
        if isinstance(data.get("options"), dict):
            cfg["options"] = data["options"]
        cfg["sync_aisleriot"] = bool(data.get("sync_aisleriot", True))
        cfg["merged_into_aisleriot"] = bool(data.get("merged_into_aisleriot", False))
        # optional UI-preference keys, only present once set by the player:
        #   color      - colour on/off (the 'v' toggle)
        #   code_skin  - play wrapped in source (the 'c' toggle)
        #   camo_theme - boss-mode disguise theme
        #   view       - board view: "expanded" cards or "legacy" cells
        if "color" in data:
            cfg["color"] = bool(data["color"])
        if "code_skin" in data:
            cfg["code_skin"] = bool(data["code_skin"])
        if isinstance(data.get("camo_theme"), str):
            cfg["camo_theme"] = data["camo_theme"]
        if data.get("view") in ("expanded", "legacy"):
            cfg["view"] = data["view"]
    return cfg


def save_config(cfg: dict) -> bool:
    cfg = dict(cfg)
    on_disk = _read_json(config_path())
    if on_disk is None:
        return False
    if not cfg.get("merged_into_aisleriot") and on_disk.get("merged_into_aisleriot"):
        # a copy loaded before the merge (the TUI keeps one for the whole
        # session) must not clear the flag
        cfg["merged_into_aisleriot"] = True
    return _write_json(config_path(), cfg)


def game_options(cfg: dict, game_key: str) -> dict:
    opts = cfg.get("options", {})
    val = opts.get(game_key)
    return dict(val) if isinstance(val, dict) else {}


def set_game_options(cfg: dict, game_key: str, options: dict) -> None:
    cfg.setdefault("options", {})[game_key] = dict(options)


# --------------------------------------------------------------------------- #
# Statistics  (per game key: wins, total, best, worst, with times in seconds)
# --------------------------------------------------------------------------- #

EMPTY_STAT = {"wins": 0, "total": 0, "best": 0, "worst": 0}

# stats.json holds one record per game key plus this entry for bookkeeping.
# The one-time merge flag lives here rather than in config.json so that it
# always travels with the stats it guards: resetting or losing the config, or
# copying just the data dir, can't make the merge run twice.
META_KEY = "_meta"


def _norm(s: Optional[dict]) -> dict:
    out = dict(EMPTY_STAT)
    if isinstance(s, dict):
        out.update({k: int(s.get(k, 0)) for k in EMPTY_STAT})
    return out


def syncing() -> bool:
    """True when we should mirror stats with the installed AisleRiot."""
    cfg = load_config()
    return bool(cfg.get("sync_aisleriot", True)) and ar.available()


def _unreadable_keyfile() -> None:
    _notice(f"can't read {ar.keyfile_path()}, so statistics are not shared "
            "with AisleRiot this time; they are kept here")


def _can_sync() -> bool:
    """syncing(), unless the keyfile is there but can't be read.

    Then sharing is skipped and results stay in the local stats, so nothing
    is ever written over a keyfile we could not read first.
    """
    if not syncing():
        return False
    if not ar.readable():
        _unreadable_keyfile()
        return False
    return True


def load_stats() -> dict:
    return _read_json(stats_path()) or {}


def _meta(stats: dict) -> dict:
    meta = stats.get(META_KEY)
    return meta if isinstance(meta, dict) else {}


def _merged(stats: dict) -> bool:
    """True once the local history in `stats` has been added to the keyfile.

    The marker in stats.json or the flag older versions kept in config.json
    is enough. A stats.json from before the marker, sitting next to a
    keyfile, counts as merged as well: that older version was syncing, so
    its stats.json is a mirror of the keyfile and adding it would double
    every shared stat. (If AisleRiot only turned up later, its old games are
    left out of the shared totals, which is the lesser harm.)
    """
    flag = _meta(stats).get("merged_into_aisleriot")
    if flag is True or load_config()["merged_into_aisleriot"]:
        return True
    if flag is None and any(k in ar.GAME_TO_SECTION for k in stats):
        return os.path.exists(ar.keyfile_path())
    return False


def save_stats(stats: dict) -> bool:
    stats = dict(stats)
    current = _read_json(stats_path())
    if current is None:
        return False
    # Keep the bookkeeping entry of the file on disk when the caller has
    # none, and never turn a merged marker back off.
    on_disk = _meta(current)
    meta = dict(_meta(stats)) if META_KEY in stats else dict(on_disk)
    if on_disk.get("merged_into_aisleriot") is True:
        meta["merged_into_aisleriot"] = True
    if meta:
        stats[META_KEY] = meta
    return _write_json(stats_path(), stats)


def get_stat(game_key: str) -> dict:
    """A game's stats. When syncing, AisleRiot's keyfile is the source of truth
    (so wins recorded by AisleRiot itself show up here); otherwise local JSON.
    """
    if syncing():
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is not None:
            try:
                shared = ar.read_stat(sect)
            except OSError:
                _unreadable_keyfile()
                shared = None
            if shared is not None:
                return _norm(shared)
    return _norm(load_stats().get(game_key))


def record_result(game_key: str, won: bool, seconds: float) -> dict:
    """Update a game's statistics with a finished game. Returns the new stat.

    Best/Worst track WINNING times only (AisleRiot semantics): a loss bumps the
    total but never the best/worst time. When syncing, the update is applied to
    BOTH the shared AisleRiot keyfile and our local JSON, so a game played here
    shows up in AisleRiot and vice versa.
    """
    with _locked():
        return _record_result(game_key, won, seconds)


def _record_result(game_key: str, won: bool, seconds: float) -> dict:
    # Fold the one win/loss into a given baseline stat.
    def apply(base: Optional[dict]) -> dict:
        s = _norm(base)
        s["total"] += 1
        if won:
            s["wins"] += 1
            secs = max(1, int(round(seconds)))
            if s["best"] == 0 or secs < s["best"]:
                s["best"] = secs
            if secs > s["worst"]:
                s["worst"] = secs
        return s

    if _can_sync():
        _merge_local_into_aisleriot_once()
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is not None:
            stats = load_stats()
            # built on the shared value as it is when we write
            updated = ar.update_stat(sect, apply)
            if updated is None:
                updated = apply(stats.get(game_key))
            # keep local JSON as a mirror/backup in lock-step with the keyfile
            stats[game_key] = updated
            stats[META_KEY] = {**_meta(stats), "merged_into_aisleriot": True}
            save_stats(stats)
            return updated

    # not syncing: local JSON only. Settle the merge marker before this game
    # joins the history, so a later sync knows whether to fold it in.
    stats = load_stats()
    stats[META_KEY] = {**_meta(stats), "merged_into_aisleriot": _merged(stats)}
    updated = apply(stats.get(game_key))
    stats[game_key] = updated
    save_stats(stats)
    return updated


def _merge_local_into_aisleriot_once() -> None:
    """One-time additive merge of any pre-existing local stats into the keyfile.

    Before we shared storage, this game kept its own JSON stats. The first time
    we sync, fold those prior games into AisleRiot's totals so nothing is lost,
    then mark it done so we never double-count. Per game we add our local totals
    to AisleRiot's and keep the better (faster best / slower worst) times.

    The marker is saved before the keyfile is touched: if we stop half way,
    AisleRiot misses some old games, which beats counting them twice.
    """
    local = load_stats()
    if _merged(local):
        return
    local[META_KEY] = {**_meta(local), "merged_into_aisleriot": True}
    if not save_stats(local):
        return
    cfg = load_config()
    cfg["merged_into_aisleriot"] = True
    save_config(cfg)
    for game_key, lstat in local.items():
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is None:
            continue
        l = _norm(lstat)
        if l["total"] == 0:
            continue

        def add(cur: Optional[dict], l: dict = l) -> dict:
            return _combined(_norm(cur), l)

        ar.update_stat(sect, add)


def _combined(a: dict, b: dict) -> dict:
    """Two records of games added together, keeping the better times."""
    bests = [t for t in (a["best"], b["best"]) if t > 0]
    return {
        "wins": a["wins"] + b["wins"],
        "total": a["total"] + b["total"],
        "best": min(bests) if bests else 0,
        "worst": max(a["worst"], b["worst"]),
    }


def reset_stats() -> int:
    """Clear statistics for the games we manage. Returns how many were cleared.

    When syncing, each managed game's Statistic is zeroed in the shared keyfile
    too (other AisleRiot games and all non-Statistic keys are left untouched).
    Local JSON is always cleared. Returns the count of games that had a record.
    """
    with _locked():
        return _reset_stats()


def _reset_stats() -> int:
    from .engine import GAME_ORDER  # local import to avoid a cycle at module load
    cleared = 0
    if _can_sync():
        for game_key in GAME_ORDER:
            sect = ar.GAME_TO_SECTION.get(game_key)
            if sect is None:
                continue
            played: List[bool] = []

            def clear(cur: Optional[dict]) -> Optional[dict]:
                played.append(bool(cur and cur.get("total", 0) > 0))
                return dict(EMPTY_STAT) if cur is not None else None

            ar.update_stat(sect, clear)
            if played and played[-1]:
                cleared += 1
    else:
        cleared = sum(1 for v in load_stats().values()
                      if isinstance(v, dict) and v.get("total", 0) > 0)
    save_stats({})
    return cleared


def percentage(stat: dict) -> Optional[float]:
    if stat["total"] <= 0:
        return None
    return 100.0 * stat["wins"] / stat["total"]


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:d}:{seconds % 60:02d}"
