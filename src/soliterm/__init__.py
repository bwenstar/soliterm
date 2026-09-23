"""Soliterm: solitaire for your terminal, AisleRiot-compatible.

Nine solitaire games with a curses TUI (keyboard and mouse) and a
pipe-friendly text mode. The engine follows GNOME AisleRiot's model and
rules, and statistics are shared with an installed AisleRiot through its
keyfile. The runtime is standard library only.

Modules:
  engine     the slot/card engine and the nine games
  cli        argument parsing, the text mode, and the entry point (main)
  tui        the curses front-end
  store      config and statistics under the XDG directories
  aisleriot  reads and writes GNOME AisleRiot's statistics keyfile
  camo       boss-mode and code-skin text
"""

__version__ = "1.0.0.dev0"

# The product name as players see it (titles, banners, --version).
APP_NAME = "Soliterm"
