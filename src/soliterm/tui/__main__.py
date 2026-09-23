"""Lets `python -m soliterm.tui` start the game, the same way as soliterm."""

import sys

# tui is the curses view, not the entry point: the launcher (cli) sets up
# config, colour, stats sharing, and text-mode fallback. Defer to it so there
# is one supported way to start the game.
from ..cli import main

if __name__ == "__main__":
    sys.exit(main())
