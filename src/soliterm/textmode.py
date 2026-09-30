"""soliterm.textmode - the pipe-friendly text mode.

A curses-free board render and a line-at-a-time command loop, for pipes,
scripts and tests. The CLI runs it for --text, when stdin or stdout is not
a terminal, and when curses is not available. The command grammar
(TEXT_HELP) is what scripts drive, so it stays stable.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import sys
import time
from contextlib import suppress
from typing import Callable

from . import APP_NAME, camo, history, records, saves, store
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
    """Slots the game places by hand (Triple Peaks, Pyramid): a tag line and
    a card line for each row down, a half card being three columns across.
    An empty tableau slot is left out, as on the board. A right-fanned one
    shows as many cards as the board does, its tag over the top one, and a
    stock has its count under it as in a row of columns."""
    spots = {
        s.sid: spot
        for s in slots
        if (s.cards or s.kind != "tableau") and (spot := g.gamedef.spot(g, s.sid))
    }
    lines: list[str] = []
    for down in sorted({d for d, _ in spots.values()}):
        tags = cells = counts = ""
        for sid, (d, across) in spots.items():
            if d == down:
                x = across * 3
                slot = g.slots[sid]
                shown: list[Card | None] = [slot.top]
                if slot.expand == "right" and slot.cards:
                    shown = list(slot.cards[-(g.gamedef.fan_limit(g, sid) or _FAN) :])
                text = " ".join(_cell(c, symbols, color) for c in shown)
                tag = slot_tag(g, sid)
                tags += " " * (x + _width(text) - len(tag) - len(tags)) + tag
                cells += " " * (x - _width(cells)) + text
                if slot.kind == "stock":
                    count = f"({len(slot.cards)})"
                    counts += " " * (x + _width(text) - len(count) - len(counts)) + count
        lines += [tags, cells] + ([counts] if counts else []) + [""]
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

# said under the board once a game under way is stuck, as the full-screen
# game's end banner says it
NO_MOVES_LEFT = "No moves left - game over. Type u to undo or n for a new deal."

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
        if not g.undo_all():
            return False, "nothing to undo"
        # a save keeps only the newest undo steps, and each step back takes
        # a move off, so a long resumed game stops short of the deal
        return True, "back to the oldest move saved" if g.moves else ""
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
            if ok:
                return ok, ""
            top = g.top(sid)
            # the card as the board names it, unless that would give it away
            card = top.label(g.symbols) if top and top.face_up else f"the face-down card on {tag}"
            reason = g.no_foundation_reason(sid, card, f"on {tag}")
            return ok, reason or f"no foundation move from {tag}"
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
            # why the run asked for won't go, the longest one with no count
            return ok, "" if ok else f"illegal move: {g.why_not(src, dst, count)}"
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


# The console mode that has a Windows console act on ANSI escapes, as other
# terminals do. Windows 10 and later have it, but a console doesn't always
# start with it on.
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def _show_escapes(out) -> tuple[bool, Callable[[], object] | None]:
    """Whether out shows ANSI escapes, and what puts its console back after.

    Off Windows the answer is yes, and so it is for a stream with no file
    behind it, which is taken at its word. A Windows console gets the mode
    that shows them until text mode is done. One too old for that doesn't
    show them, and nor does a file that isn't a console, such as NUL, a
    pipe or a file on disk.
    """
    if sys.platform != "win32":
        return True, None
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(out.fileno()))
    except (AttributeError, OSError, ValueError):
        return True, None
    kernel32 = ctypes.WinDLL("kernel32")
    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False, None
    old = mode.value
    if old & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
        return True, None
    if not kernel32.SetConsoleMode(
        handle, wintypes.DWORD(old | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    ):
        return False, None
    return True, lambda: kernel32.SetConsoleMode(handle, wintypes.DWORD(old))


def _time_ctrl_z(inp, left_out: Callable[[float], object]) -> Callable[[], object] | None:
    """Have Ctrl-Z stop text mode as it would anyway, and then hand left_out
    the seconds it was stopped, so the game's clock can leave them out, as
    AisleRiot's does. Returns what puts the old handler back.

    Only for input from a terminal, where Ctrl-Z is typed, and only where
    it stops the game at all: a shell with no job control starts it with
    SIGTSTP ignored, and Windows has none. Then it returns None.
    """
    tstp = getattr(signal, "SIGTSTP", None)
    isatty = getattr(inp, "isatty", None)
    if tstp is None or not (isatty and isatty()) or signal.getsignal(tstp) == signal.SIG_IGN:
        return None

    def stop(signum: int, frame: object) -> None:
        stopped = time.monotonic()
        # the default stops the process, where this would only come back here
        signal.signal(tstp, signal.SIG_DFL)
        try:
            os.kill(os.getpid(), tstp)  # back from this once fg continues it
        finally:
            signal.signal(tstp, stop)
        left_out(time.monotonic() - stopped)

    old = signal.signal(tstp, stop)
    return lambda: signal.signal(tstp, signal.SIG_DFL if old is None else old)


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
    if stream is None and hasattr(inp, "reconfigure"):
        # a byte stdin's encoding has no character for, as from a Latin-1
        # terminal or a binary paste, is then a bad command, not a crash
        inp.reconfigure(errors="surrogateescape")
    # a cp1252 or ASCII stdout has no suit symbols; letters beat a crash
    symbols = symbols and _can_write(out, "".join(SUIT_SYMBOL.values()))
    theme = camo_theme if camo_theme in camo.THEMES else camo.DEFAULT_THEME
    start = time.monotonic()  # one clock per deal
    recorded = False
    resumed = False
    stuck_said = False  # that no moves are left, since the last move

    def seconds() -> int:
        """This deal's time in whole seconds, as it is printed and stored."""
        return round(time.monotonic() - start)

    def boss() -> None:
        # A screenful of plausible 'work' output instead of the board. On a
        # terminal, wipe the screen and its scrollback if it takes escapes,
        # and fill the height, so no card is left in view; a pipe just gets
        # a block of lines.
        rows = 40
        if out.isatty():
            if shown:
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

    def count(won: bool, secs: int) -> dict:
        """Count the game, once. Returns its line in the history."""
        nonlocal recorded
        with store.signals_held():
            saves.let_go(game_key)  # a game taken up from a save, done with
            _, line = history.record(g, won, secs)
            recorded = True
        return line

    def give_up() -> str:
        """Count a game under way lost. A daily's line to share, as a win
        has one, or ""."""
        if not under_way():
            return ""
        secs = seconds()
        count(False, secs)
        if g.daily:
            return share_line(g.gamedef.name, g.daily, False, secs, g.moves)
        return ""

    def unkept() -> str:
        # a new deal while a game of its kind is saved, which leaves no room
        # to keep this one too
        name = g.gamedef.name
        if keep and game_key in saves.waiting(game_key):
            return f"a saved {name} game is waiting, so this one won't be kept"
        if keep and saves.elsewhere(game_key):
            return f"a saved {name} game is being played somewhere else, so this one won't be kept"
        return ""

    def put_away() -> str:
        # on leaving: kept for next time if it may be, and otherwise lost,
        # with saves.keep's notice saying why; a win not counted yet, as
        # when Ctrl-C comes just as it's made, counts as won. Signals wait
        # until it's done, so one can't cut it off halfway. A deal nobody
        # touched has nothing to keep, so it doesn't wait for the lock, and
        # nor does one already put away, so calling it again does nothing.
        # What give_up has to say of a game lost, or "".
        nonlocal recorded
        won = g.is_won() and not recorded
        if not won and not under_way():
            return ""
        with store.signals_held():
            if won:
                count(True, seconds())
                return ""
            if keep and under_way():
                recorded = saves.keep(g, seconds())
                if recorded:
                    # two lines, so a long game's still fits 80 columns
                    print(f"Saved your {g.gamedef.name} game ({so_far()}).", file=out)
                    print(f"Run soliterm --text --game {game_key} to pick it up.", file=out)
                    return ""
            return give_up()

    def tell(lines: list[str]) -> None:
        # on stderr, leaving stdout as it always is: with stderr closed,
        # Python's is None, and print would take that for stdout
        if not lines or sys.stderr is None:
            return
        out.flush()  # after the lines above, if both go to one place
        try:
            for line in lines:
                print(f"soliterm: {line}", file=sys.stderr, flush=True)
        except OSError:
            # whatever read stderr has gone, which is no reason to stop the
            # game. The line stays in stderr's buffer, where Python's flush
            # at exit would fail on it again, so stderr goes to devnull
            # instead.
            with suppress(OSError):
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stderr.fileno())

    def left_out(stopped: float) -> None:
        nonlocal start
        start += stopped  # stopped with Ctrl-Z, which is no time played

    def say_if_stuck() -> None:
        # once, under the board, as the full-screen game's banner comes up
        # once: after an undo it waits for the next move, as that does
        nonlocal stuck_said
        if not stuck_said and under_way() and g.is_stuck():
            print(NO_MOVES_LEFT, file=out)
            stuck_said = True

    shown, put_back = _show_escapes(out)
    # colour a terminal can't show is only noise, though into a file or a
    # pipe --color still means it
    color = color and (shown or not out.isatty())
    tstp_back = _time_ctrl_z(inp, left_out)
    try:
        try:
            if resume:
                # From the take on, the save is in play until put_away keeps
                # the game again, so a signal waits until there's one to keep
                with store.signals_held():
                    taken = saves.take(game_key)
                    if taken is not None:
                        g, played = taken
                        start -= played
                        resumed = True
            g.symbols = symbols  # hints name cards as the board does
            name = g.gamedef.name
            print(f"{APP_NAME} - {name} - {deal_label(g)} (text mode). Type h for help.", file=out)
            # AisleRiot open, which can still lose games, then this game's
            # own note, then what has gone wrong with the files so far
            warning = store.aisleriot_open_note()
            tell([warning] if warning else [])
            if resumed:
                print(f"Resumed your {name} game ({so_far()}). Type n for a new deal.", file=out)
            elif note := unkept():
                print(note, file=out)
            if sys.stderr is not None:
                tell(store.tell_notices())  # with none, they wait for the way out
            print(file=out)
            print(render_text(g, symbols, color), file=out)
            say_if_stuck()
            for raw in inp:
                line = raw.strip()
                if not line:
                    continue
                moves = g.moves
                _ok, msg = apply_text_command(g, line)
                if msg == "__quit__":
                    if shared := put_away():
                        print(shared, file=out)
                    print("bye", file=out)
                    return 0
                if msg == "__newdeal__":
                    shared = give_up()
                    g.new_game()
                    start, recorded, resumed = time.monotonic(), False, False
                    stuck_said = False
                    msg = f"new deal {g.deal_number}"
                    if shared:
                        msg = f"{shared}\n{msg}"
                    if note := unkept():
                        msg = f"{msg}\n{note}"
                elif msg == "__restart__":
                    # the same hand again: AisleRiot does not count a restart,
                    # and a game taken up from a save goes with it
                    saves.let_go(game_key)
                    g.restart()
                    start, recorded, resumed = time.monotonic(), False, False
                    stuck_said = False
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
                if g.moves > moves:
                    stuck_said = False
                say_if_stuck()
                if g.is_won() and not recorded:
                    secs = seconds()
                    line = count(True, secs)
                    print("Congratulations - you won!", file=out)
                    print(
                        f"Score {g.score} in {store.fmt_time(secs)} ({store.moves_text(g.moves)}).",
                        file=out,
                    )
                    print(f"Share code: {code_of(g)}", file=out)
                    if g.daily:
                        print(share_line(g.gamedef.name, g.daily, True, secs, g.moves), file=out)
                    on_deal = records.deal_text(records.on_this_deal(line, history.games()))
                    if on_deal:
                        print(f"On this deal: {on_deal}", file=out)
                    streak = history.streak_text(game_key)
                    if streak:
                        print(f"{streak}.", file=out)
                    return 0
            # the input ran out: Ctrl-D, or the end of a script
            if shared := put_away():
                print(shared, file=out)
            return 0
        except Exception:
            # the input or the output gone, as when a closing terminal's read
            # fails before its SIGHUP comes, or a bug: the game is kept or
            # counted as it is for q, and the error goes on, not one that
            # doing so ran into. Inside the handler below, so a signal
            # landing meanwhile puts it away again.
            with suppress(Exception):
                put_away()
            raise
    except KeyboardInterrupt:
        # Ctrl-C leaves like q does, minus the traceback, and so do SIGHUP,
        # SIGTERM, Ctrl-Break and a Windows console closing, which the
        # command line turns into this. A stderr that can't be written,
        # with its console gone, doesn't keep the game from being put away.
        with suppress(OSError):
            print(file=sys.stderr)
        try:
            put_away()
        finally:
            # another Ctrl-C, say as it waited for another copy's lock
            if not recorded and (g.is_won() or under_way()):
                print(file=sys.stderr)  # off the line its ^C is on
                store.cut_short(g.gamedef.name)
        return 130
    finally:
        if put_back is not None:
            put_back()
        if tstp_back is not None:
            tstp_back()
