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


def saves_dir() -> str:
    return os.path.join(store.data_dir(), "saves")


def save_path(key: str) -> str:
    return os.path.join(saves_dir(), f"{key}.json")


def keep(g: Solitaire, seconds: float) -> bool:
    """Put g in the saves folder for next time.

    False, with a notice saying why, if a game of its kind is already
    waiting or the save can't be written.
    """
    key = g.gamedef.key
    path = save_path(key)
    with store._locked():
        there = _read(key)
        if there is LEFT_ALONE:
            return False
        if there is not None:
            store._notice(
                f"a saved {GAMES[key].name} game was already waiting, so this one counted as lost"
            )
            return False
        save = {
            "format": SAVE_FORMAT,
            "version": __version__,
            "saved": history.now(),
            "seconds": int(seconds),
            **g.snapshot(SAVED_STEPS),
        }
        if store._write_json(path, save):
            return True
    store._notice(f"couldn't save your {GAMES[key].name} game to {path}, so it counts as lost")
    return False


def take(key: str) -> tuple[Solitaire, int] | None:
    """The game waiting for `key` and its seconds so far, or None.

    The save comes out of the folder, so it can't be played twice. One that
    doesn't fit its game is set aside as damaged.
    """
    path = save_path(key)
    if not os.path.exists(path):
        return None
    with store._locked():
        save = _read(key)
        if not isinstance(save, dict):
            return None
        try:
            g = engine.resume_solitaire(save)
        except ValueError:
            store._set_aside(path)
            return None
        try:
            os.remove(path)
        except OSError as exc:
            store._notice(
                f"can't take {path} out of the saves folder ({exc.strerror or exc}), "
                "so it is left there and a new hand dealt"
            )
            return None
    return g, save["seconds"]


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
