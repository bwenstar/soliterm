"""soliterm.saves - the unfinished games, one of each kind, waiting in the
saves folder for next time."""

from __future__ import annotations

import os

from . import __version__, engine, history, store
from .engine import GAMES, Solitaire

SAVE_FORMAT = 1
SAVED_STEPS = 500  # undo and redo steps kept with a game, each way
SAVE_MAX_BYTES = 4_000_000

# What _read() gives for a save this version must neither use nor write over.
LEFT_ALONE = object()

# The games this run put in the folder and hasn't taken out again
_kept: list[str] = []

# The games this copy took up from the folder and has in play, each with
# the fd that holds its lock, until it's kept again or counted
_playing: dict[str, int] = {}


def kept() -> list[str]:
    """The keys of the games this run saved that are still waiting, in the
    order they were saved, for the way out to say where they went."""
    return list(_kept)


def saves_dir() -> str:
    return os.path.join(store.data_dir(), "saves")


def save_path(key: str) -> str:
    return os.path.join(saves_dir(), f"{key}.json")


def in_play_path(key: str) -> str:
    """Where a save goes while the game is in play: a name 1.0 never reads,
    so it neither offers the game nor sets it aside meanwhile."""
    return os.path.join(saves_dir(), f"{key}.in-play.json")


def _lock_path(key: str) -> str:
    return os.path.join(saves_dir(), f"{key}.lock")


def keep(g: Solitaire, seconds: float) -> bool:
    """Put g in the saves folder for next time.

    False, with a notice saying why, if a game of its kind is already
    waiting or the save can't be written.
    """
    key = g.gamedef.key
    path = save_path(key)
    name = GAMES[key].name
    with store._locked():
        if _settle(key):
            store._notice(
                f"a saved {name} game is being played somewhere else, so this one counted as lost"
            )
            return False
        there = _read(key)
        if there is LEFT_ALONE:
            return False
        if there is not None:
            store._notice(f"a saved {name} game was already waiting, so this one counted as lost")
            return False
        save = {
            "format": SAVE_FORMAT,
            "version": __version__,
            "saved": history.now(),
            "seconds": int(seconds),
            **g.snapshot(SAVED_STEPS),
        }
        if store._write_json(path, save):
            _kept.append(key)
            let_go(key)  # the save it was taken up from, now the new one is there
            return True
    store._notice(f"couldn't save your {name} game to {path}, so it counts as lost")
    return False


def take(key: str) -> tuple[Solitaire, int] | None:
    """The game waiting for `key` and its seconds so far, or None.

    The save goes to its in-play name and the game's lock is held until
    the game is kept again or counted (let_go), so no other copy of the
    game plays it meanwhile, and yet it comes back, as it was when taken
    up, if this copy goes without doing either. Where the lock can't be
    had at all, the save just comes out of the folder. One that doesn't fit
    its game is set aside as damaged.
    """
    path = save_path(key)
    if not os.path.exists(path) and not os.path.exists(in_play_path(key)):
        return None
    with store._locked():
        if _settle(key):
            return None
        save = _read(key)
        if not isinstance(save, dict):
            return None
        try:
            g = engine.resume_solitaire(save)
        except ValueError:
            store._set_aside(path)
            return None
        fd = None
        try:
            try:
                fd = store._lock_file(_lock_path(key))
            except OSError:
                # no lock to be had, as on a file system without them: it
                # comes out of the folder as 1.0 took it, so it can't be
                # played twice, though a crash then loses it
                os.remove(path)
            else:
                if fd is None:
                    return None  # another copy has just taken it up
                os.replace(path, in_play_path(key))
        except OSError as exc:
            if fd is not None:
                store._let_go(fd)
            store._notice(
                f"can't take {path} out of the saves folder ({exc.strerror or exc}), "
                "so it is left there and a new hand dealt"
            )
            return None
        if fd is not None:
            _playing[key] = fd
    if key in _kept:
        _kept.remove(key)
    return g, save["seconds"]


def let_go(key: str) -> None:
    """Take the save this copy took up for `key` out of the folder for good,
    and let go of the game's lock: for a game kept again, counted, or dealt
    again from the start. Nothing to do for a game that wasn't taken up.

    It goes before the game is counted, so a crash between the two can
    lose that game but never count it twice.
    """
    if key not in _playing:
        return
    with store.signals_held():
        fd = _playing.pop(key)
        path = in_play_path(key)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            store._notice(
                f"can't take {path} out of the saves folder ({exc.strerror or exc}), "
                "so the game in it may be offered again"
            )
        finally:
            store._let_go(fd)


def elsewhere(key: str) -> bool:
    """Whether another copy of the game is playing a game of key's kind it
    took up, which leaves no room to keep one here."""
    if not os.path.exists(in_play_path(key)):
        return False
    with store._locked():
        return _settle(key)


def _settle(key: str) -> bool:
    """Put back a save left in play by a copy of the game that has gone, as
    by a crash or a closed window, with the stats lock held. True, with
    nothing touched, if the copy playing it is still there.

    A save waiting beside it was kept since, so it's newer and stays.
    """
    in_play = in_play_path(key)
    if key in _playing or not os.path.exists(in_play):
        return False
    try:
        fd = store._lock_file(_lock_path(key))
    except OSError:
        fd = None  # then there's no knowing, so it's left alone
    if fd is None:
        return True
    path = save_path(key)
    try:
        if os.path.exists(path):
            os.remove(in_play)
        else:
            os.replace(in_play, path)
    except OSError as exc:
        store._notice(
            f"can't put {in_play} back as {path} ({exc.strerror or exc}), so it is left where it is"
        )
    finally:
        store._let_go(fd)
    return False


def waiting(*keys: str) -> dict[str, dict]:
    """The games waiting, for the menu: {"klondike": {"seconds": 42, "moves": 31}},
    plus "daily": "2026-09-24" for a daily deal.

    Given keys, only their saves are read, so a damaged save of another
    game isn't set aside, or told of, on the way.
    """
    if not os.path.isdir(saves_dir()):
        return {}
    found = {}
    with store._locked():
        for key in keys or GAMES:
            if _settle(key):
                continue  # in play somewhere else
            save = _read(key)
            if isinstance(save, dict):
                found[key] = {"seconds": save["seconds"], "moves": save["moves"]}
                if engine.is_day(save.get("daily")):
                    found[key]["daily"] = save["daily"]
    return found


def _read(key: str) -> object:
    """The save waiting for `key` as a dict, None if there is none to play,
    or LEFT_ALONE if it must stay as it is (unreadable, or from a newer
    version). The deep checks are resume_solitaire's.
    """
    path = save_path(key)
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if size > SAVE_MAX_BYTES:
        return _damaged(path)
    save = store._read_json(path)
    if save is None:
        return LEFT_ALONE
    if not save and not os.path.exists(path):
        return None  # none there, or it was set aside; a {} has no fields
    fmt = save.get("format")
    if type(fmt) is int and fmt > SAVE_FORMAT:
        store._notice(
            f"{path} was saved by a newer Soliterm, so it is left alone "
            f"and a {GAMES[key].name} game left unfinished counts as lost"
        )
        return LEFT_ALONE
    counts = [save.get(name) for name in ("seconds", "moves", "score")]
    if (
        type(fmt) is int
        and fmt >= 1
        and save.get("game") == key
        and all(type(n) is int and n >= 0 for n in counts)
    ):
        return save
    return _damaged(path)


def _damaged(path: str) -> object:
    """Set a damaged save aside: None, or LEFT_ALONE if it can't be moved."""
    return None if store._set_aside(path) else LEFT_ALONE
