"""Text mode: the board it prints and the commands it takes."""

import io
import re

import pytest

from soliterm import store, textmode
from soliterm.engine import GAME_ORDER, Card, new_solitaire
from soliterm.textmode import render_text

from helpers import board_state, clear_board, deal

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


def test_n_says_the_new_deal_number(capsys):
    g = deal("klondike", 48213)
    textmode.run_text(g, False, "klondike", stream=io.StringIO("n\nq\n"))
    assert "new deal 48214" in capsys.readouterr().out.splitlines()


def test_letters_whose_case_means_nothing_work_in_either_case():
    g = deal("golf", 1)
    assert textmode.apply_text_command(g, "D") == (True, "")
    assert textmode.apply_text_command(g, "U") == (True, "")
    assert textmode.apply_text_command(g, "Q") == (True, "__quit__")


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
