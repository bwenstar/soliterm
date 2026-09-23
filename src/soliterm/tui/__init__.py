"""soliterm.tui - the curses front-end (keyboard + mouse).

board draws the cards and keeps the hit map clicks go through; app runs the
menu, the dialogs and the play loop on top of it. cli.py only needs main().
"""

from .app import main, run
from .board import MAX_CARD_W, MIN_CARD_W, BoardUI

__all__ = ["BoardUI", "MAX_CARD_W", "MIN_CARD_W", "main", "run"]
