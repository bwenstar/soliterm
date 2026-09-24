"""Text mode: the board it prints and the commands it takes."""

import io
import re
import signal
from datetime import date

import pytest

from soliterm import deals, history, saves, store, textmode
from soliterm.engine import GAME_ORDER, Card, new_solitaire
from soliterm.textmode import render_text

from helpers import (
    Steps,
    board_state,
    clear_board,
    deal,
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
    assert lines[score[0] + 1 :] == ["Share code: klondike:1", *streak]


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
    assert out.endswith("\nSaved your game (0:00, 1 move) for next time.\n")
    assert err == "\n"


posix_signals = pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")


@posix_signals
def test_ctrl_c_as_q_saves_the_game_keeps_it_once(monkeypatch, capsys):
    signal_once_written(monkeypatch, saves.save_path("klondike"), signal.SIGINT)
    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=iter(["d\n", "q\n"]), keep=True) == 130
    assert "Saved your game (0:00, 1 move) for next time." in capsys.readouterr().out
    assert saves.waiting()["klondike"]["moves"] == 1
    assert store.get_stat("klondike")["total"] == 0
    assert store.notices() == []


@posix_signals
def test_ctrl_c_as_n_counts_the_game_leaves_it_unsaved(monkeypatch):
    signal_once_written(monkeypatch, store.stats_path(), signal.SIGINT)
    g = deal("klondike", 1)
    assert textmode.run_text(g, False, "klondike", stream=iter(["d\n", "n\n"]), keep=True) == 130
    assert store.get_stat("klondike")["total"] == 1
    assert saves.waiting() == {}


@posix_signals
def test_ctrl_c_as_a_win_is_counted_still_puts_it_in_the_history(monkeypatch):
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
