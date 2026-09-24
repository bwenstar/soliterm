"""The game registry: every game by key, the menu order, and new_solitaire()."""

from __future__ import annotations

from ..core import Solitaire
from ..gamedef import GameDef
from .bakersdozen import BakersDozen
from .canfield import Canfield
from .eightoff import EightOff
from .fortythieves import FortyThieves
from .freecell import FreeCell
from .golf import Golf
from .klondike import Klondike
from .spider import Spider
from .yukon import Yukon

GAMES: dict[str, type[GameDef]] = {
    cls.key: cls
    for cls in [
        Klondike,
        Spider,
        FreeCell,
        EightOff,
        Golf,
        Yukon,
        BakersDozen,
        FortyThieves,
        Canfield,
    ]
}

GAME_ORDER = [
    "klondike",
    "spider",
    "freecell",
    "eightoff",
    "golf",
    "yukon",
    "bakersdozen",
    "fortythieves",
    "canfield",
]


def new_solitaire(key: str, seed: int | None = None, options: dict | None = None) -> Solitaire:
    return Solitaire(GAMES[key](), seed=seed, options=options)
