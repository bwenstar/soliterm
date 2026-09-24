"""soliterm.engine - Solitaire for your terminal, AisleRiot-compatible.

AisleRiot is a collection of solitaire card games sharing one engine: a set of
"slots" holding cards, and per-game rule modules that answer a handful of
callbacks (can you pick up this run? can it land there? what does a click do?
is there a hint? has the game been won?). This package mirrors that design.

Reimplemented from the rules/feature set of GNOME AisleRiot (the engine model,
the games' rules, the statistics dialog). No GPL source code is copied.

  cards    Card, make_deck and the suit and rank constants
  core     Slot and Solitaire, the game state every front-end drives
  gamedef  GameDef, the base class for a game's rules, and its helpers
  games    one module per game, plus the GAMES registry, new_solitaire()
           and resume_solitaire()
  rng      the shuffle behind every deal, and Microsoft FreeCell's deals

Everything the front-ends need is importable straight from soliterm.engine.
"""

from .cards import ACE, JACK, KING, QUEEN, RANK_NAME, RED_SUITS, SUIT_SYMBOL, SUITS, Card, make_deck
from .core import MAX_DEAL, RANDOM_DEALS, Slot, Solitaire
from .gamedef import GameDef
from .games import GAME_ORDER, GAMES, is_day, new_solitaire, resume_solitaire
from .games.bakersdozen import BakersDozen
from .games.canfield import Canfield
from .games.eightoff import EightOff
from .games.fortythieves import FortyThieves
from .games.freecell import FreeCell
from .games.golf import Golf
from .games.klondike import Klondike
from .games.scorpion import Scorpion
from .games.spider import Spider
from .games.spiderette import Spiderette
from .games.triplepeaks import TriplePeaks
from .games.yukon import Yukon

__all__ = [
    "ACE",
    "GAMES",
    "GAME_ORDER",
    "JACK",
    "KING",
    "MAX_DEAL",
    "QUEEN",
    "RANDOM_DEALS",
    "RANK_NAME",
    "RED_SUITS",
    "SUITS",
    "SUIT_SYMBOL",
    "BakersDozen",
    "Canfield",
    "Card",
    "EightOff",
    "FortyThieves",
    "FreeCell",
    "GameDef",
    "Golf",
    "Klondike",
    "Scorpion",
    "Slot",
    "Solitaire",
    "Spider",
    "Spiderette",
    "TriplePeaks",
    "Yukon",
    "is_day",
    "make_deck",
    "new_solitaire",
    "resume_solitaire",
]
