"""soliterm.tui - the curses front-end (keyboard + mouse).

board draws the cards and keeps the hit map clicks go through, keys is the
table of what each key does, and app runs the menu, the dialogs and the play
loop on top of them. cli.py only needs main().
"""

from .app import App, main, run
from .board import MAX_CARD_W, MIN_CARD_W, BoardUI
from .keys import KEYMAP

__all__ = ["KEYMAP", "MAX_CARD_W", "MIN_CARD_W", "App", "BoardUI", "main", "run"]
