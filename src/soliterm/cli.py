"""soliterm.cli - the command line: argument parsing and dispatch.

  soliterm                              # curses TUI (menu, keyboard + mouse)
  soliterm --game freecell              # jump straight into a game
  soliterm --list                       # list the games
  soliterm --stats                      # print statistics and exit
  soliterm --text --game golf --deal 1  # scriptable text mode

`python -m soliterm` does the same without the console script.
"""

from __future__ import annotations

import argparse
import errno
import functools
import os
import signal
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Callable

from . import APP_NAME, __version__, deals, debuginfo, history, migrate, saves, store, themes
from . import aisleriot as ar
from .engine import GAME_ORDER, GAMES
from .textmode import run_text

# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def deal_arg(text: str) -> deals.Code:
    """--deal and --seed: a deal number or a share code."""
    try:
        return deals.parse(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _owner(name: str) -> str:
    """The one game with option `name`, which --draw or --suits then picks."""
    (key,) = [k for k in GAME_ORDER if name in GAMES[k].default_options()]
    return key


def _values(key: str, name: str) -> list:
    """The values option `name` of game `key` takes."""
    return next(allowed for k, _, allowed in GAMES[key].option_spec() if k == name)


def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False: a prefix like --r must not mean --reset-stats
    p = argparse.ArgumentParser(
        prog="soliterm",
        description=f"{APP_NAME}: solitaire for your terminal, AisleRiot-compatible.",
        allow_abbrev=False,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--game",
        choices=GAME_ORDER,
        default=None,
        metavar="GAME",
        help="game to start, as --list names it (default: menu in the TUI)",
    )
    which = p.add_mutually_exclusive_group()
    which.add_argument(
        "--deal",
        type=deal_arg,
        metavar="N|CODE",
        help="play deal N, or the deal a share code names, such as klondike:d3:48213",
    )
    which.add_argument(
        "--daily", action="store_true", help="play today's daily deal, the same for everyone"
    )
    # what --deal was called in aisle-cli; not in the help, but it still works.
    # It stays out of the group, since a hidden option in one is where
    # argparse's usage line has broken before, so _requested_deal checks it.
    p.add_argument("--seed", type=deal_arg, help=argparse.SUPPRESS)
    draws, suits = _values("klondike", "draw"), _values("spider", "suits")
    p.add_argument(
        "--draw",
        type=int,
        choices=draws,
        metavar="|".join(map(str, draws)),
        help="Klondike: draw 1 or 3 cards, for this run only",
    )
    p.add_argument(
        "--suits",
        type=int,
        choices=suits,
        metavar="|".join(map(str, suits)),
        help="Spider: play with 1, 2 or 4 suits, for this run only",
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
    p.add_argument(
        "--theme",
        choices=themes.NAMES,
        help="colour theme for this run (t switches and keeps one)",
    )
    p.add_argument(
        "--no-animation", action="store_true", help="finish and win without animating the cards"
    )
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
        print(f"  {key:<14} {cls.name:<16} {cls.short_blurb}")


RECENT_LINES = 10  # the most games --stats lists under Recent games


def print_stats() -> None:
    print(
        f"{'Game':<16}{'Wins':>6}{'Total':>7}{'Win%':>7}{'Best':>8}{'Worst':>8}"
        f"{'Streak':>8}{'Longest':>8}"
    )
    streaks = history.streaks()
    for key in GAME_ORDER:
        s = store.get_stat(key)
        pcts = store.percent_text(s)
        best = "N/A" if s["best"] == 0 else store.fmt_time(s["best"])
        worst = "N/A" if s["worst"] == 0 else store.fmt_time(s["worst"])
        cur, longest = streaks.get(key, ("N/A", "N/A"))
        print(
            f"{GAMES[key].name:<16}{s['wins']:>6}{s['total']:>7}{pcts:>7}{best:>8}{worst:>8}"
            f"{cur:>8}{longest:>8}"
        )
    recent = history.recent(RECENT_LINES)
    if recent:
        print("\nRecent games")
        for e in recent:
            print(history.line(e))


def reset_stats(yes: bool) -> int:
    """--reset-stats: check with the player, back up, then clear."""
    played = history.any_games()
    if not store.any_stats() and not played:
        print("There are no statistics to clear.")
        return 0
    # only when AisleRiot has a game of ours to clear
    sharing = store.shared_record()
    if not yes:
        if not sys.stdin.isatty():
            print(
                "soliterm: --reset-stats asks before it erases anything; "
                "add --yes to clear the statistics without asking",
                file=sys.stderr,
            )
            return 2
        where = f", here and in GNOME AisleRiot ({ar.keyfile_path()})" if sharing else ""
        also = ", and the history of your games" if played else ""
        print(
            f"This erases the statistics of all {len(GAME_ORDER)} games{where}{also}.",
            file=sys.stderr,
        )
        if played:
            # they're worked out from the history, so its backup has them
            print(
                "The records and achievements go too, until history.jsonl.bak is put back.",
                file=sys.stderr,
            )
        print("Type yes to clear them: ", end="", file=sys.stderr, flush=True)
        came: list[int] = []  # the console events that came
        try:
            # on Windows, Ctrl-Break or the console closing breaks off the
            # wait for an answer as Ctrl-C does, where it waited for Enter
            with _leave_on_console_events() as came:
                answer = sys.stdin.readline()
        except KeyboardInterrupt:
            answer = ""
        if not answer.endswith("\n"):
            print(file=sys.stderr)  # Ctrl-D, Ctrl-C or Ctrl-Break left the line open
        if came or answer.strip().lower() != "yes":
            print("Nothing was cleared.")
            # a yes read after Ctrl-Break doesn't count, and it ends with
            # 130 as a game left with it does
            return 130 if came else 1
    try:
        backups = store.backup_stats()
        kept = history.backup()
        if kept:
            backups.append(kept)
    except OSError as exc:
        print(
            f"soliterm: couldn't back up the statistics ({exc}), so nothing was cleared",
            file=sys.stderr,
        )
        return 1
    for path in backups:
        print(f"Backup saved to {path}")
    n = store.reset_stats()
    if n is None:
        # stats.json couldn't be written, so nothing was cleared (its
        # notice says so) and the history stays with it
        return 1
    history.clear()
    if sharing:
        games = "1 game" if n == 1 else f"{n} games"
        print(f"Statistics cleared for {games} (shared with GNOME AisleRiot).")
    else:
        print("Statistics cleared.")
    return 0


def _load_tui() -> tuple[Any, str]:
    """The curses front end and a line for the player on the terminal type
    it plays as, "" when that is TERM's, or None and a line on why text
    mode it is.

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
            why += "; py -m pip install windows-curses adds curses to Python on Windows"
        return None, why
    problem, note = _check_terminal()
    if problem:
        return None, problem
    return tui, note


# The terminal types to play as when this system has no terminfo entry for
# the one TERM names, as over ssh from a newer terminal than the far end
# knows: nearly every terminal takes xterm's sequences, and tmux and
# screen take screen's
_STAND_INS = ("xterm-256color", "xterm")
_SCREEN_STAND_INS = ("screen-256color", "screen")
# what the player can do about a terminal type played as a stand-in
_TERMINFO_HINT = "install its terminfo for the full look"


def _check_terminal() -> tuple[str, str]:
    """Why curses can't draw the game on this terminal, "" if it can, and a
    line on the stand-in it plays as, "" for TERM's own type.

    Asked before the game starts: on a terminal type it doesn't know, or
    one that can't move the cursor, curses gives up with an error where
    text mode would have done. A type it doesn't know is played as a
    stand-in it does, if there is one, and TERM is set to that for curses
    to start with.
    """
    if os.name == "nt":
        return "", ""  # the Windows console needs no TERM
    import curses

    term = os.environ.get("TERM", "")
    rest = (
        "so playing in text mode; set TERM to your terminal's type "
        "(xterm-256color suits most) for the full-screen game"
    )
    if not term:
        return f"TERM isn't set, {rest}", ""
    if term == "dumb":
        return f"TERM=dumb can't move the cursor, {rest}", ""
    try:
        # fd 1, which curses draws on whatever sys.stdout is
        curses.setupterm(term, 1)
    except curses.error as exc:
        if "terminfo database" in str(exc):
            # a Python built to look in a folder of its own, not the system's
            return (
                f"TERM={term} can't be looked up, as curses finds no terminfo "
                "database, so playing in text mode; point TERMINFO_DIRS at one "
                "(TERMINFO_DIRS=/usr/share/terminfo:/lib/terminfo, say) for the "
                "full-screen game"
            ), ""
        stand_in = _stand_in(term)
        if stand_in is None:
            return (
                f"TERM={term} isn't a terminal type known here and no stand-in is, "
                "so playing in text mode; install its terminfo for the full-screen game"
            ), ""
        os.environ["TERM"] = stand_in
        return "", f"TERM={term} isn't known here, so playing as {stand_in}"
    if not curses.tigetstr("cup"):
        return f"TERM={term} can't move the cursor, {rest}", ""
    return "", ""


def _stand_in(term: str) -> str | None:
    """The terminal type to play as in place of `term`, which curses doesn't
    know, or None when it knows none of those tried: the first it knows,
    if that can move the cursor.

    Once curses has set up one type it looks up no other in the process,
    so after the first it knows there is no trying the next.
    """
    import curses

    inside = os.environ.get("TMUX") or os.environ.get("STY") or term.startswith(("tmux", "screen"))
    for name in _SCREEN_STAND_INS if inside else _STAND_INS:
        try:
            curses.setupterm(name, 1)
        except curses.error:
            continue
        return name if curses.tigetstr("cup") else None
    return None


def _quiet_on_broken_pipe(main: Callable[..., int]) -> Callable[..., int]:
    """End quietly when whoever reads our output stops reading.

    Output piped into head, or a pager quit early, closes the pipe: the next
    write raises BrokenPipeError (OSError EINVAL on Windows), and so does
    Python's own flush at exit. Pointing stdout at devnull leaves that last
    flush nowhere to fail.
    """

    @functools.wraps(main)
    def run(*args, **kwargs) -> int:
        try:
            try:
                rc = main(*args, **kwargs)
            except SystemExit:
                # --help and --version leave this way, their text still to
                # be written
                sys.stdout.flush()
                raise
            sys.stdout.flush()  # so a late broken pipe comes up here
            return rc
        except OSError as exc:
            if not _reader_went_away(exc):
                raise
            try:
                _to_devnull(sys.stdout.fileno())
            except (OSError, ValueError):
                pass  # a stdout with no file behind it
            return 141  # what a shell shows for SIGPIPE

    return run


def _reader_went_away(exc: OSError) -> bool:
    """True if `exc` is a write to a pipe nobody reads any more.

    Windows says EINVAL there, where other systems say EPIPE, so there an
    EINVAL counts when stdout is a pipe and it wasn't about a file name.
    """
    if isinstance(exc, BrokenPipeError):
        return True
    if os.name != "nt" or exc.errno != errno.EINVAL or exc.filename is not None:
        return False
    try:
        return stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode)
    except (OSError, ValueError):
        return False  # a stdout with no file behind it


def _to_devnull(*fds: int) -> None:
    """Point file descriptors at os.devnull, so writes to them go nowhere."""
    try:
        null = os.open(os.devnull, os.O_WRONLY)
        for fd in fds:
            os.dup2(null, fd)
    except OSError:
        pass


def _quiet_output() -> None:
    # every write to a terminal that has hung up fails with EIO
    _to_devnull(1, 2)


@contextmanager
def _leave_on_signals() -> Iterator[list[int]]:
    """Leave on SIGHUP (the terminal closing), SIGTERM or, on Windows,
    SIGBREAK (Ctrl-Break) the way Ctrl-C does.

    They raise KeyboardInterrupt, so the game in play is saved or counted as
    it is for Ctrl-C. After the first, another does nothing, so the second
    SIGHUP a closing terminal often sends can't cut that short, unless it
    comes while the way out waits for the stats lock: then it breaks off
    the wait, as a second Ctrl-C does. One ignored already, as nohup
    leaves SIGHUP, stays ignored. What it yields lists the signals that
    came. While a game may be in play on Windows, or --reset-stats asks,
    Ctrl-Break goes to _leave_on_console_events instead.
    """
    hup = getattr(signal, "SIGHUP", None)  # not on Windows
    brk = getattr(signal, "SIGBREAK", None)  # only on Windows
    signums = [
        s
        for s in (hup, signal.SIGTERM, brk)
        if s is not None and signal.getsignal(s) != signal.SIG_IGN
    ]
    came: list[int] = []

    def leave(signum: int, frame: object) -> None:
        if signum == hup:
            _quiet_output()
        if came and not store.waiting_for_lock():
            return
        came.append(signum)
        raise KeyboardInterrupt

    old = {}
    for s in signums:
        try:
            old[s] = signal.signal(s, leave)
        except (ValueError, OSError):
            pass  # only the main thread can set a handler
    try:
        yield came
    finally:
        for s, handler in old.items():
            if handler is not None:  # None: one set outside Python
                signal.signal(s, handler)


# The console control events that leave: CTRL_BREAK_EVENT, then
# CTRL_CLOSE_EVENT (the console window closing), CTRL_LOGOFF_EVENT and
# CTRL_SHUTDOWN_EVENT (logging off or shutting down with it open)
_CTRL_BREAK_EVENT = 1
_CONSOLE_LEAVING = (_CTRL_BREAK_EVENT, 2, 5, 6)
# How long the handler holds Windows off, after the console closes, while
# the game is put away: Windows ends the process 5 seconds after the close
# in any case
_CLOSE_WAIT = 4.0
# Every handler set, kept for the life of the process, as Windows may
# still be in one as the way out takes it out
_console_handlers: list[object] = []


@contextmanager
def _leave_on_console_events() -> Iterator[list[int]]:
    """On Windows, leave the way Ctrl-C does when the console window closes
    or Ctrl-Break is pressed, while a game may be in play or --reset-stats
    waits for its answer.

    Windows sends no signal for the close, but calls a handler on a thread
    of its own and ends the process once it returns. This one interrupts
    the main thread as Ctrl-C would, and breaks off a read of stdin, which
    the interrupt alone doesn't reach and which text mode waits in. Then
    it holds Windows off until the block is over, with the game put away,
    or for as long as Windows allows. Logging off and shutting down are
    taken the same way, though Windows sends those only to a process
    without user32.dll loaded, and Python has it loaded by then.

    Ctrl-Break comes here too, and leaves the same way without the wait,
    as Windows doesn't end the process for it. Left to its SIGBREAK, which
    comes only after this handler, it would be too late to be pending as
    the read is broken off, and a Ctrl-Break that a program sends doesn't
    end the read by itself. After the first event, another does no more
    than wait. Ctrl-C is left to Python's handler. What it yields lists
    the events that came. Off Windows, or where the handler can't be set,
    it does nothing.
    """
    came: list[int] = []
    if sys.platform != "win32":
        yield came
        return
    import _thread
    import ctypes
    import msvcrt
    import threading
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")
    try:
        stdin = wintypes.HANDLE(msvcrt.get_osfhandle(sys.stdin.fileno()))
    except (AttributeError, OSError, ValueError):
        stdin = None  # a stdin with no file behind it has no read to break off
    done = threading.Event()

    def on_event(event: int) -> bool:
        if event not in _CONSOLE_LEAVING:
            return False
        # one that comes as the way out ends has nothing left to interrupt
        if not came and not done.is_set():
            came.append(event)
            _thread.interrupt_main()
            if stdin is not None:
                kernel32.CancelIoEx(stdin, None)
        if event != _CTRL_BREAK_EVENT:
            done.wait(_CLOSE_WAIT)
        return True

    handler = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(on_event)
    if not kernel32.SetConsoleCtrlHandler(handler, True):
        yield came
        return
    _console_handlers.append(handler)
    try:
        yield came
    finally:
        done.set()
        kernel32.SetConsoleCtrlHandler(handler, False)


def _say_waiting() -> None:
    # the TUI says it on the screen instead
    print(f"soliterm: {store.LOCK_WAIT}", file=sys.stderr, flush=True)


def _say_after(line: str) -> None:
    """Say `line` on stderr once the game is over, unless whatever read it
    has gone (EPIPE, or EINVAL on Windows): then stderr goes to devnull,
    and the game still ends as it would have."""
    try:
        print(f"soliterm: {line}", file=sys.stderr, flush=True)
    except OSError:
        _to_devnull(2)


@_quiet_on_broken_pipe
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.debug_info:
        # before the migration, so the report writes, moves and copies nothing
        print(debuginfo.text(args.no_sync, sys.stdout.encoding))
        return 0
    # before anything reads the config or the stats
    migrate.ensure()
    if args.no_sync:
        store.disable_sync()
    try:
        with _leave_on_signals() as came, store.lock_wait_note(_say_waiting):
            try:
                rc = _run(args, parser)
            except KeyboardInterrupt:
                # one nothing caught, say during --stats: 130, as a game
                # leaves, and no traceback
                rc = 130
        # 130 as for Ctrl-C, even when curses couldn't put back a terminal
        # that had hung up
        return 130 if came else rc
    finally:
        # anything that kept the stats from being shared or saved as usual,
        # bar what text mode told of as it started
        try:
            for msg in store.tell_notices():
                print(f"soliterm: {msg}", file=sys.stderr)
        except OSError:
            # whatever read stderr has gone (EPIPE, or EINVAL on Windows),
            # which is no reason to lose stdout or end with 120 when
            # Python's flush at exit meets the same pipe
            _to_devnull(2)


def _requested_deal(args: argparse.Namespace, cfg: dict) -> deals.Deal | None:
    """What the command line asks to play, or None for nothing in particular
    (the menu in the TUI, the last game at random in text mode). Options
    from --draw and --suits go over the saved ones and aren't saved."""
    if args.seed is not None and args.deal is not None:
        raise ValueError("argument --seed: not allowed with argument --deal")
    if args.seed is not None and args.daily:
        raise ValueError("argument --seed: not allowed with argument --daily")
    code = args.deal if args.deal is not None else args.seed
    given = {name: v for name, v in (("draw", args.draw), ("suits", args.suits)) if v is not None}
    if args.daily and given:
        raise ValueError(
            "--daily can't be given options: the daily deal always uses the standard ones"
        )
    if args.daily:
        return deals.daily(args.game or cfg.get("last_game", "klondike"), deals.today())
    if len(given) > 1:
        raise ValueError("--draw and --suits are for different games")
    if code is not None and code.key is not None:
        if args.game and args.game != code.key:
            raise ValueError(f"--game {args.game} doesn't match the share code's game ({code.key})")
        if given:
            flag = next(iter(given))
            raise ValueError(f"a share code carries its own options, so leave out --{flag}")
        return deals.Deal(code.key, code.number, code.options)
    number = None if code is None else code.number
    if given:
        (name,) = given
        key = args.game or _owner(name)
        if name not in GAMES[key].default_options():
            owner, game = GAMES[_owner(name)].name, GAMES[key].name
            raise ValueError(f"--{name} only goes with {owner}, not {game}")
        return deals.Deal(key, number, given)
    if code is not None:
        return deals.Deal(args.game or cfg.get("last_game", "klondike"), number)
    if args.game:
        return deals.Deal(args.game)
    return None


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.list:
        print_list()
        return 0
    if args.reset_stats:
        return reset_stats(args.yes)
    if args.stats:
        print_stats()
        return 0

    cfg = store.load_config()
    try:
        # worked out once, so text mode plays the same deal if curses can't start
        start = _requested_deal(args, cfg)
    except ValueError as exc:
        parser.error(str(exc))
    symbols = cfg.get("symbols", True) and not args.ascii

    # Colour in text mode: explicit --color/--no-color wins; otherwise on
    # unless NO_COLOR is set (https://no-color.org) or stdout isn't a TTY.
    # Either way run_text leaves it off at a terminal that can't show it,
    # as an old Windows console. The TUI gets the bare flag, since it also
    # has the colour saved with v.
    if args.color is None:
        color = not os.environ.get("NO_COLOR")
        text_color = color and sys.stdout.isatty()
    else:
        color = text_color = args.color

    if not args.text and sys.stdout.isatty() and sys.stdin.isatty():
        tui, said = _load_tui()
        if tui is not None:
            with _leave_on_console_events():
                rc = tui.main(
                    start,
                    color=args.color,
                    symbols=symbols,
                    animation=False if args.no_animation else None,
                    theme=args.theme,
                    note=said,
                )
            if said:
                # the first game said it, and now the screen is back, where
                # it stays
                _say_after(f"{said} ({_TERMINFO_HINT})")
            return rc
        print(f"soliterm: {said}", file=sys.stderr)

    # text mode, which keeps games only for someone typing at a terminal:
    # a script or a pipe plays its deal and counts it, as it always has
    deal = start or deals.Deal(cfg.get("last_game", "klondike"))
    keep = sys.stdin.isatty()
    # as in the TUI, only a plain start, with no deal number or options, or
    # a daily over a save of the same daily, resumes
    resumes = keep and deals.resumes(deal, saves.waiting(deal.key).get(deal.key))
    with _leave_on_console_events():
        return run_text(
            deals.deal_game(deal, store.game_options(cfg, deal.key)),
            symbols,
            deal.key,
            color=text_color,
            camo_theme=cfg.get("camo_theme"),
            keep=keep,
            resume=resumes,
        )


if __name__ == "__main__":
    sys.exit(main())
