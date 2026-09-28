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
import signal
import tempfile
import time
from collections.abc import Callable, Iterator

from . import aisleriot as ar

try:
    import fcntl
except ImportError:  # Windows: no advisory locks, the lock is a no-op
    fcntl = None  # type: ignore[assignment]

# The folder name under the XDG config and data dirs. Under its old name the
# game used "aisle-cli"; migrate.py copies those files over on the first run.
APP_DIR_NAME = "soliterm"

# Things the player should hear about (say, a keyfile we could not read),
# collected here for the command line to print when the game is over.
_notices: list[str] = []


def notices() -> list[str]:
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


def _read_json(path: str) -> dict | None:
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
        _notice(
            f"can't read {path} ({exc.strerror or exc}), "
            "so it is left alone and nothing is saved to it"
        )
        return None
    try:
        # given bytes, json works out the encoding: UTF-8 with or without
        # the BOM Notepad puts in, or UTF-16 or UTF-32 as PowerShell may save
        # it (a file that fits none raises a ValueError too)
        data = json.loads(raw)
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
        return True  # another copy of the game moved it first
    except OSError as exc:
        _notice(
            f"{path} is damaged and can't be moved aside "
            f"({exc.strerror or exc}), so nothing is saved to it"
        )
        return False
    _notice(f"{path} was damaged; it is kept as {target} and a new one started")
    return True


def _write_json(path: str, obj: dict) -> bool:
    """Save `obj` to `path` as JSON, whole or not at all (see _write_text)."""
    try:
        text = json.dumps(obj, indent=2)
    except (OSError, TypeError, ValueError):
        return False
    return _write_text(path, text)


def _write_text(path: str, text: str) -> bool:
    """Save `text` to `path` whole or not at all.

    The text goes to a temp file in the same directory, which then replaces
    the old file in one step, so a crash or a full disk leaves the old file
    as it was rather than a truncated one. Whatever stops the write, Ctrl-C
    included, takes the temp file away with it.
    """
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{os.path.basename(path)}.", suffix=".tmp")
    except OSError:
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
    except BaseException as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(exc, OSError):
            return False
        raise
    return True


# Reentrancy count for _locked(): record_result holds the lock while it
# calls helpers that take it too.
_lock_depth = 0

# What the front end says while another copy of the game has the lock, and
# how it says it (see lock_wait_note)
LOCK_WAIT = "waiting for another copy of the game to finish with the statistics"
_on_wait: Callable[[], None] | None = None
_waiting = False


def waiting_for_lock() -> bool:
    """Whether this copy is stuck waiting for another to let go of the lock."""
    return _waiting


@contextlib.contextmanager
def lock_wait_note(say: Callable[[], None]) -> Iterator[None]:
    """Have say() called when the stats lock is busy, before the wait for
    it, so the player knows why the game has stopped. Another copy holds it
    only for a moment, unless it is stopped (Ctrl-Z) while it does."""
    global _on_wait  # noqa: PLW0603 (state for this run)
    old, _on_wait = _on_wait, say
    try:
        yield
    finally:
        _on_wait = old


# Ctrl-C, the terminal closing and kill: what signals_held holds back
_LEAVING = [getattr(signal, n) for n in ("SIGINT", "SIGHUP", "SIGTERM") if hasattr(signal, n)]


@contextlib.contextmanager
def signals_held() -> Iterator[None]:
    """Hold back Ctrl-C, SIGHUP and SIGTERM until the block is done.

    For saving or counting a game and marking it done as one step: one
    landing between the two would have the game saved or counted again on
    the way out. A signal that comes meanwhile lands as the block ends.
    Where signals can't be held (Windows) it does nothing.

    The stats lock that saving and counting take comes first, while
    signals still land, so a wait for it behind another copy of the game
    that doesn't let go can be broken off. Leaving then waits for it
    again, to save or count the game. After a SIGHUP or SIGTERM the
    command line lets another of either through only while it waits.
    """
    with _locked():
        if not hasattr(signal, "pthread_sigmask"):
            yield
            return
        old = signal.pthread_sigmask(signal.SIG_BLOCK, _LEAVING)
        try:
            yield
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)


def cut_short(name: str) -> None:
    """Tell of a game left neither saved nor counted, as Ctrl-C or a signal
    broke off the way out, say while it waited for the lock."""
    _notice(f"leaving was cut short, so your {name} game was neither saved nor counted")


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """Hold the stats lock while reading, changing and saving the stats.

    Two copies of the game finishing at once would otherwise both read the
    same stats and the later save would drop the other's result. The lock is
    advisory (flock on stats.lock beside stats.json) and does nothing where
    there is no fcntl, or when the lock file can't be made.
    """
    global _lock_depth, _waiting  # noqa: PLW0603 (state for this process)
    fd = None
    if _lock_depth == 0 and fcntl is not None:
        try:
            os.makedirs(data_dir(), exist_ok=True)
            # kept open while we hold the lock; the finally below closes it
            fd = os.open(os.path.join(data_dir(), "stats.lock"), os.O_WRONLY | os.O_CREAT, 0o600)
            with contextlib.suppress(OSError):
                os.fchmod(fd, 0o600)  # one an older version left open to others
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if _on_wait is not None:
                    # a note that can't be written, to a stderr that has
                    # closed, say, still waits for the lock
                    with contextlib.suppress(OSError, ValueError):
                        _on_wait()
                _waiting = True
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                finally:
                    _waiting = False
        except BaseException as exc:
            if fd is not None:
                os.close(fd)
            fd = None
            if not isinstance(exc, OSError):
                raise  # Ctrl-C while it waited
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        if fd is not None:
            os.close(fd)  # which also lets go of the lock


DEFAULT_CONFIG = {
    "last_game": "klondike",
    "symbols": True,
    "options": {},  # per-game option overrides, keyed by game key
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
        #   theme      - the colour theme ('t'); not camo_theme, the disguise
        #   four_color - green clubs and orange diamonds (the '4' toggle)
        #   code_skin  - play wrapped in source (the 'c' toggle)
        #   camo_theme - boss-mode disguise theme
        #   view       - board view: "expanded" cards or "legacy" cells
        #   animation  - cards move on their own: the finish and the win's cascade
        for key in ("color", "code_skin", "animation", "four_color"):
            if isinstance(data.get(key), bool):
                cfg[key] = data[key]
        if isinstance(data.get("camo_theme"), str):
            cfg["camo_theme"] = data["camo_theme"]
        # any name is kept: one from a newer version plays as classic here
        if isinstance(data.get("theme"), str):
            cfg["theme"] = data["theme"]
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
        # a copy loaded before the merge must not clear the flag
        cfg["merged_into_aisleriot"] = True
    return _write_json(config_path(), cfg)


def update_config(**changes: object) -> bool:
    """Save the settings in `changes` to config.json, and only those.

    The file is read again first and the rest of it kept as it is now: a
    hand edit made since the game started, what another copy of the game
    saved, or a key this version doesn't know. `options` gives the options
    of the games that change, and the other games keep theirs. As with
    save_config, a damaged file is set aside first and one that can't be
    read is left alone. Returns False if nothing was saved.
    """
    data = _read_json(config_path())
    if data is None:
        return False
    for key, value in changes.items():
        old = data.get(key)
        if key == "options" and isinstance(value, dict) and isinstance(old, dict):
            data[key] = {**old, **value}
        else:
            data[key] = value
    return _write_json(config_path(), data)


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
    return {
        k: v
        for k, v in val.items()
        if any(type(v) is type(a) and v == a for a in allowed.get(k, ()))
    }


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


def _norm(s: dict | None) -> dict:
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
    global _no_sync  # noqa: PLW0603 (state for this run)
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


def sharing_waits() -> bool:
    """True while sharing is on but AisleRiot has yet to be run and make the
    folder its keyfile goes in, so results wait here until it has."""
    return syncing() and not os.path.isdir(ar.gnome_games_dir())


def _unreadable_keyfile() -> None:
    _notice(
        f"can't read {ar.keyfile_path()}, so statistics are not shared "
        "with AisleRiot this time; they are kept here"
    )


def _unwritable_keyfile() -> None:
    if not os.path.isdir(ar.gnome_games_dir()):
        # AisleRiot hasn't been run yet. Nothing is wrong: the results wait
        # here until it has made its config.
        return
    _notice(
        f"couldn't write {ar.keyfile_path()}; results it is missing are "
        "kept here and added to it next time"
    )


def _unwritable_stats() -> None:
    _notice(
        f"couldn't write {stats_path()}, so that game is missing from the statistics kept there"
    )


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
        meta["unsynced"] = {**_foreign(meta.get("unsynced")), **waiting}
    stats[META_KEY] = meta
    if not save_stats(stats):
        _unwritable_stats()
    return updated


def _one_game(won: bool, seconds: float) -> dict:
    """A record of one finished game, to add to a stat with _combined().

    Best/Worst are winning times only, so a loss adds nothing to them."""
    secs = max(1, round(seconds)) if won else 0
    return {"wins": int(won), "total": 1, "best": secs, "worst": secs}


def _unsynced(stats: dict) -> dict[str, dict]:
    """Games recorded here that the keyfile hasn't been given yet, per game.

    They were played while we weren't sharing (sharing off, or the keyfile
    out of reach). Our own record of each game already counts them.
    """
    raw = _meta(stats).get("unsynced")
    if not isinstance(raw, dict):
        return {}
    out = {k: _norm(v) for k, v in raw.items() if k in ar.GAME_TO_SECTION}
    return {k: v for k, v in out.items() if v["total"] > 0}


def _foreign(unsynced: object) -> dict:
    """The entries of an unsynced list for games this version doesn't have.

    A newer version with more games put them there while it wasn't sharing.
    We can't share them, but they are kept as they are, so that version can
    once it is back.
    """
    if not isinstance(unsynced, dict):
        return {}
    return {k: v for k, v in unsynced.items() if k not in ar.GAME_TO_SECTION}


def _share(stats: dict, waiting: dict[str, dict], game_key: str) -> None:
    """Add the games in `waiting` to the keyfile, then save `stats` (whose
    own records already count them) with whatever didn't make it.

    They are taken off the unsynced list and saved before the keyfile is
    touched: if we stop half way, AisleRiot misses those games, which beats
    counting them twice.
    """
    meta = {**_meta(stats), "merged_into_aisleriot": True}
    foreign = _foreign(meta.pop("unsynced", None))
    if foreign:
        meta["unsynced"] = foreign
    stats[META_KEY] = meta
    if not save_stats(stats):
        # the others are still listed in the file on disk; sending them
        # now would send them again next time
        waiting = {game_key: waiting[game_key]} if game_key in waiting else {}
    left: dict[str, dict] = {}
    for key, games in waiting.items():
        ours = _norm(stats.get(key))

        def add(cur: dict | None, games: dict = games, ours: dict = ours) -> dict:
            # A game the keyfile has no record of (a fresh keyfile, or sol
            # saving its own copy over ours) starts from our record, which
            # counts these games already, rather than from nothing.
            return ours if cur is None else _combined(_norm(cur), games)

        written = ar.update_stat(ar.GAME_TO_SECTION[key], add)
        if written is None:
            left[key] = games
        else:
            stats[key] = written  # our copy follows the keyfile
    if left:
        _unwritable_keyfile()
        meta["unsynced"] = {**foreign, **left}
    if not save_stats(stats):
        _unwritable_stats()


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
    # (bar a newer version's games, which only it can share)
    meta = {**_meta(local), "merged_into_aisleriot": True}
    foreign = _foreign(meta.pop("unsynced", None))
    if foreign:
        meta["unsynced"] = foreign
    local[META_KEY] = meta
    if not save_stats(local):
        return
    update_config(merged_into_aisleriot=True)
    left: dict[str, dict] = {}
    for game_key, lstat in local.items():
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is None:
            continue
        ours = _norm(lstat)
        if ours["total"] == 0:
            continue

        def add(cur: dict | None, ours: dict = ours) -> dict:
            return _combined(_norm(cur), ours)

        if ar.update_stat(sect, add) is None:
            left[game_key] = ours
    if left:
        # what the keyfile didn't take waits with the other unshared games
        _unwritable_keyfile()
        meta["unsynced"] = {**foreign, **left}
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
    return any(get_stat(k)["total"] > 0 or _norm(local.get(k))["total"] > 0 for k in GAME_ORDER)


def backup_stats() -> list[str]:
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
        fin = open(src, "rb")  # noqa: SIM115 (the with below closes it)
    except FileNotFoundError:
        return False
    with fin:
        fd, tmp = tempfile.mkstemp(
            dir=os.path.dirname(dst), prefix=f".{os.path.basename(dst)}.", suffix=".tmp"
        )
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


def shared_record() -> bool:
    """True if AisleRiot has one of our games on record, for reset_stats()
    to clear there too. It may have none: not run yet, or run only for
    games we don't play."""
    if not syncing():
        return False
    try:
        return any(s["total"] > 0 for s in ar.all_known_stats().values())
    except OSError:
        return False  # unreadable, so reset_stats() leaves it as it is


def reset_stats() -> int | None:
    """Clear statistics for the games we manage. Returns how many were cleared.

    When syncing, each managed game's Statistic is zeroed in the shared keyfile
    too (other AisleRiot games and all non-Statistic keys are left untouched).
    Local JSON is cleared first, and if it can't be written nothing is
    cleared: None is returned, with a notice. Otherwise returns the count of
    games that had a record.
    """
    with _locked():
        return _reset_stats()


def _reset_stats() -> int | None:
    from .engine import GAME_ORDER  # local import to avoid a cycle at module load

    stats = load_stats()
    # stats.json goes first, so that if it can't be cleared nothing is
    meta = dict(_meta(stats))
    meta.pop("unsynced", None)  # games not yet shared are cleared too
    if not save_stats({META_KEY: meta}):
        _notice(f"couldn't write {stats_path()}, so nothing was cleared")
        return None
    cleared = 0
    if _can_sync():
        for game_key in GAME_ORDER:
            sect = ar.GAME_TO_SECTION.get(game_key)
            if sect is None:
                continue
            played: list[bool] = []

            def clear(cur: dict | None) -> dict | None:
                # update_stat calls this before the loop moves on
                played.append(bool(cur and cur.get("total", 0) > 0))  # noqa: B023
                return dict(EMPTY_STAT) if cur is not None else None

            if ar.update_stat(sect, clear) is None and played and played[-1]:
                _notice(
                    f"couldn't write {ar.keyfile_path()}, so AisleRiot "
                    "still has some of the statistics cleared here"
                )
            # ours may have games the keyfile hasn't been given yet
            if (played and played[-1]) or _norm(stats.get(game_key))["total"] > 0:
                cleared += 1
    else:
        cleared = sum(1 for k in GAME_ORDER if _norm(stats.get(k))["total"] > 0)
    return cleared


def percentage(stat: dict) -> float | None:
    if stat["total"] <= 0:
        return None
    return 100.0 * stat["wins"] / stat["total"]


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:d}:{seconds % 60:02d}"


def moves_text(n: int) -> str:
    """A count of moves as it reads in a sentence: 1 move, 2 moves."""
    return "1 move" if n == 1 else f"{n} moves"
