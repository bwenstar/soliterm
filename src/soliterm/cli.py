"""soliterm.cli - the launcher and the pipe-friendly text mode.

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
import time
from typing import List, Optional, Tuple

from . import APP_NAME, __version__, camo, engine, store
from .engine import GAME_ORDER, GAMES, Card, Solitaire


# --------------------------------------------------------------------------- #
# Text rendering (curses-free; for pipes and tests)
# --------------------------------------------------------------------------- #

# ANSI colours for text mode. We draw a face-up card like a real card: a white
# card face with red text for hearts/diamonds and black text for spades/clubs,
# so black suits read as black (not white) on any terminal background. Escape
# codes wrap only the card token and never change its visible width, so column
# alignment is unaffected.
_ANSI = {
    "red":   "\033[1;31;47m",   # bold red on white
    "black": "\033[30;47m",     # black on white
    "back":  "\033[37;44m",     # white on blue (face-down back)
    "reset": "\033[0m",
}


def _cell(card: Optional[Card], symbols: bool, color: bool = False) -> str:
    if card is None:
        return "[  ]"
    if not card.face_up:
        token = "[##]"
        return f"{_ANSI['back']}{token}{_ANSI['reset']}" if color else token
    token = f"[{card.label(symbols):>2}]"
    if not color:
        return token
    paint = _ANSI["red"] if card.is_red else _ANSI["black"]
    return f"{paint}{token}{_ANSI['reset']}"


def render_text(g: Solitaire, symbols: bool = True, color: bool = False) -> str:
    lines: List[str] = []
    lines.append(f"=== {g.gamedef.name} ===")
    # group slots by row
    rows = sorted({s.row for s in g.slots})
    # number tableau/cell/etc slots 1-based for the command interface
    for row in rows:
        sids = [s.sid for s in g.slots if s.row == row]
        # header line of slot tags
        tags = []
        for sid in sids:
            s = g.slots[sid]
            tag = {"stock": "stk", "waste": "wst", "foundation": "fnd",
                   "tableau": f"#{sid}", "reserve": "rsv", "freecell": "cel"}.get(s.kind, str(sid))
            tags.append(f"{tag:>4}")
        lines.append(" ".join(tags))
        # show the slots; expand "down" slots vertically
        max_h = max((len(g.slots[sid].cards) for sid in sids
                     if g.slots[sid].expand == "down"), default=0)
        if max_h == 0:
            # single-line row (stock/waste/foundations/cells)
            cells = []
            for sid in sids:
                s = g.slots[sid]
                if s.expand == "right":
                    inner = " ".join(_cell(c, symbols, color) for c in s.cards[-6:]) or "[  ]"
                    cells.append(inner)
                else:
                    extra = f"({len(s.cards)})" if s.kind == "stock" else ""
                    cells.append(_cell(s.top, symbols, color) + extra)
            lines.append(" ".join(f"{c:>4}" for c in cells))
        else:
            for r in range(max_h):
                cells = []
                for sid in sids:
                    s = g.slots[sid]
                    if s.expand == "down":
                        cells.append(_cell(s.cards[r], symbols, color) if r < len(s.cards)
                                     else ("[  ]" if r == 0 and not s.cards else "    "))
                    else:
                        cells.append((_cell(s.top, symbols, color) if r == 0 else "    "))
                lines.append(" ".join(f"{c:>4}" for c in cells))
        lines.append("")
    won = "  *** YOU WIN! ***" if g.is_won() else ""
    lines.append(f"score={g.score} moves={g.moves} | {g.status}{won}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Text command parser (slots addressed by their engine id)
# --------------------------------------------------------------------------- #

TEXT_HELP = """\
Text-mode commands (slots are addressed by the #N tags shown on the board):
  p / .            reprint the board
  d                deal from the stock
  a                autoplay safe cards to foundations
  <src> <dst>      move the default run from slot src to slot dst, e.g.  9 12
  <src> <dst> <n>  move exactly n cards
  c <slot>         click a slot (deal / play, game-specific)
  cc <slot>        double-click a slot (send to foundation)
  f <slot>         send the slot's top card to its foundation
  hint / ?         suggest a legal move (shows the slot ids to use)
  b / boss         boss mode: print fake 'work' output to hide the game
  u  undo   r  redo   n  new deal
  h / help         this help
  q                quit
"""


def _hint_message(g: Solitaire) -> str:
    h = g.hint()
    if h is None:
        return "Hint: no move available - try dealing, or undo."
    src, dst, desc = h
    if src == dst:                      # a deal-from-stock style hint
        return f"Hint: {desc}."
    return f"Hint: {desc}  (type:  {src} {dst})"


def apply_text_command(g: Solitaire, cmd: str) -> Tuple[bool, str]:
    cmd = cmd.strip().lower()
    if not cmd:
        return False, ""
    if cmd in ("q", "quit", "exit"):
        return True, "__quit__"
    if cmd in ("h", "help"):
        return True, TEXT_HELP
    if cmd in ("hint", "?"):
        return True, _hint_message(g)
    if cmd in ("b", "boss"):
        return True, "__boss__"
    if cmd in ("p", ".", "print"):
        return True, "__print__"
    if cmd in ("d", "deal"):
        ok = g.deal()
        return ok, "" if ok else g.deal_blocked_reason()
    if cmd in ("a", "auto"):
        n = g.autoplay()
        return n > 0, f"autoplayed {n}"
    if cmd in ("u", "undo"):
        ok = g.undo()
        return ok, "" if ok else "nothing to undo"
    if cmd in ("r", "redo"):
        ok = g.redo()
        return ok, "" if ok else "nothing to redo"
    if cmd in ("n", "new"):
        g.new_game()
        return True, "new deal"

    parts = cmd.replace(",", " ").split()
    try:
        if parts[0] in ("c", "click") and len(parts) == 2:
            return g.click(int(parts[1])), ""
        if parts[0] in ("cc", "dc") and len(parts) == 2:
            return g.double_click(int(parts[1])), ""
        if parts[0] in ("f", "found") and len(parts) == 2:
            return g.double_click(int(parts[1])), ""
        if all(p.isdigit() for p in parts) and len(parts) in (2, 3):
            src = int(parts[0]); dst = int(parts[1])
            n = int(parts[2]) if len(parts) == 3 else None
            ok = g.attempt_move(src, dst, n)
            return ok, "" if ok else "illegal move"
    except (ValueError, IndexError):
        pass
    return False, f"bad command: {cmd!r} (try h)"


def run_text(g: Solitaire, symbols: bool, game_key: str, stream=None,
             color: bool = False) -> int:
    out = sys.stdout
    inp = stream if stream is not None else sys.stdin
    start = time.time()
    print(f"{APP_NAME} - {g.gamedef.name} (text mode). Type h for help.\n", file=out)
    print(render_text(g, symbols, color), file=out)
    recorded = False
    for raw in inp:
        line = raw.strip()
        if not line:
            continue
        ok, msg = apply_text_command(g, line)
        if msg == "__quit__":
            print("bye", file=out)
            return 0
        if msg == "__print__":
            print(render_text(g, symbols, color), file=out)
            continue
        if msg == "__boss__":
            # print a screenful of plausible 'work' output instead of the board
            theme = camo.DEFAULT_THEME
            for cl in camo.screenful(theme, lines=40):
                print(cl, file=out)
            continue
        if msg == TEXT_HELP:
            print(msg, file=out)
            continue
        if msg:
            print(msg, file=out)
        print(render_text(g, symbols, color), file=out)
        if g.is_won() and not recorded:
            recorded = True
            store.record_result(game_key, True, time.time() - start)
            print("Congratulations - you won!", file=out)
            print(f"Score {g.score} in {store.fmt_time(time.time() - start)} "
                  f"({g.moves} moves).", file=out)
            return 0
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="soliterm",
        description=f"{APP_NAME}: solitaire for your terminal, AisleRiot-compatible.",
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
    p.add_argument("--list", action="store_true", help="list the games and exit")
    p.add_argument("--stats", action="store_true", help="print statistics and exit")
    p.add_argument("--reset-stats", action="store_true",
                   help="erase all statistics and exit")
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


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        print_list(); return 0
    if args.reset_stats:
        n = store.reset_stats()
        if store.syncing():
            print(f"Statistics cleared for {n} game(s) "
                  "(shared with GNOME AisleRiot).")
        else:
            print("Statistics cleared.")
        return 0
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
