"""soliterm.textmode - the pipe-friendly text mode.

A curses-free board render and a line-at-a-time command loop, for pipes,
scripts and tests. The CLI runs it for --text, when stdin or stdout is not
a terminal, and when curses is not available. The command grammar
(TEXT_HELP) is what scripts drive, so it stays stable.
"""

from __future__ import annotations

import re
import sys
import time
from typing import List, Optional, Tuple

from . import APP_NAME, camo, store
from .engine import Card, Slot, Solitaire


# --------------------------------------------------------------------------- #
# Text rendering (curses-free; for pipes and tests)
# --------------------------------------------------------------------------- #

# ANSI colours for text mode. We draw a face-up card like a real card: a white
# card face with red text for hearts/diamonds and black text for spades/clubs,
# so black suits read as black (not white) on any terminal background. Escape
# codes wrap only the card token and never change its visible width; columns
# are padded on the visible width (see _pad), so alignment is unaffected.
_ANSI = {
    "red":   "\033[1;31;47m",   # bold red on white
    "black": "\033[30;47m",     # black on white
    "back":  "\033[37;44m",     # white on blue (face-down back)
    "reset": "\033[0m",
}
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# Every card token is this wide, so '[10S]' and '[ 9S]' take the same room.
_CELL_W = 5
# Most cards a right-fanned waste (Golf, Canfield, Forty Thieves) shows. Four
# keeps the widest top row, Forty Thieves', inside 80 columns.
_FAN = 4


def _cell(card: Optional[Card], symbols: bool, color: bool = False) -> str:
    if card is None:
        return "[   ]"
    if not card.face_up:
        token = "[###]"
        return f"{_ANSI['back']}{token}{_ANSI['reset']}" if color else token
    token = f"[{card.label(symbols):>3}]"
    if not color:
        return token
    paint = _ANSI["red"] if card.is_red else _ANSI["black"]
    return f"{paint}{token}{_ANSI['reset']}"


def _width(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _pad(text: str, width: int) -> str:
    """Right-align text in a column, measuring what the terminal shows."""
    return " " * (width - _width(text)) + text


def _column(s: Slot, symbols: bool, color: bool) -> List[str]:
    """The lines a slot draws under its tag, top to bottom."""
    if s.expand == "down":
        return [_cell(c, symbols, color) for c in s.cards] or [_cell(None, symbols)]
    if s.expand == "right":
        return [" ".join(_cell(c, symbols, color) for c in s.cards[-_FAN:])
                or _cell(None, symbols)]
    lines = [_cell(s.top, symbols, color)]
    if s.kind == "stock":
        lines.append(f"({len(s.cards)})")      # the count sits under the pile
    return lines


def render_text(g: Solitaire, symbols: bool = True, color: bool = False) -> str:
    lines: List[str] = []
    lines.append(f"=== {g.gamedef.name} ===")
    for row in sorted({s.row for s in g.slots}):
        slots = [s for s in g.slots if s.row == row]
        tags = [{"stock": "stk", "waste": "wst", "foundation": "fnd",
                 "tableau": f"#{s.sid}", "reserve": "rsv",
                 "freecell": "cel"}.get(s.kind, str(s.sid)) for s in slots]
        cols = [_column(s, symbols, color) for s in slots]
        # each column is as wide as its widest line, so a slot's cards
        # always sit right under its tag
        widths = [max([_CELL_W, len(t)] + [_width(x) for x in c])
                  for t, c in zip(tags, cols)]
        lines.append(" ".join(_pad(t, w) for t, w in zip(tags, widths)))
        for r in range(max(len(c) for c in cols)):
            lines.append(" ".join(_pad(c[r] if r < len(c) else "", w)
                                  for c, w in zip(cols, widths)).rstrip())
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
        return f"Hint: {g.no_hint_reason()}."
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
    g.symbols = symbols               # hints name cards as the board does
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
