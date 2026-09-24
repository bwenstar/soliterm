"""The game registry: every game by key, the menu order, new_solitaire()
and resume_solitaire()."""

from __future__ import annotations

from datetime import date

from ..core import MAX_DEAL, Solitaire
from ..gamedef import GameDef
from .bakersdozen import BakersDozen
from .canfield import Canfield
from .eightoff import EightOff
from .fortythieves import FortyThieves
from .freecell import FreeCell
from .golf import Golf
from .klondike import Klondike
from .scorpion import Scorpion
from .spider import Spider
from .spiderette import Spiderette
from .triplepeaks import TriplePeaks
from .yukon import Yukon

GAMES: dict[str, type[GameDef]] = {
    cls.key: cls
    for cls in [
        Klondike,
        Spider,
        Spiderette,
        FreeCell,
        EightOff,
        Golf,
        TriplePeaks,
        Yukon,
        Scorpion,
        BakersDozen,
        FortyThieves,
        Canfield,
    ]
}

GAME_ORDER = [
    "klondike",
    "spider",
    "spiderette",
    "freecell",
    "eightoff",
    "golf",
    "triplepeaks",
    "yukon",
    "scorpion",
    "bakersdozen",
    "fortythieves",
    "canfield",
]


def new_solitaire(key: str, seed: int | None = None, options: dict | None = None) -> Solitaire:
    return Solitaire(GAMES[key](), seed=seed, options=options)


def _is_day(text: object) -> bool:
    """Whether `text` is a day written the way date.isoformat() writes it."""
    try:
        return isinstance(text, str) and date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def resume_solitaire(snap: dict) -> Solitaire:
    """The game a Solitaire.snapshot() was taken of, ready to play on.

    Each position in it (the board and every undo and redo step) is checked
    against a fresh deal of the same hand: same slots, same cards. Raises
    ValueError if anything doesn't fit.
    """
    key, opts, deal = snap.get("game"), snap.get("options"), snap.get("deal")
    if not isinstance(key, str) or key not in GAMES:
        raise ValueError(f"{key!r} doesn't fit any game here")
    clean = GAMES[key].sanitize_options(opts if isinstance(opts, dict) else None)
    # every option saved must be one the game still allows, type and all
    if not isinstance(opts, dict) or any(
        k not in clean or (type(v), v) != (type(clean[k]), clean[k]) for k, v in opts.items()
    ):
        raise ValueError(f"the options {opts!r} don't fit {key}")
    if type(deal) is not int or not 0 <= deal <= MAX_DEAL:
        raise ValueError(f"the deal {deal!r} doesn't fit, as deals run from 0 to {MAX_DEAL}")
    daily = snap.get("daily")  # missing from saves made before the daily deal
    if daily is not None and not _is_day(daily):
        raise ValueError(f"the daily {daily!r} doesn't fit, as it isn't a day like 2026-09-24")
    position, undo, redo = snap.get("position"), snap.get("undo"), snap.get("redo")
    if not (
        isinstance(position, str)
        and isinstance(undo, list)
        and isinstance(redo, list)
        and all(isinstance(t, str) for t in undo + redo)
    ):
        raise ValueError("the positions don't fit, as they aren't all text")
    g = new_solitaire(key, seed=deal, options=clean)
    for text in (position, *undo, *redo):
        g._check_position(text)
    g._restore(position)
    g._undo = [t.encode() for t in undo]
    g._redo = [t.encode() for t in redo]
    g.daily = daily
    g.seed = None  # n deals at random from here, not the number after
    return g
