"""Soliterm: solitaire for your terminal, AisleRiot-compatible.

Thirteen solitaire games with a curses TUI (keyboard and mouse) and a
pipe-friendly text mode. The engine follows GNOME AisleRiot's model and
rules, and statistics are shared with an installed AisleRiot through its
keyfile. The runtime is standard library only, apart from windows-curses
on Windows, where CPython ships no curses module.

Modules:
  engine     the slot/card engine; engine.games holds one module per game
  cli        argument parsing and the entry point (main)
  textmode   the pipe-friendly text mode (plain board, command loop)
  tui        the curses front-end
  store      config and statistics under the XDG directories
  saves      unfinished games kept for next time
  history    every game counted, for streaks and recent games
  aisleriot  reads and writes GNOME AisleRiot's statistics keyfile
  camo       boss-mode and code-skin text
"""

__version__ = "1.1.0"

# The product name as players see it (titles, banners, --help).
APP_NAME = "Soliterm"
