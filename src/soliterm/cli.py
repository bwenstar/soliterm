"""soliterm.cli - the command line: argument parsing and dispatch.

  soliterm                              # curses TUI (menu, keyboard + mouse)
  soliterm --game freecell              # jump straight into a game
  soliterm --list                       # list the games
  soliterm --stats                      # print statistics and exit
  soliterm --text --game golf --seed 1  # scriptable text mode

`python -m soliterm` does the same without the console script.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from . import APP_NAME, __version__, engine, migrate, store
from . import aisleriot as ar
from .engine import GAME_ORDER, GAMES
from .textmode import run_text


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False: a prefix like --r must not mean --reset-stats
    p = argparse.ArgumentParser(
        prog="soliterm",
        description=f"{APP_NAME}: solitaire for your terminal, AisleRiot-compatible.",
        allow_abbrev=False,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--game", choices=GAME_ORDER, default=None,
                   help="game to start (default: menu in the TUI)")
    p.add_argument("--seed", type=int, default=None, help="reproducible shuffle")
    p.add_argument("--text", action="store_true",
                   help="force text mode (no curses); reads commands from stdin")
    p.add_argument("--ascii", action="store_true",
                   help="letter suits (S/H/D/C) instead of unicode symbols")
    p.add_argument("--color", dest="color", action="store_true", default=None,
                   help="force coloured suits in text mode (red/black on white)")
    p.add_argument("--no-color", dest="color", action="store_false",
                   help="disable coloured output")
    once = p.add_mutually_exclusive_group()
    once.add_argument("--list", action="store_true", help="list the games and exit")
    once.add_argument("--stats", action="store_true", help="print statistics and exit")
    once.add_argument("--reset-stats", action="store_true",
                      help="erase the statistics of every game, AisleRiot's own "
                           "record of them included, and exit; asks first and "
                           "keeps a backup")
    p.add_argument("--yes", action="store_true",
                   help="with --reset-stats: don't ask first")
    p.add_argument("--no-sync", action="store_true",
                   help="leave GNOME AisleRiot's statistics alone this time and "
                        "keep them here only (also SOLITERM_NO_AISLERIOT=1)")
    return p


def print_list() -> None:
    print("Games:")
    for key in GAME_ORDER:
        cls = GAMES[key]
        print(f"  {key:<14} {cls.name:<16} {cls.blurb}")


def print_stats() -> None:
    print(f"{'Game':<16}{'Wins':>6}{'Total':>7}{'Win%':>7}{'Best':>8}{'Worst':>8}")
    for key in GAME_ORDER:
        s = store.get_stat(key)
        pct = store.percentage(s)
        pcts = "N/A" if pct is None else f"{pct:.0f}%"
        best = "N/A" if s["best"] == 0 else store.fmt_time(s["best"])
        worst = "N/A" if s["worst"] == 0 else store.fmt_time(s["worst"])
        print(f"{GAMES[key].name:<16}{s['wins']:>6}{s['total']:>7}"
              f"{pcts:>7}{best:>8}{worst:>8}")


def reset_stats(yes: bool) -> int:
    """--reset-stats: check with the player, back up, then clear."""
    if not store.any_stats():
        print("There are no statistics to clear.")
        return 0
    sharing = store.syncing()
    if not yes:
        if not sys.stdin.isatty():
            print("soliterm: --reset-stats asks before it erases anything; "
                  "add --yes to clear the statistics without asking",
                  file=sys.stderr)
            return 2
        where = (f", here and in GNOME AisleRiot ({ar.keyfile_path()})"
                 if sharing else "")
        print(f"This erases the statistics of all {len(GAME_ORDER)} games{where}.",
              file=sys.stderr)
        print("Type yes to clear them: ", end="", file=sys.stderr, flush=True)
        try:
            answer = sys.stdin.readline()
        except KeyboardInterrupt:
            answer = ""
        if not answer.endswith("\n"):
            print(file=sys.stderr)      # Ctrl-D or Ctrl-C left the line open
        if answer.strip().lower() != "yes":
            print("Nothing was cleared.")
            return 1
    try:
        backups = store.backup_stats()
    except OSError as exc:
        print(f"soliterm: couldn't back up the statistics ({exc}), "
              "so nothing was cleared", file=sys.stderr)
        return 1
    for path in backups:
        print(f"Backup saved to {path}")
    n = store.reset_stats()
    if sharing:
        print(f"Statistics cleared for {n} game(s) "
              "(shared with GNOME AisleRiot).")
    else:
        print("Statistics cleared.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # before anything reads the config or the stats
    migrate.ensure()
    if args.no_sync:
        store.disable_sync()
    try:
        return _run(args)
    finally:
        # anything that kept the stats from being shared or saved as usual
        for msg in store.notices():
            print(f"soliterm: {msg}", file=sys.stderr)


def _run(args: argparse.Namespace) -> int:
    if args.list:
        print_list(); return 0
    if args.reset_stats:
        return reset_stats(args.yes)
    if args.stats:
        print_stats(); return 0

    cfg = store.load_config()
    symbols = cfg.get("symbols", True) and not args.ascii

    # Colour (both the curses TUI and text mode): explicit --color/--no-color
    # wins; otherwise on unless NO_COLOR is set (https://no-color.org). The TTY
    # check only applies to text mode - the TUI is always on a terminal.
    if args.color is None:
        color = not os.environ.get("NO_COLOR")
        text_color = color and sys.stdout.isatty()
    else:
        color = text_color = args.color

    use_curses = not args.text and sys.stdout.isatty() and sys.stdin.isatty()
    if use_curses:
        try:
            import curses  # noqa: F401
            from . import tui
        except Exception:
            use_curses = False

    if use_curses:
        from . import tui
        return tui.main(start_key=args.game, seed=args.seed, color=color)

    # text mode
    key = args.game or cfg.get("last_game", "klondike")
    opts = {**GAMES[key].default_options(), **store.game_options(cfg, key)}
    g = engine.new_solitaire(key, seed=args.seed, options=opts)
    return run_text(g, symbols, key, color=text_color)


if __name__ == "__main__":
    sys.exit(main())
