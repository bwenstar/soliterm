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
import functools
import os
import sys
from typing import Any, Callable

from . import APP_NAME, __version__, debuginfo, engine, migrate, store
from . import aisleriot as ar
from .engine import GAME_ORDER, GAMES
from .textmode import run_text

# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def seed_arg(text: str) -> int:
    """--seed: a whole number from 0 up (the engine refuses negative seeds)."""
    try:
        seed = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid seed: {text!r}") from None
    if seed < 0:
        raise argparse.ArgumentTypeError(f"seed must be 0 or more, not {seed}")
    return seed


def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False: a prefix like --r must not mean --reset-stats
    p = argparse.ArgumentParser(
        prog="soliterm",
        description=f"{APP_NAME}: solitaire for your terminal, AisleRiot-compatible.",
        allow_abbrev=False,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--game", choices=GAME_ORDER, default=None, help="game to start (default: menu in the TUI)"
    )
    p.add_argument(
        "--seed",
        type=seed_arg,
        default=None,
        metavar="N",
        help="reproducible shuffle (N is 0 or more)",
    )
    p.add_argument(
        "--text", action="store_true", help="force text mode (no curses); reads commands from stdin"
    )
    p.add_argument(
        "--ascii", action="store_true", help="letter suits (S/H/D/C) instead of unicode symbols"
    )
    p.add_argument(
        "--color",
        dest="color",
        action="store_true",
        default=None,
        help="force coloured suits in text mode (red/black on white)",
    )
    p.add_argument("--no-color", dest="color", action="store_false", help="disable coloured output")
    once = p.add_mutually_exclusive_group()
    once.add_argument("--list", action="store_true", help="list the games and exit")
    once.add_argument("--stats", action="store_true", help="print statistics and exit")
    once.add_argument(
        "--reset-stats",
        action="store_true",
        help="erase the statistics of every game, AisleRiot's own "
        "record of them included, and exit; asks first and "
        "keeps a backup",
    )
    once.add_argument(
        "--debug-info", action="store_true", help="print what a bug report needs and exit"
    )
    p.add_argument("--yes", action="store_true", help="with --reset-stats: don't ask first")
    p.add_argument(
        "--no-sync",
        action="store_true",
        help="leave GNOME AisleRiot's statistics alone this time and "
        "keep them here only (also SOLITERM_NO_AISLERIOT=1)",
    )
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
        print(f"{GAMES[key].name:<16}{s['wins']:>6}{s['total']:>7}{pcts:>7}{best:>8}{worst:>8}")


def reset_stats(yes: bool) -> int:
    """--reset-stats: check with the player, back up, then clear."""
    if not store.any_stats():
        print("There are no statistics to clear.")
        return 0
    sharing = store.syncing()
    if not yes:
        if not sys.stdin.isatty():
            print(
                "soliterm: --reset-stats asks before it erases anything; "
                "add --yes to clear the statistics without asking",
                file=sys.stderr,
            )
            return 2
        where = f", here and in GNOME AisleRiot ({ar.keyfile_path()})" if sharing else ""
        print(f"This erases the statistics of all {len(GAME_ORDER)} games{where}.", file=sys.stderr)
        print("Type yes to clear them: ", end="", file=sys.stderr, flush=True)
        try:
            answer = sys.stdin.readline()
        except KeyboardInterrupt:
            answer = ""
        if not answer.endswith("\n"):
            print(file=sys.stderr)  # Ctrl-D or Ctrl-C left the line open
        if answer.strip().lower() != "yes":
            print("Nothing was cleared.")
            return 1
    try:
        backups = store.backup_stats()
    except OSError as exc:
        print(
            f"soliterm: couldn't back up the statistics ({exc}), so nothing was cleared",
            file=sys.stderr,
        )
        return 1
    for path in backups:
        print(f"Backup saved to {path}")
    n = store.reset_stats()
    if sharing:
        print(f"Statistics cleared for {n} game(s) (shared with GNOME AisleRiot).")
    else:
        print("Statistics cleared.")
    return 0


def _load_tui() -> tuple[Any, str]:
    """The curses front end, or None and a line on why text mode it is.

    Text mode it is when a module isn't there (curses on a Windows Python,
    say, or one left out of a package) or curses can't draw on this
    terminal. Any other error in the front end is a bug and is raised, not
    hidden behind text mode.
    """
    try:
        from . import tui
    except ImportError as exc:
        why = f"can't load the full-screen game ({exc}), so playing in text mode"
        if os.name == "nt" and exc.name in ("curses", "_curses"):
            why += "; pip install windows-curses adds curses to Python on Windows"
        return None, why
    problem = _terminal_problem()
    if problem:
        return None, problem
    return tui, ""


def _terminal_problem() -> str | None:
    """Why curses can't draw the game on this terminal, or None if it can.

    Asked before the game starts: on a terminal type it doesn't know, or
    one that can't move the cursor, curses gives up with an error where
    text mode would have done.
    """
    if os.name == "nt":
        return None  # the Windows console needs no TERM
    import curses

    term = os.environ.get("TERM", "")
    rest = (
        "so playing in text mode; set TERM to your terminal's type "
        "(xterm-256color suits most) for the full-screen game"
    )
    if not term:
        return f"TERM isn't set, {rest}"
    if term == "dumb":
        return f"TERM=dumb can't move the cursor, {rest}"
    try:
        # fd 1, which curses draws on whatever sys.stdout is
        curses.setupterm(term, 1)
    except curses.error:
        return f"TERM={term} isn't a terminal type known here, {rest}"
    if not curses.tigetstr("cup"):
        return f"TERM={term} can't move the cursor, {rest}"
    return None


def _quiet_on_broken_pipe(main: Callable[..., int]) -> Callable[..., int]:
    """End quietly when whoever reads our output stops reading.

    Output piped into head, or a pager quit early, closes the pipe: the next
    write raises BrokenPipeError, and so does Python's own flush at exit.
    Pointing stdout at devnull leaves that last flush nowhere to fail.
    """

    @functools.wraps(main)
    def run(*args, **kwargs) -> int:
        try:
            rc = main(*args, **kwargs)
            sys.stdout.flush()  # so a late EPIPE comes up here
            return rc
        except BrokenPipeError:
            try:
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            except (OSError, ValueError):
                pass
            return 141  # what a shell shows for SIGPIPE

    return run


@_quiet_on_broken_pipe
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.debug_info:
        # before the migration, so the report writes, moves and copies nothing
        print(debuginfo.text(args.no_sync, sys.stdout.encoding))
        return 0
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
        print_list()
        return 0
    if args.reset_stats:
        return reset_stats(args.yes)
    if args.stats:
        print_stats()
        return 0

    cfg = store.load_config()
    symbols = cfg.get("symbols", True) and not args.ascii

    # Colour in text mode: explicit --color/--no-color wins; otherwise on
    # unless NO_COLOR is set (https://no-color.org) or stdout isn't a TTY.
    # The TUI gets the bare flag, since it also has the colour saved with v.
    if args.color is None:
        color = not os.environ.get("NO_COLOR")
        text_color = color and sys.stdout.isatty()
    else:
        color = text_color = args.color

    if not args.text and sys.stdout.isatty() and sys.stdin.isatty():
        tui, why = _load_tui()
        if tui is not None:
            return tui.main(args.game, seed=args.seed, color=args.color, symbols=symbols)
        print(f"soliterm: {why}", file=sys.stderr)

    # text mode
    key = args.game or cfg.get("last_game", "klondike")
    opts = {**GAMES[key].default_options(), **store.game_options(cfg, key)}
    g = engine.new_solitaire(key, seed=args.seed, options=opts)
    return run_text(g, symbols, key, color=text_color, camo_theme=cfg.get("camo_theme"))


if __name__ == "__main__":
    sys.exit(main())
