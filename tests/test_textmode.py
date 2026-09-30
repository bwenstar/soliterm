"""Text mode: the board it prints and the commands it takes."""

import ctypes
import errno
import io
import os
import re
import signal
import sys
import types
from datetime import date

import pytest

from soliterm import cli, deals, history, saves, store, textmode
from soliterm.engine import GAME_ORDER, Card, new_solitaire
from soliterm.textmode import render_text

from helpers import (
    OtherCopy,
    Steps,
    board_state,
    clear_board,
    deal,
    from_before_the_counts,
    nothing_in_play,
    saved,
    signal_once_written,
    stalled_klondike,
    steps,
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def played(key, seed, steps=40):
    """A game some good moves in, so there are foundations, fans and 10s about."""
    g = deal(key, seed)
    for _ in range(steps):
        mv = g.best_move()
        if mv is not None:
            g.attempt_move(*mv)
        elif not g.deal():
            break
    return g


def typed(msg):
    """The command a hint tells the player to type, or None."""
    m = re.search(r"type: ([^)]*)\)", msg)
    return m.group(1) if m else None


def blocks(board):
    """The board's slot rows as (tag line, card lines), status line left out."""
    lines = board.splitlines()[1:-1]
    out, cur = [], []
    for line in lines + [""]:
        if line:
            cur.append(line)
        elif cur:
            out.append((cur[0], cur[1:]))
            cur = []
    return out


def ends(line):
    """Where each card token, tag or count on a line ends."""
    return [m.end() for m in re.finditer(r"\[[^\]]*\]|\S+", line)]


# -- the board ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("key", GAME_ORDER)
def test_cards_line_up_under_their_tags(key, seed):
    g = played(key, seed)
    board = ANSI.sub("", render_text(g, symbols=True, color=True))
    for tags, rows in blocks(board):
        edges = ends(tags)
        # a fan shows several cards in one slot, but the top one sits under the tag
        assert set(edges) <= set(ends(rows[0])), board
        for row in rows[1:]:
            assert set(ends(row)) <= set(edges), board
        for row in rows:
            assert all(len(t) == 5 for t in re.findall(r"\[[^\]]*\]", row)), board


KIND_TAG = {
    "stock": "stk",
    "waste": "wst",
    "foundation": "fnd",
    "freecell": "cel",
    "reserve": "rsv",
    "tableau": "",
}


@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_slot_shows_its_id_and_kind(key):
    g = deal(key, 1)
    board = render_text(g, symbols=False)
    shown = {int(sid): kind for kind, sid in re.findall(r"([a-z]*)#(\d+)", board)}
    assert shown == {s.sid: KIND_TAG[s.kind] for s in g.slots}


def test_placed_slots_print_where_the_game_puts_them():
    g = steps()
    top, left, right = g.ids_of("tableau")
    placed = blocks(render_text(g, symbols=False))[1:]
    assert len(placed) == 2  # a row of cards for each row down
    for sid, (down, across) in zip((top, left, right), Steps.SPOTS):
        tags, rows = placed[down]
        x = across * 3  # a half card
        assert tags[x : x + 5] == f"#{sid}".rjust(5)
        assert re.fullmatch(r"\[[^\]]{3}\]", rows[0][x : x + 5])
        assert len(rows) == 1
    # an empty one is left out, as on the board, and so is a row with none
    g.slots[left].cards = []
    g.slots[right].cards = []
    board = render_text(g, symbols=False)
    assert len(blocks(board)) == 2
    assert not re.search(rf"#({left}|{right})\b", board)


@pytest.mark.parametrize("key", GAME_ORDER)
def test_a_hint_names_the_slots_as_the_board_does(key):
    g = deal(key, 1)
    tags = set(re.findall(r"[a-z]*#\d+", render_text(g, symbols=False)))
    for _ in range(30):
        h = g.hint()
        if h is None:
            break
        if h[0] == h[1]:
            g.deal()
            continue
        msg = textmode._hint_message(g)
        named = re.findall(r"[a-z]*#\d+", msg)
        assert named == [textmode.slot_tag(g, h[0]), textmode.slot_tag(g, h[1])], msg
        assert set(named) <= tags, msg
        assert textmode.apply_text_command(g, typed(msg))[0], msg


# -- hints ------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("key", GAME_ORDER)
def test_typing_a_hint_back_makes_that_move(key, seed):
    g = deal(key, seed)
    for _ in range(30):
        h = g.hint()
        if h is None:
            break
        src, dst, _ = h
        msg = textmode._hint_message(g)
        cmd = typed(msg)
        assert cmd, msg
        mv = g.best_move()
        want = g.clone()
        if src == dst:
            want.deal()
        elif mv is not None and mv[:2] == (src, dst):
            want.attempt_move(*mv)
        else:
            want = None  # a hint that is not the best move
        before = len(g.cards(dst))
        ok, out = textmode.apply_text_command(g, cmd)
        assert ok, f"{msg!r} -> {out!r}"
        if want is not None:
            assert board_state(g) == board_state(want), msg
        else:
            assert len(g.cards(dst)) > before, msg


def test_typing_a_setup_hint_back_moves_just_the_cards_it_names():
    # 28 hints into this Yukon deal the hint is to move K♣ alone into an
    # empty column, which scores nothing itself but sets up the next move;
    # a bare "7 6" would take the whole pile from the Q♣ above it instead
    g = deal("yukon", 4)
    for _ in range(28):
        g.attempt_move(*g.hint_move())
    src, dst, n = g.hint_move()
    assert g.best_move() is None and n < g.default_pickup(src)
    want = g.clone()
    want.attempt_move(src, dst, n)
    msg = textmode._hint_message(g)
    ok, out = textmode.apply_text_command(g, typed(msg))
    assert ok, f"{msg!r} -> {out!r}"
    assert board_state(g) == board_state(want), msg


def test_a_move_without_a_count_lifts_as_much_as_will_land():
    g = deal("klondike", 1)
    clear_board(g)
    t, f = g.ids_of("tableau")[0], g.ids_of("foundation")[0]
    g.slots[t].cards = [Card(3, "S", True), Card(2, "D", True)]
    g.slots[f].cards = [Card(1, "D", True)]
    ok, _ = textmode.apply_text_command(g, f"{t} {f}")
    assert ok
    assert [str(c) for c in g.cards(f)] == ["AD", "2D"]
    assert [str(c) for c in g.cards(t)] == ["3S"]


# -- commands ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd,says",
    [
        ("f 9", "no foundation move from #9"),
        ("cc 9", "double-clicking #9 does nothing"),
        ("c 2", "clicking fnd#2 does nothing"),
        ("a", "nothing to autoplay"),
    ],
)
def test_a_command_that_does_nothing_says_so(cmd, says):
    g = deal("klondike", 2)
    before = g.serialize()
    ok, msg = textmode.apply_text_command(g, cmd)
    assert (ok, msg) == (False, says)
    assert g.serialize() == before


@pytest.mark.parametrize("symbols, five", [(True, "5\u2665"), (False, "5H")])
@pytest.mark.parametrize(
    "key, says",
    [("golf", "{} doesn't go on the waste"), ("scorpion", "Scorpion has no foundations")],
)
def test_f_in_a_game_with_no_foundations_says_so(key, says, symbols, five):
    g = deal(key, 1)
    g.symbols = symbols  # as run_text sets it
    clear_board(g)
    g.slots[2].cards = [Card(5, "H", True)]
    for waste in g.ids_of("waste"):
        g.slots[waste].cards = [Card(9, "S", True)]
    # the card as the board and the hints name it
    assert textmode.apply_text_command(g, "f 2") == (False, says.format(five))


def test_f_on_a_face_down_card_does_not_name_it():
    g = deal("triplepeaks", 1)
    covered = g.ids_of("tableau")[0]  # the top of the first peak
    assert not g.top(covered).face_up
    assert textmode.apply_text_command(g, f"f {covered}") == (
        False,
        f"the face-down card on #{covered} doesn't go on the waste",
    )


@pytest.mark.parametrize("key", ["golf", "triplepeaks"])
def test_f_with_no_card_to_play_names_none(key):
    g = deal(key, 1)
    clear_board(g)
    waste = g.ids_of("waste")[0]
    g.slots[waste].cards = [Card(9, "S", True)]
    empty = g.ids_of("tableau")[0]
    tag = textmode.slot_tag(g, empty)
    assert textmode.apply_text_command(g, f"f {empty}") == (
        False,
        f"nothing on {tag} goes on the waste",
    )
    tag = textmode.slot_tag(g, waste)
    assert textmode.apply_text_command(g, f"f {waste}") == (
        False,
        f"nothing on {tag} goes on the waste",
    )


def test_text_a_finishes_the_game():
    g = stalled_klondike()
    assert textmode.apply_text_command(g, "a") == (True, "autoplayed 37")
    assert g.is_won()


def test_text_a_still_autoplays_when_it_cant_finish():
    g = stalled_klondike(blocked=True)
    assert textmode.apply_text_command(g, "a") == (True, "autoplayed 1")
    assert not g.is_won()


@pytest.mark.parametrize("cmd", ["99 2", "9 99", "9 99 1", "c 99", "cc 99", "f 99"])
def test_a_slot_that_does_not_exist_is_named(cmd):
    g = deal("klondike", 1)
    ok, msg = textmode.apply_text_command(g, cmd)
    assert (ok, msg) == (False, "no slot 99 (slots are 0-12)")


@pytest.mark.parametrize("cmd", ["N", "restart", "Restart"])
def test_capital_n_and_restart_start_this_deal_over(cmd, capsys):
    g = new_solitaire("golf")
    seed, start = g.deal_number, board_state(g)
    textmode.run_text(g, False, "golf", stream=io.StringIO(f"d\n{cmd}\nq\n"))
    assert (g.deal_number, board_state(g), g.moves) == (seed, start, 0)
    assert "restarted this deal" in capsys.readouterr().out.splitlines()


def test_small_n_still_deals_a_new_hand(capsys):
    g = new_solitaire("golf")
    seed = g.deal_number
    textmode.run_text(g, False, "golf", stream=io.StringIO("n\nq\n"))
    assert g.deal_number != seed
    assert f"new deal {g.deal_number}" in capsys.readouterr().out.splitlines()


def test_the_text_header_names_the_deal(capsys):
    g = deal("klondike", 48213)
    textmode.run_text(g, False, "klondike", stream=io.StringIO("q\n"))
    header = capsys.readouterr().out.splitlines()[0]
    assert header == "Soliterm - Klondike - Deal 48213 (text mode). Type h for help."


def test_the_text_header_names_a_daily(capsys):
    g = deals.deal_game(deals.daily("klondike", date(2026, 9, 24)), {})
    textmode.run_text(g, False, "klondike", stream=io.StringIO("q\n"))
    header = capsys.readouterr().out.splitlines()[0]
    assert header == "Soliterm - Klondike - Daily 2026-09-24 (text mode). Type h for help."


def test_n_says_the_new_deal_number(capsys):
    g = deal("klondike", 48213)
    textmode.run_text(g, False, "klondike", stream=io.StringIO("n\nq\n"))
    assert "new deal 48214" in capsys.readouterr().out.splitlines()


def test_letters_whose_case_means_nothing_work_in_either_case():
    g = deal("golf", 1)
    assert textmode.apply_text_command(g, "D") == (True, "")
    assert textmode.apply_text_command(g, "U") == (True, "")
    assert textmode.apply_text_command(g, "Q") == (True, "__quit__")


def test_text_undo_all_and_redo_all():
    g = deal("golf", 1)
    start = g.serialize()
    assert textmode.apply_text_command(g, "undo all") == (False, "nothing to undo")
    g.deal()
    g.deal()
    end = g.serialize()
    assert textmode.apply_text_command(g, "undo all") == (True, "")
    assert g.serialize() == start
    assert textmode.apply_text_command(g, " Redo  ALL") == (True, "")
    assert g.serialize() == end
    assert textmode.apply_text_command(g, "redo all") == (False, "nothing to redo")
    assert "undo all" in textmode.TEXT_HELP and "redo all" in textmode.TEXT_HELP


def test_text_undo_all_says_when_a_resumed_game_stops_short_of_the_deal(monkeypatch):
    # a save keeps only the newest undo steps
    monkeypatch.setattr(saves, "SAVED_STEPS", 3)
    g = deal("klondike", 4)
    for _ in range(5):
        g.deal()
    assert saves.keep(g, 42)
    g, _seconds = saves.take("klondike")
    assert textmode.apply_text_command(g, "undo all") == (True, "back to the oldest move saved")
    assert g.moves == 2
    # back at the deal it says nothing, as before
    g.new_game()
    g.deal()
    assert textmode.apply_text_command(g, "undo all") == (True, "")


def test_text_U_still_undoes_one():
    g = deal("golf", 1)
    g.deal()
    one = g.serialize()
    g.deal()
    assert textmode.apply_text_command(g, "U") == (True, "")
    assert g.serialize() == one


def test_the_help_lists_restart():
    assert "N / restart" in textmode.TEXT_HELP


@pytest.mark.parametrize(
    "encoding,suits",
    [
        ("cp1252", "SHDC"),
        ("latin-1", "SHDC"),
        ("ascii", "SHDC"),
        ("utf-8", "♠♥♦♣"),
    ],
)
def test_suits_fall_back_to_letters_when_stdout_cannot_show_them(encoding, suits, monkeypatch):
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding=encoding)
    monkeypatch.setattr("sys.stdout", out)
    g = deal("klondike", 1)
    assert textmode.run_text(g, True, "klondike", stream=io.StringIO("q\n")) == 0
    out.flush()
    board = raw.getvalue().decode(encoding)
    shown = {m[-1] for m in re.findall(r"\[ *(?:10|[A2-9JQK])(.)\]", board)}
    assert shown and shown <= set(suits)


def test_the_hint_uses_letters_too_when_stdout_cannot_show_symbols(monkeypatch):
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="ascii")
    monkeypatch.setattr("sys.stdout", out)
    g = deal("klondike", 1)
    assert textmode.run_text(g, True, "klondike", stream=io.StringIO("hint\nq\n")) == 0
    out.flush()
    hint = next(
        line for line in raw.getvalue().decode("ascii").splitlines() if line.startswith("Hint: ")
    )
    assert "Move AD to its foundation" in hint


# -- a Windows console -------------------------------------------------------------------

HANDLE = 0x44  # the handle stdout's file number has, as msvcrt gives it


class Terminal(io.StringIO):
    def isatty(self):
        return True


class ConsoleOut(Terminal):
    """sys.stdout on Windows: a terminal, with a file number behind it."""

    def fileno(self):
        return 1


class PipeOut(ConsoleOut):
    def isatty(self):
        return False


class Kernel32:
    """The console calls text mode makes, on a console whose mode is `mode`.

    With `vt` False it's a Windows too old for the mode that shows escapes,
    and with `console` False the handle isn't a console at all.
    """

    def __init__(self, out, mode=3, vt=True, console=True):
        self.out, self.mode, self.vt, self.console = out, mode, vt, console
        self.set = []  # each mode set, with all that had been written by then

    def GetConsoleMode(self, handle, ref):
        if handle.value != HANDLE or not self.console:
            return 0
        ref._obj.value = self.mode
        return 1

    def SetConsoleMode(self, handle, mode):
        if handle.value != HANDLE or not self.console or (mode.value & 4 and not self.vt):
            return 0
        self.mode = mode.value
        self.set.append((self.mode, self.out.getvalue()))
        return 1


@pytest.fixture
def windows(monkeypatch):
    """Makes this Windows, with `out` as stdout on the console it returns."""

    def on(out, **console):
        kernel32 = Kernel32(out, **console)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setitem(
            sys.modules, "msvcrt", types.SimpleNamespace(get_osfhandle={1: HANDLE}.get)
        )
        monkeypatch.setattr(ctypes, "WinDLL", {"kernel32": kernel32}.get, raising=False)
        monkeypatch.setattr(
            textmode.shutil,
            "get_terminal_size",
            lambda fallback=(80, 24): os.terminal_size((80, 30)),
        )
        return kernel32

    return on


def after_the_board(text):
    """The lines after the last board printed."""
    lines = text.splitlines()
    last = max(i for i, line in enumerate(lines) if "score=" in line)
    return lines[last + 1 :]


def leaving(leave):
    """A deal from the stock, then `leave`: a command or what's raised."""
    yield "d\n"
    if isinstance(leave, str):
        yield leave
    else:
        raise leave


@pytest.mark.parametrize(
    "leave,rc",
    [("q\n", 0), (KeyboardInterrupt(), 130)],
    ids=["q", "ctrl-c"],
)
def test_a_windows_console_shows_the_colours_and_gets_its_mode_back(leave, rc, windows):
    out = ConsoleOut()
    kernel32 = windows(out)
    g = deal("golf", 7)
    assert textmode.run_text(g, False, "golf", stream=leaving(leave), color=True) == rc
    # on before the first line and back after the last
    assert kernel32.set == [(3 | 4, ""), (3, out.getvalue())]
    assert ANSI.search(out.getvalue())


def test_the_console_mode_goes_back_after_an_error_too(windows):
    kernel32 = windows(ConsoleOut())
    g = deal("golf", 7)
    with pytest.raises(OSError, match="gone"):
        textmode.run_text(g, False, "golf", stream=leaving(OSError("gone")), color=True)
    assert [mode for mode, _ in kernel32.set] == [3 | 4, 3]


def test_a_console_already_showing_escapes_is_left_as_it_is(windows):
    out = ConsoleOut()
    kernel32 = windows(out, mode=3 | 4)
    g = deal("golf", 7)
    assert textmode.run_text(g, False, "golf", stream=io.StringIO("b\nq\n"), color=True) == 0
    assert kernel32.set == []
    assert ANSI.search(out.getvalue())
    assert "\x1b[H\x1b[2J\x1b[3J" in out.getvalue()


@pytest.mark.parametrize(
    "console", [{"vt": False}, {"console": False}], ids=["old-windows", "not-a-console"]
)
def test_a_terminal_that_cant_show_escapes_gets_none(console, windows):
    out = ConsoleOut()
    kernel32 = windows(out, **console)
    g = deal("golf", 7)
    assert textmode.run_text(g, False, "golf", stream=io.StringIO("b\nq\n"), color=True) == 0
    assert "\x1b" not in out.getvalue()
    assert kernel32.mode == 3
    # the boss screen can't clear the board away, but still fills the screen
    assert len(after_the_board(out.getvalue())) == 30 + 1  # and then "bye"


def test_colour_asked_for_into_a_pipe_keeps_its_codes(windows):
    out = PipeOut()
    windows(out, console=False)
    g = deal("golf", 7)
    assert textmode.run_text(g, False, "golf", stream=io.StringIO("q\n"), color=True) == 0
    assert ANSI.search(out.getvalue())


def test_on_windows_a_stdout_with_no_file_behind_it_is_taken_as_it_is(windows):
    out = Terminal()
    kernel32 = windows(out)
    g = deal("golf", 7)
    assert textmode.run_text(g, False, "golf", stream=io.StringIO("b\nq\n"), color=True) == 0
    assert kernel32.set == []
    assert ANSI.search(out.getvalue())
    assert "\x1b[H\x1b[2J\x1b[3J" in out.getvalue()


# -- results ----------------------------------------------------------------------------


def play_text(key, script, seed=1):
    """Runs a text session on a seeded deal; returns the game and its stats."""
    g = deal(key, seed)
    assert textmode.run_text(g, False, key, stream=io.StringIO(script)) == 0
    return g, store.get_stat(key)


@pytest.mark.parametrize(
    "script,lost",
    [
        ("d\nq\n", 1),  # quit after a move
        ("d\n", 1),  # the input ran out after a move
        ("d\nn\nq\n", 1),  # the deal walked away from counts, the new one does not
        ("d\nn\nd\nq\n", 2),  # both deals were played
        ("q\n", 0),  # never moved
        ("n\nq\n", 0),
        ("d\nN\nq\n", 0),  # starting the same deal over is not a loss
        ("d\nN\nd\nq\n", 1),
    ],
)
def test_leaving_a_started_deal_counts_as_a_loss(script, lost, capsys):
    _, s = play_text("klondike", script)
    assert (s["wins"], s["total"]) == (0, lost)


def one_card_from_won(g):
    """Every Klondike card home but the king of spades, which is on a column."""
    fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    for f, suit in zip(fids, "SHDC"):
        g.slots[f].cards = [Card(r, suit, True) for r in range(1, 14)]
    g.slots[fids[0]].cards.pop()
    g.slots[tids[0]].cards = [Card(13, "S", True)]
    return tids[0]


class Clock:
    """Stands in for the time module in textmode; tests move it by hand."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    time = monotonic


@pytest.mark.parametrize("again,total", [("n", 2), ("N", 1)])
@pytest.mark.parametrize("secs,shown", [(10.4, 10), (10.6, 11)])
def test_a_win_is_timed_from_its_own_deal(again, total, secs, shown, monkeypatch, capsys):
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)
    g = deal("klondike", 1)

    def script():
        clock.now += 100  # time spent on the deal given up
        yield "d\n"
        yield again + "\n"
        clock.now += secs
        yield f"f {one_card_from_won(g)}\n"

    assert textmode.run_text(g, False, "klondike", stream=script()) == 0
    s = store.get_stat("klondike")
    assert (s["wins"], s["total"], s["best"], s["worst"]) == (1, total, shown, shown)
    assert f"in {store.fmt_time(shown)} " in capsys.readouterr().out


class Typed:
    """What a script yields, typed at a terminal."""

    def __init__(self, lines):
        self.lines = lines

    def __iter__(self):
        return iter(self.lines)

    def isatty(self):
        return True


needs_sigtstp = pytest.mark.skipif(not hasattr(signal, "SIGTSTP"), reason="needs POSIX signals")


@needs_sigtstp
def test_the_time_stopped_with_ctrl_z_is_left_out(monkeypatch, capsys):
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)
    stops = []

    def kill(pid, signum):
        # the default is back for the stop itself, which lasts an hour
        assert (pid, signum) == (os.getpid(), signal.SIGTSTP)
        stops.append(signal.getsignal(signal.SIGTSTP))
        clock.now += 3600

    monkeypatch.setattr(os, "kill", kill)
    g = deal("klondike", 1)

    def ctrl_z():
        handler = signal.getsignal(signal.SIGTSTP)
        assert callable(handler), "nothing handles Ctrl-Z"
        handler(signal.SIGTSTP, None)

    def script():
        yield "d\n"
        clock.now += 10
        ctrl_z()
        clock.now += 5
        ctrl_z()  # and once more, as it is handled again after
        yield f"f {one_card_from_won(g)}\n"

    assert textmode.run_text(g, False, "klondike", stream=Typed(script())) == 0
    assert stops == [signal.SIG_DFL, signal.SIG_DFL]
    assert "in 0:15 " in capsys.readouterr().out


@needs_sigtstp
@pytest.mark.parametrize("tty", [True, False])
@pytest.mark.parametrize("before", [signal.SIG_DFL, signal.SIG_IGN])
def test_ctrl_z_is_handled_only_at_a_terminal_that_can_stop(tty, before):
    # a shell with no job control starts its commands with SIGTSTP ignored
    during = []

    def script():
        during.append(signal.getsignal(signal.SIGTSTP))
        yield "q\n"

    old = signal.signal(signal.SIGTSTP, before)
    try:
        stream = Typed(script()) if tty else script()
        assert textmode.run_text(deal("golf", 1), False, "golf", stream=stream) == 0
        handled = tty and before == signal.SIG_DFL
        assert callable(during[0]) == handled
        assert signal.getsignal(signal.SIGTSTP) == before
    finally:
        signal.signal(signal.SIGTSTP, old)


@pytest.mark.parametrize(
    "n,text", [(0, "0 moves"), (1, "1 move"), (2, "2 moves"), (31, "31 moves")]
)
def test_moves_text(n, text):
    assert store.moves_text(n) == text


def test_a_win_in_one_move_says_1_move(capsys):
    g = deal("klondike", 1)
    script = io.StringIO(f"f {one_card_from_won(g)}\n")
    assert textmode.run_text(g, False, "klondike", stream=script) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(re.fullmatch(r"Score \d+ in \d+:\d\d \(1 move\)\.", line) for line in lines)


def test_a_text_win_prints_the_share_code(capsys):
    g = deal("klondike", 5)
    script = io.StringIO(f"f {one_card_from_won(g)}\n")
    assert textmode.run_text(g, False, "klondike", stream=script) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2].startswith("Score ")
    assert lines[-1] == "Share code: klondike:5"


def test_text_mode_prints_the_share_line_after_a_daily_win(monkeypatch, capsys):
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)
    g = deals.deal_game(deals.daily("klondike", date(2026, 9, 24)), {})

    def script():
        clock.now += 192
        yield f"f {one_card_from_won(g)}\n"

    assert textmode.run_text(g, False, "klondike", stream=script()) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2:] == [
        "Share code: klondike:20260924",
        "Soliterm daily 2026-09-24, Klondike: won in 3:12, 1 move",
    ]


# what text mode says once a command leaves no moves
NO_MOVES = textmode.NO_MOVES_LEFT


def said_after_each_board(out):
    """For each board printed, the opening one first, whether it was said
    right after it that no moves are left."""
    return [part.startswith(NO_MOVES + "\n") for part in re.split(r"(?m)^score=.*\n", out)[1:]]


def one_move_left():
    """Golf with one move to make, the 6C onto the 5H, and none after it,
    and the command that makes it."""
    g = deal("golf", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    waste = g.ids_of("waste")[0]
    g.slots[waste].cards = [Card(5, "H", True)]
    g.slots[t[0]].cards = [Card(13, "S", True), Card(6, "C", True)]
    for sid, rank in zip(t[1:], (9, 10, 11, 12, 9, 10)):
        g.slots[sid].cards = [Card(rank, "SH"[sid % 2], True)]
    return g, f"{t[0]} {waste}"


def test_text_mode_says_when_no_moves_are_left(capsys):
    g, move = one_move_left()
    script = f"{move}\np\nhint\n9 9\nq\n"
    assert textmode.run_text(g, False, "golf", stream=io.StringIO(script)) == 0
    out = capsys.readouterr().out
    # once, right after the board the move leaves, and not again while
    # nothing changes
    assert said_after_each_board(out) == [False, True, False, False, False]
    lines = out.splitlines()
    at = lines.index(NO_MOVES)
    assert re.match(r"score=\d+ moves=1 \|", lines[at - 1])
    assert len(NO_MOVES) <= 80


def test_no_moves_left_is_said_again_once_the_move_is_made_again(capsys):
    g, move = one_move_left()
    script = f"{move}\nu\n{move}\nu\nr\nq\n"
    assert textmode.run_text(g, False, "golf", stream=io.StringIO(script)) == 0
    said = said_after_each_board(capsys.readouterr().out)
    assert said == [False, True, False, True, False, True]


def test_a_dead_end_taken_back_to_is_not_said_again_until_a_move(capsys):
    # Scorpion with the stock dealt and two Kings that can only slide
    # between empty columns: a dead end after every move and every undo.
    # As with the full-screen game's banner, which u takes away until the
    # next move, it's said again only after a move. The game is under way
    # from the start, so it's said under the first board too.
    g = deal("scorpion", 1)
    clear_board(g)
    c = g.ids_of("tableau")
    g.slots[c[0]].cards = [Card(13, "H", True), Card(2, "C", True)]
    g.slots[c[1]].cards = [Card(13, "S", True), Card(3, "D", True)]
    g.moves = 5  # a game under way
    assert g.is_stuck()
    script = f"{c[0]} {c[2]} 2\nu\np\n{c[0]} {c[3]} 2\nq\n"
    assert textmode.run_text(g, False, "scorpion", stream=io.StringIO(script)) == 0
    said = said_after_each_board(capsys.readouterr().out)
    assert said == [True, True, False, False, True]


@pytest.mark.parametrize("again", ["n", "N"])
def test_a_deal_played_afresh_has_moves_left(capsys, again):
    g, move = one_move_left()
    script = f"{move}\n{again}\nq\n"
    assert textmode.run_text(g, False, "golf", stream=io.StringIO(script)) == 0
    assert said_after_each_board(capsys.readouterr().out) == [False, True, False]


def test_a_resumed_game_with_no_moves_left_says_so_under_its_board(monkeypatch, capsys):
    # as the full-screen game shows its banner at once. The position isn't
    # one a deal could come to, so it's handed over as the save would be.
    g, move = one_move_left()
    g.attempt_move(*map(int, move.split()))
    monkeypatch.setattr(saves, "take", lambda key: (g, 30))
    resumed = textmode.run_text(
        deal("golf", 1), False, "golf", stream=io.StringIO("q\n"), keep=True, resume=True
    )
    assert resumed == 0
    out = capsys.readouterr().out
    assert "Resumed your Golf game" in out
    assert said_after_each_board(out) == [True]
    assert "Saved your Golf game" in out.split(NO_MOVES)[1]


def a_daily(monkeypatch):
    """Klondike's daily deal of 2026-09-24, and what's typed at it as a
    script goes, the first line 1:15 in."""
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)

    def typed(script):
        clock.now += 75  # at the first read, once the game's clock is going
        yield from script.splitlines(keepends=True)

    return deals.deal_game(deals.daily("klondike", date(2026, 9, 24)), {}), typed


DAILY_LOST = "Soliterm daily 2026-09-24, Klondike: stuck after 1:15, 1 move"


@pytest.mark.parametrize(
    "script, last",
    [("d\nq\n", ["bye"]), ("d\n", []), ("d\nn\nq\n", None)],
    ids=["q", "the end of the input", "n"],
)
def test_a_daily_counted_lost_prints_its_share_line(monkeypatch, capsys, script, last):
    g, typed = a_daily(monkeypatch)
    assert textmode.run_text(g, False, "klondike", stream=typed(script)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert store.get_stat("klondike")["total"] == 1
    at = lines.index(DAILY_LOST)
    if last is None:
        # before the new deal's line
        assert lines[at + 1] == f"new deal {g.deal_number}"
    else:
        assert lines[at + 1 :] == last
    assert lines.count(DAILY_LOST) == 1


@pytest.mark.parametrize("script", ["q\n", "d\nN\nq\n", "n\nd\nq\n"])
def test_a_daily_not_counted_lost_prints_no_share_line(monkeypatch, capsys, script):
    # never moved, dealt again from the start, or a new deal lost instead
    g, typed = a_daily(monkeypatch)
    assert textmode.run_text(g, False, "klondike", stream=typed(script)) == 0
    assert "Soliterm daily" not in capsys.readouterr().out


def test_a_daily_kept_for_later_prints_no_share_line(monkeypatch, capsys):
    g, typed = a_daily(monkeypatch)
    assert textmode.run_text(g, False, "klondike", stream=typed("d\nq\n"), keep=True) == 0
    out = capsys.readouterr().out
    assert "Saved your Klondike game" in out and "Soliterm daily" not in out
    assert store.get_stat("klondike")["total"] == 0


def test_a_daily_that_cant_be_kept_prints_its_share_line(monkeypatch, capsys):
    # a saved Klondike game waits, so this one is counted lost instead
    keep_one()
    g, typed = a_daily(monkeypatch)
    assert textmode.run_text(g, False, "klondike", stream=typed("d\nq\n"), keep=True) == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [DAILY_LOST, "bye"]


def a_damaged_config():
    """A config.json that isn't JSON, set aside as the command line reads
    it. What that says."""
    os.makedirs(store.config_dir(), exist_ok=True)
    with open(store.config_path(), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    store.load_config()
    (notice,) = store.notices()
    return notice


def test_text_mode_says_all_it_starts_with_before_the_board(monkeypatch):
    # AisleRiot open, which can still lose games, then this game's note,
    # then what went wrong with the files
    told = [store.AISLERIOT_OPEN]
    monkeypatch.setattr(store, "aisleriot_open_note", lambda: told.pop() if told else None)
    notice = a_damaged_config()
    keep_one()
    both = io.StringIO()
    monkeypatch.setattr(sys, "stdout", both)
    monkeypatch.setattr(sys, "stderr", both)
    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=Typed(["q\n"]), keep=True) == 0
    assert both.getvalue().splitlines()[:6] == [
        "Soliterm - Klondike - Deal 1 (text mode). Type h for help.",
        f"soliterm: {store.AISLERIOT_OPEN}",
        "a saved Klondike game is waiting, so this one won't be kept",
        f"soliterm: {notice}",
        "",
        "=== Klondike ===",
    ]


@pytest.mark.parametrize(
    "before, streak",
    [
        ([True], ["2 wins in a row, your longest yet."]),
        ([True, True, True, False, True], ["2 wins in a row (longest 3)."]),
        ([], []),
        ([True, False], []),
    ],
    ids=["two in a row", "short of the longest", "a first win", "one after a loss"],
)
def test_a_text_win_prints_the_streak(before, streak, capsys):
    for won in before:
        history.record(deal("klondike", 1), won, 60)
    g = deal("klondike", 1)
    script = io.StringIO(f"f {one_card_from_won(g)}\n")
    assert textmode.run_text(g, False, "klondike", stream=script) == 0
    lines = capsys.readouterr().out.splitlines()
    score = [i for i, line in enumerate(lines) if line.startswith("Score ")]
    # the wins before were on this deal, and slower
    deal_line = ["On this deal: a new best, was 1:00, 0 moves"] if True in before else []
    assert lines[score[0] + 1 :] == ["Share code: klondike:1", *deal_line, *streak]


def won_before(seconds, moves, number=1, **options):
    """A win of Klondike's deal `number` in the history, in seconds and moves."""
    g = deal("klondike", number, **options)
    g.moves = moves
    history.record(g, True, seconds)


@pytest.mark.parametrize(
    "before, said",
    [
        ([], []),
        ([(300, 150)], ["On this deal: a new best, was 5:00, 150 moves"]),
        ([(300, 150), (5, 30), (40, 3)], ["On this deal: your best is 0:05, 30 moves"]),
        # the same time, and the moves decide
        ([(192, 40)], ["On this deal: a new best, was 3:12, 40 moves"]),
        ([(192, 0)], ["On this deal: your best is 3:12, 0 moves"]),
        ([(192, 1)], ["On this deal: your best is 3:12, 1 move"]),
        # another deal, or the same one with other options
        ([(300, 150, 2), (300, 150, 1, 3)], []),
    ],
    ids=["first", "faster", "slower", "fewer-moves", "more-moves", "the-same", "other-deals"],
)
def test_a_text_win_says_how_it_stood_on_its_deal(before, said, monkeypatch, capsys):
    for seconds, moves, *deal_draw in before:
        number, *draw = deal_draw or [1]
        won_before(seconds, moves, number, **({"draw": draw[0]} if draw else {}))
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)
    g = deal("klondike", 1)

    def script():
        clock.now += 192
        yield f"f {one_card_from_won(g)}\n"

    assert textmode.run_text(g, False, "klondike", stream=script()) == 0
    lines = capsys.readouterr().out.splitlines()
    assert f"Score {g.score} in 3:12 (1 move)." in lines
    at = lines.index("Share code: klondike:1")
    assert [line for line in lines[at + 1 :] if "wins in a row" not in line] == said


def test_a_text_daily_stands_on_the_same_deal_played_plainly(monkeypatch, capsys):
    won_before(300, 150, 20260924)
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)
    g = deals.deal_game(deals.daily("klondike", date(2026, 9, 24)), {})

    def script():
        clock.now += 192
        yield f"f {one_card_from_won(g)}\n"

    assert textmode.run_text(g, False, "klondike", stream=script()) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-4:] == [
        "Share code: klondike:20260924",
        "Soliterm daily 2026-09-24, Klondike: won in 3:12, 1 move",
        "On this deal: a new best, was 5:00, 150 moves",
        "2 wins in a row, your longest yet.",
    ]


def test_a_text_win_played_again_within_the_second_has_the_first_to_beat(monkeypatch, capsys):
    # as the same script piped in twice does: the two lines are the same
    monkeypatch.setattr(history, "now", lambda: "2026-09-24T14:05:11+10:00")
    monkeypatch.setattr(textmode, "time", Clock())
    for _ in range(2):
        g = deal("klondike", 1)
        typed = iter([f"f {one_card_from_won(g)}\n"])
        assert textmode.run_text(g, False, "klondike", stream=typed) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line for line in lines if line.startswith("On this deal")] == [
        "On this deal: your best is 0:01, 1 move"
    ]
    first, again = history.games()
    assert first == again


@pytest.mark.parametrize("script", ["d\nq\n", "d\nn\nq\n", "d\n"])
def test_a_text_loss_says_nothing_about_its_deal(monkeypatch, capsys, script):
    g, typed = a_daily(monkeypatch)
    won_before(60, 40, g.deal_number)
    assert textmode.run_text(g, False, "klondike", stream=typed(script)) == 0
    out = capsys.readouterr().out
    assert store.get_stat("klondike")["total"] == 2
    assert DAILY_LOST in out and "On this deal" not in out


def test_ctrl_c_as_a_win_is_shown_still_counts_it(monkeypatch):
    real = textmode.render_text

    def render(g, *args):
        if g.is_won():
            raise KeyboardInterrupt  # before the win is counted
        return real(g, *args)

    monkeypatch.setattr(textmode, "render_text", render)
    g = deal("klondike", 1)
    script = io.StringIO(f"f {one_card_from_won(g)}\n")
    assert textmode.run_text(g, False, "klondike", stream=script) == 130
    s = store.get_stat("klondike")
    assert (s["wins"], s["total"]) == (1, 1)


def test_text_games_go_in_the_history(capsys):
    play_text("klondike", "d\nq\n")
    g = deal("klondike", 1)
    script = io.StringIO(f"f {one_card_from_won(g)}\n")
    assert textmode.run_text(g, False, "klondike", stream=script) == 0
    assert [(e["result"], e["moves"], e["deal"]) for e in history.games()] == [
        ("lost", 1, 1),
        ("won", 1, 1),
    ]


@pytest.mark.parametrize("before,lost", [(["d\n"], 1), (["p\n"], 0)])
def test_ctrl_c_leaves_quietly_and_counts_like_quitting(before, lost, capsys):
    def script():
        yield from before
        raise KeyboardInterrupt

    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=script()) == 130
    s = store.get_stat("klondike")
    assert (s["wins"], s["total"]) == (0, lost)
    assert "Traceback" not in capsys.readouterr().err


# -- saved games ---------------------------------------------------------------------------


# what leaving says of a game it saved
KEPT = (
    "Saved your Klondike game (0:00, 1 move).\nRun soliterm --text --game klondike to pick it up."
)


def test_ctrl_c_saves_a_game_it_may_keep(monkeypatch, capsys):
    monkeypatch.setattr(textmode, "time", Clock())

    def script():
        yield "d\n"
        raise KeyboardInterrupt

    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=script(), keep=True) == 130
    assert saves.waiting() == {"klondike": {"seconds": 0, "moves": 1}}
    assert store.get_stat("klondike")["total"] == 0
    out, err = capsys.readouterr()
    assert out.endswith(f"\n{KEPT}\n")
    assert err == "\n"


@pytest.mark.parametrize("key", GAME_ORDER)
def test_the_saved_game_line_fits_80_columns(monkeypatch, capsys, key):
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)

    def script():
        clock.now += 5025  # a long game, over an hour
        yield "q\n"

    g = deal(key, 1)
    g.moves = 1234
    textmode.run_text(g, False, key, stream=script(), keep=True)
    out = capsys.readouterr().out
    said = out[out.index("Saved your") : out.index("\nbye\n")].splitlines()
    assert f"({store.fmt_time(5025)}, 1234 moves)" in said[0]
    assert f"soliterm --text --game {key}" in said[-1]
    assert max(len(line) for line in said) <= 80


posix_signals = pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")


@posix_signals
def test_ctrl_c_as_q_saves_the_game_keeps_it_once(monkeypatch, capsys, ctrl_c):
    signal_once_written(monkeypatch, saves.save_path("klondike"), signal.SIGINT)
    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=iter(["d\n", "q\n"]), keep=True) == 130
    assert KEPT in capsys.readouterr().out
    assert saves.waiting()["klondike"]["moves"] == 1
    assert store.get_stat("klondike")["total"] == 0
    assert store.notices() == []


@pytest.mark.skipif(store.fcntl is None, reason="needs flock")
@pytest.mark.parametrize("keep", [True, False])
def test_ctrl_c_twice_as_q_waits_for_the_lock_says_what_was_lost(keep, capsys):
    os.makedirs(store.data_dir(), exist_ok=True)

    def ctrl_c():
        raise KeyboardInterrupt  # as it waits

    g = deal("klondike", 1)
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:

        def script():
            yield "d\n"
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_EX)  # another copy takes it
            yield "q\n"

        with store.lock_wait_note(ctrl_c), pytest.raises(KeyboardInterrupt):
            textmode.run_text(g, False, "klondike", stream=script(), keep=keep)
    assert saves.waiting() == {}
    assert store.get_stat("klondike")["total"] == 0
    assert store.notices() == [
        "leaving was cut short, so your Klondike game was neither saved nor counted"
    ]
    # a line for each ^C, so the notice starts a line of its own
    assert capsys.readouterr().err == "\n\n"


@pytest.mark.skipif(store.fcntl is None, reason="needs flock")
@pytest.mark.parametrize("keep", [True, False])
@pytest.mark.parametrize("leave", ["q\n", KeyboardInterrupt, None], ids=["q", "ctrl-c", "eof"])
def test_leaving_an_untouched_deal_does_not_wait_for_the_lock(keep, leave):
    os.makedirs(store.data_dir(), exist_ok=True)
    waits = []
    g = deal("klondike", 1)
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:

        def let_go():
            waits.append(store.LOCK_WAIT)
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)

        def script():
            yield "p\n"
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_EX)  # another copy takes it
            if leave is KeyboardInterrupt:
                raise leave
            if leave:
                yield leave

        with store.lock_wait_note(let_go):
            textmode.run_text(g, False, "klondike", stream=script(), keep=keep)
    # there was nothing to keep or count, so nothing to wait for
    assert waits == []
    assert saves.waiting() == {}
    assert store.get_stat("klondike")["total"] == 0


@posix_signals
def test_ctrl_c_as_n_counts_the_game_leaves_it_unsaved(monkeypatch, ctrl_c):
    signal_once_written(monkeypatch, store.stats_path(), signal.SIGINT)
    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=iter(["d\n", "n\n"]), keep=True) == 130
    assert store.get_stat("klondike")["total"] == 1
    assert saves.waiting() == {}


@posix_signals
def test_ctrl_c_as_a_win_is_counted_still_puts_it_in_the_history(monkeypatch, ctrl_c):
    signal_once_written(monkeypatch, store.stats_path(), signal.SIGINT)
    g = deal("klondike", 1)
    script = iter([f"f {one_card_from_won(g)}\n"])
    assert textmode.run_text(g, False, "klondike", stream=script, keep=True) == 130
    assert store.get_stat("klondike")["wins"] == 1
    assert [e["result"] for e in history.games()] == ["won"]


def test_n_with_a_game_of_its_kind_saved_says_it_wont_be_kept(capsys):
    assert saves.keep(deal("klondike", 4), 42)
    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=iter(["n\n", "q\n"]), keep=True) == 0
    lines = capsys.readouterr().out.splitlines()
    note = "a saved Klondike game is waiting, so this one won't be kept"
    assert lines[1] == note
    new = next(i for i, line in enumerate(lines) if line.startswith("new deal "))
    assert lines[new + 1] == note


def test_n_after_a_resumed_chosen_deal_deals_the_next_number(capsys):
    assert saves.keep(deal("klondike", 7), 42)
    g = deal("klondike", 1)
    script = iter(["n\n", "q\n"])
    assert textmode.run_text(g, False, "klondike", stream=script, keep=True, resume=True) == 0
    assert "\nnew deal 8\n" in capsys.readouterr().out


def test_n_on_a_resumed_game_counts_it_lost_with_its_saved_time(monkeypatch, capsys):
    clock = Clock()
    monkeypatch.setattr(textmode, "time", clock)

    def script():
        clock.now += 5
        yield "n\n"
        yield "q\n"

    assert saves.keep(deal("klondike", 1), 42)
    g = deal("klondike", 2)
    assert textmode.run_text(g, False, "klondike", stream=script(), keep=True, resume=True) == 0
    # the resumed game was under way before a move; the new deal never was
    assert [(e["result"], e["seconds"], e["moves"]) for e in history.games()] == [("lost", 47, 0)]
    assert saves.waiting() == {}


# -- a resumed game, whichever way it goes -----------------------------------------------


def keep_one():
    """Klondike deal 4, one deal in, 31 moves and 0:42 on, kept for next time."""
    g = deal("klondike", 4)
    g.deal()
    g.moves = 31
    assert saves.keep(g, 42)


def typing(*lines):
    """The lines typed, with an error raised, or a signal sent, where one
    is given in their place."""
    for line in lines:
        if line in ("SIGHUP", "SIGTERM"):
            os.kill(os.getpid(), getattr(signal, line))
        elif not isinstance(line, str):
            raise line
        else:
            yield line + "\n"


def resume_one(*lines):
    """Run text mode as at a terminal, on the game kept for Klondike, as
    what is typed goes. Its exit status."""
    return textmode.run_text(
        deal("klondike", 1), False, "klondike", stream=typing(*lines), keep=True, resume=True
    )


@pytest.mark.parametrize(
    "leave, rc",
    [(["q"], 0), ([], 0), ([KeyboardInterrupt], 130), (["SIGHUP"], 130), (["SIGTERM"], 130)],
    ids=["q", "the end of the input", "ctrl-c", "sighup", "sigterm"],
)
def test_leaving_a_resumed_game_keeps_it_again(monkeypatch, leave, rc):
    if leave[:1] in (["SIGHUP"], ["SIGTERM"]) and not hasattr(signal, "SIGHUP"):
        pytest.skip("needs POSIX signals")
    monkeypatch.setattr(textmode, "time", Clock())
    monkeypatch.setattr(cli, "_quiet_output", lambda: None)
    keep_one()
    with cli._leave_on_signals():
        assert resume_one("d", *leave) == rc
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 32}}
    assert store.get_stat("klondike")["total"] == 0
    assert nothing_in_play()


HUNG_UP = OSError(errno.EIO, "Input/output error")


def test_an_error_in_a_resumed_game_keeps_it_again_and_goes_on(monkeypatch):
    monkeypatch.setattr(textmode, "time", Clock())
    keep_one()
    with pytest.raises(OSError, match="Input/output error"):
        resume_one("d", HUNG_UP)
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 32}}
    assert nothing_in_play()


def test_an_error_keeping_it_doesnt_hide_the_error_that_led_there(monkeypatch):
    keep_one()

    def keep(g, seconds):
        raise ValueError("and this")

    monkeypatch.setattr(saves, "keep", keep)
    with pytest.raises(OSError, match="Input/output error"):
        resume_one("d", HUNG_UP)


def test_winning_a_resumed_game_takes_it_out_of_play():
    g = deal("klondike", 1)
    king = one_card_from_won(g)
    assert saves.keep(g, 42)
    assert resume_one(f"f {king}") == 0
    assert store.get_stat("klondike")["wins"] == 1
    assert saves.waiting() == {}
    assert nothing_in_play()


@pytest.mark.parametrize(
    "typed, lost", [(["n", "q"], 1), (["n"], 1), (["N", "q"], 0)], ids=["n", "n then the end", "N"]
)
def test_dealing_over_a_resumed_game_takes_it_out_of_play(typed, lost):
    keep_one()
    assert resume_one(*typed) == 0
    assert store.get_stat("klondike")["total"] == lost
    assert saves.waiting() == {}
    assert nothing_in_play()


def test_a_resumed_game_killed_in_play_is_offered_again_as_it_was(monkeypatch, capsys):
    keep_one()
    with OtherCopy() as other:
        other.says("Resumed your Klondike game (0:42, 31 moves)")
        other.types("d")
        other.says("moves=32 ")
        other.kill()
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 31}}
    monkeypatch.setattr(textmode, "time", Clock())
    assert resume_one("d", "q") == 0
    assert "Resumed your Klondike game (0:42, 31 moves)." in capsys.readouterr().out
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 32}}


def test_a_game_another_copy_has_in_play_isnt_resumed_here(capsys):
    keep_one()
    with OtherCopy() as other:
        other.says("Resumed your Klondike game (0:42, 31 moves)")
        assert resume_one("d", "q") == 0
        assert other.quits() == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == (
        "a saved Klondike game is being played somewhere else, so this one won't be kept"
    )
    # the game played here had no room to be kept; the other one did
    assert store.get_stat("klondike")["total"] == 1
    assert saves.waiting()["klondike"]["moves"] == 31


# -- hints and undos --------------------------------------------------------------------


def test_the_hints_and_undos_typed_go_in_the_history():
    play_text("klondike", "hint\n?\nd\nd\nu\nr\nundo all\nd\n")
    (e,) = history.games()
    assert (e["result"], e["moves"], e["hints"], e["undos"]) == ("lost", 1, 2, 3)


def test_a_resumed_game_carries_on_counting(monkeypatch):
    monkeypatch.setattr(textmode, "time", Clock())
    g = deal("klondike", 4)
    g.deal()
    g.hints, g.undos = 2, 5
    assert saves.keep(g, 42)
    assert resume_one("hint", "u", "q") == 0
    assert (saved()["hints"], saved()["undos"]) == (3, 6)


def test_a_game_from_a_save_before_the_counts_has_none_in_its_line(monkeypatch):
    monkeypatch.setattr(textmode, "time", Clock())
    keep_one()
    from_before_the_counts()
    assert resume_one("hint", "d", "n") == 0
    (e,) = history.games()
    assert e["moves"] == 32
    assert not {"hints", "undos"} & set(e)
