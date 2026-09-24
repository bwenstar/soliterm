"""soliterm.textmode - the pipe-friendly text mode.

A curses-free board render and a line-at-a-time command loop, for pipes,
scripts and tests. The CLI runs it for --text, when stdin or stdout is not
a terminal, and when curses is not available. The command grammar
(TEXT_HELP) is what scripts drive, so it stays stable.
"""

from __future__ import annotations

import re
import shutil
import sys
import time

from . import APP_NAME, camo, history, saves, store
from .deals import code_of, deal_label, share_line
from .engine import SUIT_SYMBOL, Card, Slot, Solitaire

# --------------------------------------------------------------------------- #
# Text rendering (curses-free; for pipes and tests)
# --------------------------------------------------------------------------- #

# ANSI colours for text mode. We draw a face-up card like a real card: a white
# card face with red text for hearts/diamonds and black text for spades/clubs,
# so black suits read as black (not white) on any terminal background. Escape
# codes wrap only the card token and never change its visible width; columns
# are padded on the visible width (see _pad), so alignment is unaffected.
_ANSI = {
    "red": "\033[1;31;47m",  # bold red on white
    "black": "\033[30;47m",  # black on white
    "back": "\033[37;44m",  # white on blue (face-down back)
    "reset": "\033[0m",
}
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# Every card token is this wide, so '[10S]' and '[ 9S]' take the same room.
_CELL_W = 5
# Most cards a right-fanned waste (Golf, Canfield, Forty Thieves) shows. Four
# keeps the widest top row, Forty Thieves', inside 80 columns.
_FAN = 4


def _cell(card: Card | None, symbols: bool, color: bool = False) -> str:
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


_KIND_TAG = {
    "stock": "stk",
    "waste": "wst",
    "foundation": "fnd",
    "reserve": "rsv",
    "freecell": "cel",
    "tableau": "",
}


def slot_tag(g: Solitaire, sid: int) -> str:
    """How the board labels a slot: its kind and id, e.g. 'fnd#4', '#9'.

    Tableau columns are the common case, so they go without a kind.
    """
    return f"{_KIND_TAG.get(g.kind(sid), g.kind(sid)[:3])}#{sid}"


def _column(s: Slot, symbols: bool, color: bool) -> list[str]:
    """The lines a slot draws under its tag, top to bottom."""
    if s.expand == "down":
        return [_cell(c, symbols, color) for c in s.cards] or [_cell(None, symbols)]
    if s.expand == "right":
        return [" ".join(_cell(c, symbols, color) for c in s.cards[-_FAN:]) or _cell(None, symbols)]
    lines = [_cell(s.top, symbols, color)]
    if s.kind == "stock":
        lines.append(f"({len(s.cards)})")  # the count sits under the pile
    return lines


def _placed(g: Solitaire, slots: list[Slot], symbols: bool, color: bool) -> list[str]:
    """Slots the game places by hand (Triple Peaks): a tag line and a card
    line for each row down, a half card being three columns across. An
    empty one is left out, as on the board."""
    spots = {s.sid: spot for s in slots if s.cards and (spot := g.gamedef.spot(g, s.sid))}
    lines: list[str] = []
    for down in sorted({d for d, _ in spots.values()}):
        tags = cells = ""
        for sid, (d, across) in spots.items():
            if d == down:
                x = across * 3
                tags += " " * (x - len(tags)) + _pad(slot_tag(g, sid), _CELL_W)
                cells += " " * (x - _width(cells)) + _cell(g.top(sid), symbols, color)
        lines += [tags, cells, ""]
    return lines


def render_text(g: Solitaire, symbols: bool = True, color: bool = False) -> str:
    lines: list[str] = []
    lines.append(f"=== {g.gamedef.name} ===")
    for row in sorted({s.row for s in g.slots}):
        slots = [s for s in g.slots if s.row == row]
        if g.gamedef.spot(g, slots[0].sid) is not None:
            lines += _placed(g, slots, symbols, color)
            continue
        tags = [slot_tag(g, s.sid) for s in slots]
        cols = [_column(s, symbols, color) for s in slots]
        # each column is as wide as its widest line, so a slot's cards
        # always sit right under its tag
        widths = [max([_CELL_W, len(t)] + [_width(x) for x in c]) for t, c in zip(tags, cols)]
        lines.append(" ".join(_pad(t, w) for t, w in zip(tags, widths)))
        for r in range(max(len(c) for c in cols)):
            lines.append(
                " ".join(_pad(c[r] if r < len(c) else "", w) for c, w in zip(cols, widths)).rstrip()
            )
        lines.append("")
    won = "  *** YOU WIN! ***" if g.is_won() else ""
    lines.append(f"score={g.score} moves={g.moves} | {g.status}{won}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Text command parser (slots addressed by their engine id)
# --------------------------------------------------------------------------- #

TEXT_HELP = """\
Text-mode commands. A slot is named by the number in its tag on the board,
so stk#0 is 0, fnd#4 is 4 and #9 is 9:
  p / .            reprint the board
  d                deal from the stock
  a                autoplay safe cards, or finish once all can go up
  <src> <dst>      move the longest run from slot src that dst takes, e.g.  9 12
  <src> <dst> <n>  move exactly n cards
  c <slot>         click a slot (deal / play, game-specific)
  cc <slot>        double-click a slot (send to foundation)
  f <slot>         send the slot's top card to its foundation
  hint / ?         suggest a legal move (shows the slot ids to use)
  b / boss         boss mode: print fake 'work' output to hide the game
  u  undo   r  redo   n  new deal
  undo all         take back every move, back to the deal
  redo all         redo every move taken back
  N / restart      start this deal over
  h / help         this help
  q                quit
"""


def _hint_count(g: Solitaire, src: int, dst: int) -> int:
    """How many cards the hinted move from src to dst lifts."""
    # the hint may be a setup move rather than best_move(), and that can
    # lift fewer cards than a bare "src dst" would
    mv = g.hint_move()
    if mv is not None and mv[:2] == (src, dst):
        return mv[2]
    # not the hinted move: the longest run that lands, as a bare "src dst"
    # would pick
    for n in range(g.default_pickup(src), 0, -1):
        sim = g.clone()
        if sim.attempt_move(src, dst, n):
            return n
    return g.default_pickup(src)


def _hint_message(g: Solitaire) -> str:
    h = g.hint()
    if h is None:
        return f"Hint: {g.no_hint_reason()}."
    src, dst, desc = h
    if src == dst:  # a deal-from-stock style hint
        if g.kind(src) == "stock":
            return f"Hint: {desc}  (type: d)"
        return f"Hint: {desc}."
    # a bare "src dst" lifts the default run; name the count when it differs
    n = _hint_count(g, src, dst)
    cmd = f"{src} {dst}" if n == g.default_pickup(src) else f"{src} {dst} {n}"
    return f"Hint: {desc}  ({slot_tag(g, src)} -> {slot_tag(g, dst)}, type: {cmd})"


def _missing_slot(g: Solitaire, *sids: int) -> str:
    """Names the first of sids that is not a slot on this board, else ''."""
    for sid in sids:
        if not 0 <= sid < len(g.slots):
            return f"no slot {sid} (slots are 0-{len(g.slots) - 1})"
    return ""


def apply_text_command(g: Solitaire, cmd: str) -> tuple[bool, str]:
    raw = cmd.strip()
    cmd = raw.lower()
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
        n = g.finish() or g.autoplay()
        return n > 0, f"autoplayed {n}" if n else "nothing to autoplay"
    if cmd.split() == ["undo", "all"]:
        n = g.undo_all()
        return n > 0, "" if n else "nothing to undo"
    if cmd.split() == ["redo", "all"]:
        n = g.redo_all()
        return n > 0, "" if n else "nothing to redo"
    if cmd in ("u", "undo"):
        ok = g.undo()
        return ok, "" if ok else "nothing to undo"
    if cmd in ("r", "redo"):
        ok = g.redo()
        return ok, "" if ok else "nothing to redo"
    # the one place case matters, as in the TUI: N replays this deal, n
    # deals a new one. run_text deals, since leaving a deal can count in
    # the stats.
    if raw == "N" or cmd == "restart":
        return True, "__restart__"
    if cmd in ("n", "new"):
        return True, "__newdeal__"

    parts = cmd.replace(",", " ").split()
    try:
        if parts[0] in ("c", "click", "cc", "dc", "f", "found") and len(parts) == 2:
            sid = int(parts[1])
            missing = _missing_slot(g, sid)
            if missing:
                return False, missing
            tag = slot_tag(g, sid)
            if parts[0] in ("c", "click"):
                ok = g.click(sid)
                return ok, "" if ok else f"clicking {tag} does nothing"
            ok = g.double_click(sid)
            if parts[0] in ("cc", "dc"):
                return ok, "" if ok else f"double-clicking {tag} does nothing"
            return ok, "" if ok else f"no foundation move from {tag}"
        if all(p.isdigit() for p in parts) and len(parts) in (2, 3):
            src = int(parts[0])
            dst = int(parts[1])
            missing = _missing_slot(g, src, dst)
            if missing:
                return False, missing
            count = int(parts[2]) if len(parts) == 3 else None
            ok = g.attempt_move(src, dst, count)
            if not ok and count is None:
                # like a drop in the TUI: when the whole run won't land,
                # try the shorter runs off its top, longest first
                for k in range(g.default_pickup(src) - 1, 0, -1):
                    if g.attempt_move(src, dst, k):
                        ok = True
                        break
            return ok, "" if ok else "illegal move"
    except (ValueError, IndexError):
        pass
    return False, f"bad command: {cmd!r} (try h)"


def _can_write(out, text: str) -> bool:
    """Whether out's encoding has every character of text."""
    encoding = getattr(out, "encoding", None)
    if not encoding:  # a str buffer such as StringIO
        return True
    try:
        text.encode(encoding)
    except (UnicodeError, LookupError):
        return False
    return True


def run_text(
    g: Solitaire,
    symbols: bool,
    game_key: str,
    stream=None,
    color: bool = False,
    camo_theme: str | None = None,
    keep: bool = False,
    resume: bool = False,
) -> int:
    """Play g at a prompt, reading commands from `stream` (stdin by default).

    With `resume`, the game saved for game_key is played in g's place if
    there is one. With `keep`, a game left under way is saved for next time
    rather than counted lost.
    """
    out = sys.stdout
    inp = stream if stream is not None else sys.stdin
    # a cp1252 or ASCII stdout has no suit symbols; letters beat a crash
    symbols = symbols and _can_write(out, "".join(SUIT_SYMBOL.values()))
    theme = camo_theme if camo_theme in camo.THEMES else camo.DEFAULT_THEME
    start = time.monotonic()  # one clock per deal
    recorded = False
    resumed = False

    def seconds() -> int:
        """This deal's time in whole seconds, as it is printed and stored."""
        return round(time.monotonic() - start)

    def boss() -> None:
        # A screenful of plausible 'work' output instead of the board. On a
        # terminal, wipe the screen and its scrollback and fill the height,
        # so no card is left in view; a pipe just gets a block of lines.
        rows = 40
        if out.isatty():
            out.write("\x1b[H\x1b[2J\x1b[3J")
            rows = shutil.get_terminal_size().lines
        for line in camo.screenful(theme, lines=rows):
            print(line, file=out)

    def so_far() -> str:
        return f"{store.fmt_time(seconds())}, {store.moves_text(g.moves)}"

    def under_way() -> bool:
        # from the first move, as in the TUI and AisleRiot, or from the start
        # of a resumed game, until it is counted or saved; a deal nobody
        # touched does not count at all
        return not recorded and not g.is_won() and (g.moves > 0 or resumed)

    def count(won: bool, secs: int) -> None:
        nonlocal recorded
        with store.signals_held():
            history.record(g, won, secs)
            recorded = True

    def give_up() -> None:
        if under_way():
            count(False, seconds())

    def put_away() -> None:
        # on leaving: kept for next time if it may be, and otherwise lost,
        # with saves.keep's notice saying why; a win not counted yet, as
        # when Ctrl-C comes just as it's made, counts as won
        nonlocal recorded
        if g.is_won() and not recorded:
            count(True, seconds())
            return
        if keep and under_way():
            with store.signals_held():
                recorded = saves.keep(g, seconds())
            if recorded:
                print(f"Saved your game ({so_far()}) for next time.", file=out)
                return
        give_up()

    try:
        if resume:
            # From the take on, the game is out of the saves folder until
            # put_away puts it back, so a signal waits until it is in play
            with store.signals_held():
                taken = saves.take(game_key)
                if taken is not None:
                    g, played = taken
                    start -= played
                    resumed = True
        g.symbols = symbols  # hints name cards as the board does
        name = g.gamedef.name
        print(f"{APP_NAME} - {name} - {deal_label(g)} (text mode). Type h for help.", file=out)
        if resumed:
            print(f"Resumed your {name} game ({so_far()}). Type n for a new deal.", file=out)
        elif keep and g.gamedef.key in saves.waiting(g.gamedef.key):
            print(f"a saved {name} game is waiting, so this one won't be kept", file=out)
        print(file=out)
        print(render_text(g, symbols, color), file=out)
        for raw in inp:
            line = raw.strip()
            if not line:
                continue
            _ok, msg = apply_text_command(g, line)
            if msg == "__quit__":
                put_away()
                print("bye", file=out)
                return 0
            if msg == "__newdeal__":
                give_up()
                g.new_game()
                start, recorded, resumed = time.monotonic(), False, False
                msg = f"new deal {g.deal_number}"
            elif msg == "__restart__":
                # the same hand again: AisleRiot does not count a restart
                g.restart()
                start, recorded, resumed = time.monotonic(), False, False
                msg = "restarted this deal"
            if msg == "__print__":
                print(render_text(g, symbols, color), file=out)
                continue
            if msg == "__boss__":
                boss()
                continue
            if msg == TEXT_HELP:
                print(msg, file=out)
                continue
            if msg:
                print(msg, file=out)
            print(render_text(g, symbols, color), file=out)
            if g.is_won() and not recorded:
                secs = seconds()
                count(True, secs)
                print("Congratulations - you won!", file=out)
                print(
                    f"Score {g.score} in {store.fmt_time(secs)} ({store.moves_text(g.moves)}).",
                    file=out,
                )
                print(f"Share code: {code_of(g)}", file=out)
                if g.daily:
                    print(share_line(g.gamedef.name, g.daily, True, secs, g.moves), file=out)
                streak = history.streak_text(game_key)
                if streak:
                    print(f"{streak}.", file=out)
                return 0
        put_away()  # the input ran out: Ctrl-D, or the end of a script
        return 0
    except KeyboardInterrupt:
        # Ctrl-C leaves like q does, minus the traceback, and so do SIGHUP
        # and SIGTERM, which the command line turns into this
        print(file=sys.stderr)
        put_away()
        return 130
