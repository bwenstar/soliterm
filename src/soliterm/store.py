"""soliterm.store - config + AisleRiot-style statistics persistence.

AisleRiot keeps PER-GAME statistics (not a score leaderboard): Wins, Total
games, win Percentage, and Best/Worst *winning time*. We persist the same set,
plus the player's chosen options per game, under XDG paths.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import time
from typing import Dict, Iterator, List, Optional

from . import aisleriot as ar

try:
    import fcntl
except ImportError:     # Windows: no advisory locks, the lock is a no-op
    fcntl = None  # type: ignore[assignment]

# The folder name under the XDG config and data dirs. Under its old name the
# game used "aisle-cli"; migrate.py copies those files over on the first run.
APP_DIR_NAME = "soliterm"

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
        # each key is checked on its own: one of the wrong type (a hand
        # edit, say) falls back to its default and the others still load
        # a game this version doesn't have (renamed, or from a newer
        # version) would have nothing to deal
        from .engine import GAMES  # local import to avoid a cycle at module load
        if isinstance(data.get("last_game"), str) and data["last_game"] in GAMES:
            cfg["last_game"] = data["last_game"]
        for key in ("symbols", "sync_aisleriot", "merged_into_aisleriot"):
            if isinstance(data.get(key), bool):
                cfg[key] = data[key]
        if isinstance(data.get("options"), dict):
            cfg["options"] = data["options"]
        # optional UI-preference keys, only present once set by the player:
        #   color      - colour on/off (the 'v' toggle)
        #   code_skin  - play wrapped in source (the 'c' toggle)
        #   camo_theme - boss-mode disguise theme
        #   view       - board view: "expanded" cards or "legacy" cells
        for key in ("color", "code_skin"):
            if isinstance(data.get(key), bool):
                cfg[key] = data[key]
        if isinstance(data.get("camo_theme"), str):
            cfg["camo_theme"] = data["camo_theme"]
        if data.get("view") in ("expanded", "legacy"):
            cfg["view"] = data["view"]
        # where the settings were copied from on the first run (migrate.py)
        if isinstance(data.get("migrated_from"), dict):
            cfg["migrated_from"] = data["migrated_from"]
    return cfg


def save_config(cfg: dict) -> bool:
    cfg = dict(cfg)
    on_disk = _read_json(config_path())
    if on_disk is None:
        return False
    if not cfg.get("merged_into_aisleriot") and on_disk.get("merged_into_aisleriot") is True:
        # a copy loaded before the merge (the TUI keeps one for the whole
        # session) must not clear the flag
        cfg["merged_into_aisleriot"] = True
    return _write_json(config_path(), cfg)


def game_options(cfg: dict, game_key: str) -> dict:
    """The player's saved options for a game, leaving out any the game doesn't
    offer or with a value it doesn't allow, so its defaults are used instead.
    """
    from .engine import GAMES  # local import to avoid a cycle at module load
    opts = cfg.get("options", {})
    val = opts.get(game_key) if isinstance(opts, dict) else None
    if not isinstance(val, dict) or game_key not in GAMES:
        return {}
    allowed = {okey: values for okey, _label, values in GAMES[game_key].option_spec()}
    # compare types too: JSON true would pass for 1, and 2.0 for 2
    return {k: v for k, v in val.items()
            if any(type(v) is type(a) and v == a for a in allowed.get(k, ()))}


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


def _count(value: object) -> int:
    """A stored count or time in seconds: a whole number, 0 or more.
    Anything else (a string, null, a fraction, a negative) reads as 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and value > 0 else 0


def _norm(s: Optional[dict]) -> dict:
    out = dict(EMPTY_STAT)
    if isinstance(s, dict):
        out.update({k: _count(s.get(k, 0)) for k in EMPTY_STAT})
    return out


# Set by --no-sync: the AisleRiot keyfile is left alone for the rest of the run.
_no_sync = False


def disable_sync() -> None:
    """Keep this run's statistics local: nothing reads or writes the AisleRiot
    keyfile from now on. Games recorded meanwhile are shared the next time
    sharing is on, as when sync_aisleriot is turned off in the config."""
    global _no_sync
    _no_sync = True


def sync_disabled() -> bool:
    """True if sharing is off for this run: --no-sync, or SOLITERM_NO_AISLERIOT
    set to anything but "" or "0"."""
    return _no_sync or os.environ.get("SOLITERM_NO_AISLERIOT", "") not in ("", "0")


def syncing() -> bool:
    """True when we should mirror stats with the installed AisleRiot."""
    if sync_disabled():
        return False
    cfg = load_config()
    return bool(cfg.get("sync_aisleriot", True)) and ar.available()


def _unreadable_keyfile() -> None:
    _notice(f"can't read {ar.keyfile_path()}, so statistics are not shared "
            "with AisleRiot this time; they are kept here")


def _unwritable_keyfile() -> None:
    if not os.path.isdir(ar.gnome_games_dir()):
        # AisleRiot hasn't been run yet. Nothing is wrong: the results wait
        # here until it has made its config.
        return
    _notice(f"couldn't write {ar.keyfile_path()}; results it is missing are "
            "kept here and added to it next time")


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
    else:
        stats.pop(META_KEY, None)
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
                # plus any games of ours the keyfile hasn't been given yet
                waiting = _unsynced(load_stats()).get(game_key)
                return _combined(_norm(shared), waiting) if waiting else _norm(shared)
    return _norm(load_stats().get(game_key))


def record_result(game_key: str, won: bool, seconds: float) -> dict:
    """Update a game's statistics with a finished game. Returns the new stat.

    Best/Worst track WINNING times only (AisleRiot semantics): a loss bumps the
    total but never the best/worst time. When syncing, the update is applied to
    BOTH the shared AisleRiot keyfile and our local JSON, so a game played here
    shows up in AisleRiot and vice versa. Games recorded while not sharing
    are listed in stats.json and go into the keyfile along with the next
    result recorded while sharing.
    """
    with _locked():
        return _record_result(game_key, won, seconds)


def _record_result(game_key: str, won: bool, seconds: float) -> dict:
    one = _one_game(won, seconds)
    if _can_sync():
        _merge_local_into_aisleriot_once()
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is not None:
            stats = load_stats()
            stats[game_key] = _combined(_norm(stats.get(game_key)), one)
            waiting = _unsynced(stats)
            waiting[game_key] = _combined(waiting.get(game_key, dict(EMPTY_STAT)), one)
            _share(stats, waiting, game_key)
            return get_stat(game_key)

    # not syncing: local JSON only. Settle the merge marker before this game
    # joins the history, so a later sync knows whether to fold it in.
    stats = load_stats()
    merged = _merged(stats)
    meta = {**_meta(stats), "merged_into_aisleriot": merged}
    updated = _combined(_norm(stats.get(game_key)), one)
    stats[game_key] = updated
    if merged and game_key in ar.GAME_TO_SECTION:
        # the merge won't run again, so note the game for the keyfile
        waiting = _unsynced(stats)
        waiting[game_key] = _combined(waiting.get(game_key, dict(EMPTY_STAT)), one)
        meta["unsynced"] = waiting
    stats[META_KEY] = meta
    save_stats(stats)
    return updated


def _one_game(won: bool, seconds: float) -> dict:
    """A record of one finished game, to add to a stat with _combined().

    Best/Worst are winning times only, so a loss adds nothing to them."""
    secs = max(1, int(round(seconds))) if won else 0
    return {"wins": int(won), "total": 1, "best": secs, "worst": secs}


def _unsynced(stats: dict) -> Dict[str, dict]:
    """Games recorded here that the keyfile hasn't been given yet, per game.

    They were played while we weren't sharing (sharing off, or the keyfile
    out of reach). Our own record of each game already counts them.
    """
    raw = _meta(stats).get("unsynced")
    if not isinstance(raw, dict):
        return {}
    out = {k: _norm(v) for k, v in raw.items() if k in ar.GAME_TO_SECTION}
    return {k: v for k, v in out.items() if v["total"] > 0}


def _share(stats: dict, waiting: Dict[str, dict], game_key: str) -> None:
    """Add the games in `waiting` to the keyfile, then save `stats` (whose
    own records already count them) with whatever didn't make it.

    They are taken off the unsynced list and saved before the keyfile is
    touched: if we stop half way, AisleRiot misses those games, which beats
    counting them twice.
    """
    meta = {**_meta(stats), "merged_into_aisleriot": True}
    meta.pop("unsynced", None)
    stats[META_KEY] = meta
    if not save_stats(stats):
        # the others are still listed in the file on disk; sending them
        # now would send them again next time
        waiting = {game_key: waiting[game_key]} if game_key in waiting else {}
    left: Dict[str, dict] = {}
    for key, games in waiting.items():
        def add(cur: Optional[dict], games: dict = games,
                ours: dict = _norm(stats.get(key))) -> dict:
            # A game the keyfile has no record of (a fresh keyfile, or sol
            # saving its own copy over ours) starts from our record, which
            # counts these games already, rather than from nothing.
            return ours if cur is None else _combined(_norm(cur), games)
        written = ar.update_stat(ar.GAME_TO_SECTION[key], add)
        if written is None:
            left[key] = games
        else:
            stats[key] = written    # our copy follows the keyfile
    if left:
        _unwritable_keyfile()
        meta["unsynced"] = left
    save_stats(stats)


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
    # the whole history goes in, so nothing is left waiting on its own
    meta = {**_meta(local), "merged_into_aisleriot": True}
    meta.pop("unsynced", None)
    local[META_KEY] = meta
    if not save_stats(local):
        return
    cfg = load_config()
    cfg["merged_into_aisleriot"] = True
    save_config(cfg)
    left: Dict[str, dict] = {}
    for game_key, lstat in local.items():
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is None:
            continue
        l = _norm(lstat)
        if l["total"] == 0:
            continue

        def add(cur: Optional[dict], l: dict = l) -> dict:
            return _combined(_norm(cur), l)

        if ar.update_stat(sect, add) is None:
            left[game_key] = l
    if left:
        # what the keyfile didn't take waits with the other unshared games
        _unwritable_keyfile()
        meta["unsynced"] = left
        save_stats(local)


def _combined(a: dict, b: dict) -> dict:
    """Two records of games added together, keeping the better times."""
    bests = [t for t in (a["best"], b["best"]) if t > 0]
    return {
        "wins": a["wins"] + b["wins"],
        "total": a["total"] + b["total"],
        "best": min(bests) if bests else 0,
        "worst": max(a["worst"], b["worst"]),
    }


def any_stats() -> bool:
    """True if a game we manage has a game on record, here or in the keyfile."""
    from .engine import GAME_ORDER  # local import to avoid a cycle at module load
    local = load_stats()
    return any(get_stat(k)["total"] > 0 or _norm(local.get(k))["total"] > 0
               for k in GAME_ORDER)


def backup_stats() -> List[str]:
    """Copy what reset_stats() would clear to backups beside the originals:
    the keyfile (when sharing) to aisleriot.soliterm-bak, and stats.json to
    stats.json.bak. Returns the backups made; raises OSError if one fails.
    """
    pairs = [(stats_path(), stats_path() + ".bak")]
    if _can_sync():
        pairs.insert(0, (ar.keyfile_path(), ar.keyfile_path() + ".soliterm-bak"))
    made = []
    for src, dst in pairs:
        if _copy_file(src, dst):
            made.append(dst)
    return made


def _copy_file(src: str, dst: str) -> bool:
    """Copy `src` over `dst` in one step, keeping its mode. False if there
    is no `src`; OSError if it can't be copied."""
    try:
        fin = open(src, "rb")
    except FileNotFoundError:
        return False
    with fin:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst),
                                   prefix=f".{os.path.basename(dst)}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fout:
                shutil.copyfileobj(fin, fout)
                fout.flush()
                os.fsync(fout.fileno())
            shutil.copymode(src, tmp)
            os.replace(tmp, dst)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return True


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
    stats = load_stats()
    if _can_sync():
        for game_key in GAME_ORDER:
            sect = ar.GAME_TO_SECTION.get(game_key)
            if sect is None:
                continue
            played: List[bool] = []

            def clear(cur: Optional[dict]) -> Optional[dict]:
                played.append(bool(cur and cur.get("total", 0) > 0))
                return dict(EMPTY_STAT) if cur is not None else None

            if ar.update_stat(sect, clear) is None and played and played[-1]:
                _notice(f"couldn't write {ar.keyfile_path()}, so AisleRiot "
                        "still has some of the statistics cleared here")
            # ours may have games the keyfile hasn't been given yet
            if (played and played[-1]) or _norm(stats.get(game_key))["total"] > 0:
                cleared += 1
    else:
        cleared = sum(1 for k in GAME_ORDER if _norm(stats.get(k))["total"] > 0)
    meta = dict(_meta(load_stats()))
    meta.pop("unsynced", None)      # games not yet shared are cleared too
    save_stats({META_KEY: meta})
    return cleared


def percentage(stat: dict) -> Optional[float]:
    if stat["total"] <= 0:
        return None
    return 100.0 * stat["wins"] / stat["total"]


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:d}:{seconds % 60:02d}"
