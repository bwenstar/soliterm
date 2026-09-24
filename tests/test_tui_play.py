"""Drive the real curses loop, soliterm.tui.run(), with scripted keys and clicks.

The curses calls that need a real terminal are stubbed out, and the window is
a FakeScr that plays back a key script and remembers what was on screen each
time the game asked for a key.
"""

import curses
import functools
import glob
import importlib.util
import json
import os
import re
import signal
import sys

import pytest

import soliterm.tui
from soliterm import aisleriot as ar
from soliterm import cli, deals, engine, history, saves, store
from soliterm.deals import Deal
from soliterm.engine import Card
from soliterm.tui import cascade
from soliterm.tui.app import DEAL_TEXT_MAX

from helpers import FakeScr, clear_board, deal, signal_once_written, stalled_klondike

ENTER = "\n"
ESC = 27


class Click:
    """A left click on card idx of slot sid, found through the live hit map."""

    def __init__(self, sid, idx, bstate=curses.BUTTON1_CLICKED):
        self.sid, self.idx, self.bstate = sid, idx, bstate


class Mouse:
    """A raw mouse event at screen cell (y, x), for the screens without cards."""

    def __init__(self, y, x, bstate=curses.BUTTON1_CLICKED):
        self.y, self.x, self.bstate = y, x, bstate


class Resize:
    """The terminal changing size to h rows by w columns."""

    def __init__(self, h, w):
        self.h, self.w = h, w


class Later:
    """Key k, pressed once the game_clock has moved on by seconds."""

    def __init__(self, seconds, k):
        self.seconds, self.k = seconds, k


class Signal:
    """The signal `name` arriving from outside, as kill sends it."""

    def __init__(self, name):
        self.name = name


class ScriptedScr(FakeScr):
    def __init__(self, h, w, keys, uis):
        super().__init__(h, w)
        self.keys = list(keys)
        self.uis = uis
        self.frames = []  # the screen each time a key was read
        self.mouse = None
        self.spare = 0
        self.delay = -1  # how long getch waits for a key, in ms; -1 for ever
        self.delays = []  # the delay each key was read with

    def nodelay(self, flag):
        self.delay = 0 if flag else -1

    def timeout(self, ms):
        self.delay = ms

    def getch(self):
        self.frames.append(self.text())
        self.delays.append(self.delay)
        if not self.keys:
            # out of script: keep pressing q until the game lets go
            self.spare += 1
            assert self.spare < 20, "the UI kept asking for keys after q"
            return ord("q")
        k = self.keys.pop(0)
        if isinstance(k, Later):
            soliterm.tui.app.clock.now += k.seconds
            k = k.k
        assert k != -1 or self.delay >= 0, "no key is coming and getch would wait for ever"
        if isinstance(k, type) and issubclass(k, BaseException):
            raise k  # e.g. KeyboardInterrupt, for Ctrl-C
        if isinstance(k, Signal):
            os.kill(os.getpid(), getattr(signal, k.name))
            return -1
        if isinstance(k, Click):
            cells = sorted(yx for yx, hit in self.uis[-1].hit.items() if hit == (k.sid, k.idx))
            assert cells, f"card {k.idx} of slot {k.sid} is not on screen"
            y, x = cells[0]
            self.mouse = (0, x, y, 0, k.bstate)
            return curses.KEY_MOUSE
        if isinstance(k, Mouse):
            self.mouse = (0, k.x, k.y, 0, k.bstate)
            return curses.KEY_MOUSE
        if isinstance(k, Resize):
            self.h, self.w = k.h, k.w
            self.erase()
            return curses.KEY_RESIZE
        return ord(k) if isinstance(k, str) else k


@pytest.fixture
def tui(monkeypatch):
    """Returns run(keys, ...) which plays a script through soliterm.tui.run().

    It starts on a game of start_key (None for the menu), deal number deal=
    if given, or on start=, a Deal. Pass game= to start play on a board
    built by hand. The returned screen
    has .frames, .rc, .uis (every BoardUI made, each with .selections),
    .pairs (init_pair calls), .masks (mousemask calls) and .intervals
    (mouseinterval calls).
    """
    uis, pairs, masks, intervals = [], [], [], []

    class RecordingBoardUI(soliterm.tui.BoardUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.initial_has_color = self.has_color
            self.selections = []  # the selected slot at every draw
            uis.append(self)

        def draw(self, selected_slot, *args):
            self.selections.append(selected_slot)
            return super().draw(selected_slot, *args)

    monkeypatch.setattr(soliterm.tui.app, "BoardUI", RecordingBoardUI)
    # set here rather than in run() so a test can put its own in first
    monkeypatch.setattr(curses, "curs_set", lambda n: None)
    monkeypatch.setattr(curses, "use_default_colors", lambda: None)
    # a test that wants a light background sets COLORFGBG itself
    monkeypatch.delenv("COLORFGBG", raising=False)

    def run(
        keys,
        start_key="klondike",
        game=None,
        deal=None,
        color=None,
        color_capable=True,
        h=40,
        w=120,
        start=None,
        **kwargs,
    ):
        scr = ScriptedScr(h, w, keys, uis)
        kwargs.setdefault("animation", False)  # a test that wants it says so
        monkeypatch.setattr(curses, "mousemask", lambda mask: masks.append(mask) or (mask, 0))
        monkeypatch.setattr(curses, "mouseinterval", intervals.append)
        monkeypatch.setattr(curses, "has_colors", lambda: color_capable)
        monkeypatch.setattr(curses, "start_color", lambda: None)
        monkeypatch.setattr(curses, "init_pair", lambda *a: pairs.append(a))
        monkeypatch.setattr(curses, "color_pair", lambda n: n << 8)
        monkeypatch.setattr(curses, "getmouse", lambda: scr.mouse)
        if game is not None:
            real = engine.new_solitaire
            pending = [game]

            def new_solitaire(key, seed=None, options=None):
                return pending.pop() if pending else real(key, seed=seed, options=options)

            monkeypatch.setattr(engine, "new_solitaire", new_solitaire)
        try:
            if start is None and start_key is not None:
                start = Deal(start_key, deal)
            scr.rc = soliterm.tui.run(scr, start, color=color, **kwargs)
        except KeyboardInterrupt:
            # let through, it would stop the whole test session
            pytest.fail("Ctrl-C got out of the TUI")
        scr.uis, scr.pairs, scr.masks, scr.intervals = uis, pairs, masks, intervals
        return scr

    return run


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def game_clock(monkeypatch):
    """Stop the clock the TUI reads, so only Later() in a script moves it."""
    fake = FakeClock()
    monkeypatch.setattr(soliterm.tui.app, "clock", fake)
    return fake


def times(scr):
    """The time on the status line of every frame that shows the board."""
    return [t for frame in scr.frames for t in re.findall(r"Time (\d+:\d\d)", frame)]


def board(key, first, second, **options):
    """A board with only the first two tableau columns filled in."""
    g = deal(key, 1, **options)
    t = g.ids_of("tableau")
    for sid in t:
        g.slots[sid].cards = []
    g.slots[t[0]].cards = first
    g.slots[t[1]].cards = second
    return g, t[0], t[1]


def names(g, sid):
    return [str(c) for c in g.cards(sid)]


def up(rank, suit):
    return Card(rank, suit, True)


# -- picking up and dropping ------------------------------------------------------


def test_a_keyboard_drop_lands_the_part_of_the_run_that_fits(tui):
    # 4S-3S is the default pickup, only the 3S fits on 4H
    g, a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(4, "H")], suits=4)
    assert g.default_pickup(a) == 2
    assert not g.clone().attempt_move(a, b, 2)
    scr = tui([ENTER, curses.KEY_RIGHT, ENTER], start_key="spider", game=g)
    assert scr.rc == 0
    assert names(g, b) == ["4H", "3S"]
    assert names(g, a) == ["9H", "4S"]


def test_a_keyboard_drop_moves_the_whole_run_when_it_fits(tui):
    g, _a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(5, "H")], suits=4)
    tui([ENTER, curses.KEY_RIGHT, ENTER], start_key="spider", game=g)
    assert names(g, b) == ["5H", "4S", "3S"]


def test_a_klondike_three_drops_off_the_top_of_a_run(tui):
    g, _a, b = board("klondike", [up(9, "C"), up(4, "S"), up(3, "H")], [up(4, "C")])
    tui([ENTER, curses.KEY_RIGHT, ENTER], start_key="klondike", game=g)
    assert names(g, b) == ["4C", "3H"]


def test_the_keyboard_can_lift_part_of_a_run_into_an_empty_column(tui):
    g, a, b = board("spider", [up(9, "H"), up(7, "S"), up(6, "S"), up(5, "S")], [], suits=4)
    assert g.default_pickup(a) == 3
    tui([ENTER, "-", "-", curses.KEY_RIGHT, ENTER], start_key="spider", game=g)
    assert names(g, b) == ["5S"]
    assert names(g, a) == ["9H", "7S", "6S"]


@pytest.mark.parametrize("target", [(9, "D"), (4, "H")])
def test_a_clicked_split_is_never_shrunk_to_fit(tui, target):
    # clicking the 4S lifts 4S-3S exactly; on 4H the 3S alone would fit, but
    # the player asked for two cards
    g, a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(*target)], suits=4)
    before = g.serialize()
    scr = tui([Click(a, 1), Click(b, 0)], start_key="spider", game=g)
    assert "picked up 2 card(s) from 4S" in scr.frames[1]
    assert "illegal move" in scr.frames[2]
    assert g.serialize() == before


def test_clicking_the_top_card_lifts_just_that_card(tui):
    g, a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(4, "H")], suits=4)
    tui([Click(a, 2), Click(b, 0)], start_key="spider", game=g)
    assert names(g, b) == ["4H", "3S"]


def test_the_lift_keys_reach_cards_squeezed_onto_one_row(tui):
    # too long a column for 18 rows puts JS 10S 9S on one row; a click there
    # lifts from the JS, and - and + go through the cards under it
    run = [up(r, "S") for r in range(12, 0, -1)]
    g, a, b = board("spider", [Card(1, "S", False)] * 5 + run, [], suits=1)
    scr = tui(
        [Click(a, 6), "-", "-", "+", curses.KEY_RIGHT, ENTER],
        start_key="spider",
        game=g,
        h=18,
        w=80,
    )
    assert "| +3 |" in scr.frames[0].replace("\u2502", "|")
    assert "picked up 11 card(s) from JS" in scr.frames[1]
    assert "holding 10 cards from 10S" in scr.frames[4]
    assert names(g, b) == [str(c) for c in run[2:]]
    assert names(g, a)[5:] == ["QS", "JS"]


def test_the_hint_key_shows_the_hint(tui):
    g = deal("klondike", 1)
    desc = g.hint()[2]
    scr = tui(["h"], game=g)
    assert f"Hint: {desc}" in scr.frames[1]


def test_the_hint_names_cards_the_way_the_board_draws_them(tui):
    # with symbols off the board shows 2H, so the hint must not say 2♥
    cfg = store.load_config()
    cfg["symbols"] = False
    store.save_config(cfg)
    g = deal("klondike", 1)
    g.symbols = False
    desc = g.hint()[2]
    g.symbols = True
    scr = tui(["h"], game=g)
    assert f"Hint: {desc}" in scr.frames[1]


def test_the_hint_key_with_nothing_to_hint_explains_why(tui):
    g, _, _ = board("freecell", [up(13, "S")], [up(13, "H")])
    assert g.hint() is None
    scr = tui(["h"], start_key="freecell", game=g)
    assert g.no_hint_reason() in scr.frames[1]
    assert "deal" not in scr.frames[1]


def test_n_deals_a_new_hand_and_shift_n_replays_it_under_seed(tui):
    seeded = deal("klondike", 5)
    first = seeded.serialize()
    seeded.new_game()
    second = seeded.serialize()
    assert second != first
    scr = tui(["n", "d", "N"], deal=5)
    assert scr.uis[0].game.serialize() == second


def test_the_tui_starts_on_the_deal_asked_for(tui):
    scr = tui([], start=Deal("klondike", 48213, {"draw": 3}))
    g = scr.uis[0].game
    assert (g.deal_number, g.options["draw"]) == (48213, 3)
    want = deal("klondike", 48213, draw=3)
    assert [s.cards for s in g.slots] == [s.cards for s in want.slots]
    # for this run only: the saved options are left alone
    assert store.game_options(store.load_config(), "klondike") == {}


def test_a_deal_number_only_fixes_the_first_game(tui):
    # deal 5 of one game and deal 5 of the next have nothing to do with
    # each other, so a game picked from the menu is a random one
    scr = tui(["m", ENTER], deal=5)
    first, second = (ui.game for ui in scr.uis)
    assert first.seed == 5
    assert second.gamedef.key == "klondike" and second.seed is None


def test_the_title_names_the_deal(tui):
    scr = tui([], deal=48213)
    assert "Soliterm  -  Klondike  -  Deal 48213" in scr.frames[0]


# -- g: play a deal ------------------------------------------------------------------


def test_g_plays_a_typed_deal(tui):
    scr = tui(["g", "4", "2", ENTER], start=Deal("klondike", 5, {"draw": 3}))
    box = scr.frames[3]
    assert "Play a deal" in box
    assert "This deal   : 5" in box and "Share code  : klondike:d3:5" in box
    assert "> 42_" in box
    # a number on its own keeps the game and the options in play
    g = scr.uis[-1].game
    assert (g.gamedef.key, g.deal_number, g.options["draw"]) == ("klondike", 42, 3)
    assert [s.cards for s in g.slots] == [s.cards for s in deal("klondike", 42, draw=3).slots]
    assert "playing klondike:d3:42" in scr.frames[4]


def test_g_takes_a_share_code_for_another_game(tui):
    keys = ["g", *"spider:s2:7", ENTER]
    scr = tui(keys)
    g = scr.uis[-1].game
    assert (g.gamedef.key, g.deal_number, g.options) == ("spider", 7, {"suits": 2})
    assert "playing spider:s2:7" in scr.frames[len(keys)]
    cfg = store.load_config()
    assert cfg["last_game"] == "spider"
    # for this run only: the options aren't saved
    assert store.game_options(cfg, "spider") == {}


def test_g_keeps_the_text_and_shows_a_bad_code_error(tui):
    scr = tui(["g", *"chess:5", ENTER, "x", curses.KEY_BACKSPACE, ESC, -1], deal=5)
    wrong = scr.frames[9]
    assert "> chess:5_" in wrong and "no game called 'chess'" in wrong
    # typing clears the error
    assert "> chess:5x_" in scr.frames[10] and "chess'" not in scr.frames[10]
    assert "> chess:5_" in scr.frames[11]
    assert "kept this deal" in scr.frames[-1]
    assert len(scr.uis) == 1


def test_g_types_b_q_and_n_and_ctrl_u_clears_the_text(tui):
    scr = tui(["g", "b", "q", "n", 21, "4", ENTER], deal=5)
    assert "> bqn_" in scr.frames[4]
    assert "> _" in scr.frames[5]
    assert scr.uis[-1].game.deal_number == 4


@pytest.mark.parametrize("leave", [[ESC, -1], [ENTER]])
def test_g_then_esc_or_an_empty_enter_keeps_this_deal(tui, leave):
    scr = tui(["g", *leave], deal=5)
    assert "kept this deal" in scr.frames[-1]
    assert len(scr.uis) == 1


@pytest.mark.parametrize("typed", ["5", "klondike:5", "Klondike deal 5"])
def test_g_on_the_deal_in_play_says_so(tui, typed):
    scr = tui(["d", "g", *typed, ENTER], deal=5)
    assert "that's the deal in play (N starts it over)" in scr.frames[-1]
    assert len(scr.uis) == 1 and scr.uis[0].game.moves == 1


def test_g_asks_before_leaving_a_started_game(tui):
    scr = tui(["d", "g", "7", ENTER, "n", "g", "7", ENTER, "y"], deal=5)
    ask = scr.frames[4]
    assert "Leave this game for klondike:7?" in ask
    assert "The game in play will count as lost." in ask
    assert "kept this deal" in scr.frames[5]
    assert "playing klondike:7" in scr.frames[9]
    assert [ui.game.deal_number for ui in scr.uis] == [5, 7]
    assert store.get_stat("klondike")["total"] == 1  # the deal given up


@pytest.mark.parametrize("key", engine.GAME_ORDER)
def test_g_takes_the_board_title_row_pasted_whole(tui, key):
    # the longest title the game has, copied as a whole row, spaces and all
    row = tui([], start=Deal(key, engine.MAX_DEAL)).frames[0].split("\n")[0]
    assert f"  Deal {engine.MAX_DEAL}" in row
    scr = tui(["g", *row, ENTER], start=Deal(key, engine.MAX_DEAL))
    assert "that's the deal in play (N starts it over)" in scr.frames[-1]


@pytest.mark.parametrize("skin", [False, True])
@pytest.mark.parametrize("game", ["klondike", "golf"])
def test_the_pick_deal_box_fits_80x24(tui, skin, game):
    if skin:
        code_skin_on()
    # as long as the box takes, with the longest errors there are: one
    # naming the options Klondike takes, one saying Golf has none
    typed = f"{game}:" + "x" * (DEAL_TEXT_MAX - len(game) - 3) + ":5"
    assert len(typed) == DEAL_TEXT_MAX
    with pytest.raises(ValueError, match="share code") as exc:
        deals.parse(typed)
    scr = tui(["g", *typed, "y", ENTER, ESC, -1], h=24, w=80)
    box = scr.frames[len(typed) + 3]
    assert "Terminal too small" not in box
    rows = box.split("\n")
    assert all(len(row) < 80 for row in rows)
    (prompt,) = [i for i, row in enumerate(rows) if f"> {typed}_" in row]
    (footer,) = [i for i, row in enumerate(rows) if "Enter play - Esc back" in row]
    # the error, however long, is all on screen between the two
    start = rows[prompt].index(">")
    shown = " ".join(row[start:].strip() for row in rows[prompt + 1 : footer])
    assert " ".join(shown.split()) == str(exc.value)


@pytest.mark.parametrize("skin", [False, True])
def test_a_long_deal_scrolls_to_keep_its_end_in_view(tui, skin):
    if skin:
        code_skin_on()
    typed = "klondike:" + "x" * 45 + ":48213"
    scr = tui(["g", *typed, ESC, -1], h=24, w=50)
    rows = scr.frames[len(typed) + 1].split("\n")
    (prompt,) = [row for row in rows if row.endswith("_")]
    assert prompt.endswith(":48213_")
    assert len(prompt) == 49  # all the room there is
    # and the start, cut off, is marked as cut
    assert prompt.split("< ")[1].startswith("xxx")


def test_the_terminal_is_not_asked_to_report_pointer_motion(tui):
    scr = tui([])
    assert scr.masks
    assert not any(m & curses.REPORT_MOUSE_POSITION for m in scr.masks)
    assert all(m & curses.BUTTON1_PRESSED for m in scr.masks)


def test_ncurses_does_not_hold_clicks_back_to_wait_for_a_double_click(tui):
    # the play screen spots double-clicks itself
    assert tui([]).intervals == [0]


def test_esc_acts_at_once(tui):
    # nothing queued behind the Esc (the -1), so it is the Esc key
    scr = tui([ENTER, ESC, -1])
    before, picked, after = scr.uis[0].selections[:3]
    assert before is None and picked is not None and after is None


def test_alt_and_a_key_does_not_act_as_esc_then_the_key(tui):
    # a terminal sends Alt+n as Esc then n, both at once
    scr = tui(["d", ENTER, ESC, "n"])
    assert not any("new deal" in frame for frame in scr.frames)
    assert "Moves 1" in scr.frames[-1]
    assert scr.uis[0].selections[-1] is not None


@pytest.mark.parametrize("event", ["click", "resize"])
def test_a_click_or_a_resize_just_after_esc_is_not_taken_for_alt(tui, event):
    # neither comes as Alt, so both the Esc and what follows it act
    t = deal("klondike", 1).ids_of("tableau")
    follow = Click(t[1], 1) if event == "click" else Resize(40, 120)
    scr = tui([ENTER, ESC, follow])
    picked, *rest = scr.uis[0].selections[1:]
    assert picked == t[0] and None in rest
    assert rest[-1] == (t[1] if event == "click" else None)


def test_alt_and_a_key_does_nothing_on_the_menu_or_the_banner(tui):
    # Alt+j would have moved the menu to Spider, Alt+n dealt a new hand
    scr = tui([ESC, "j", ENTER], start_key=None)
    assert scr.uis[0].game.gamedef.key == "klondike"
    scr = tui(["a", ESC, "n", "m"], game=near_won())
    assert "YOU WIN" in scr.frames[-2]
    assert "choose a game" in scr.frames[-1]


def test_the_escape_delay_is_short_unless_the_player_set_one(monkeypatch):
    seen = []
    monkeypatch.setattr(
        curses, "wrapper", lambda fn, *args: seen.append(os.environ.get("ESCDELAY")) or 0
    )
    # set before it is taken away, so the one main() puts in goes afterwards
    monkeypatch.setenv("ESCDELAY", "")
    monkeypatch.delenv("ESCDELAY")
    assert soliterm.tui.main() == 0
    assert int(seen[-1]) <= 50
    monkeypatch.setenv("ESCDELAY", "300")
    soliterm.tui.main()
    assert seen[-1] == "300"


def test_a_terminal_that_cannot_hide_the_cursor_still_plays(tui, monkeypatch):
    # vt100, ansi and xterm-mono have no way to make the cursor invisible
    def no_civis(n):
        raise curses.error("curs_set() returned ERR")

    monkeypatch.setattr(curses, "curs_set", no_civis)
    scr = tui(["d", "q"])
    assert scr.rc == 0
    assert "Soliterm  -  Klondike" in scr.frames[0]
    assert "Moves 1" in scr.frames[1]


def test_a_colour_terminal_without_default_colours_still_plays(tui, monkeypatch):
    # a few colour terminals can't leave the background to the terminal
    def no_default_colours():
        raise curses.error("use_default_colors() returned ERR")

    monkeypatch.setattr(curses, "use_default_colors", no_default_colours)
    scr = tui(["d", "q"])
    assert scr.rc == 0
    assert "Moves 1" in scr.frames[1]
    assert scr.pairs and all(-1 not in pair[1:] for pair in scr.pairs)


def test_ascii_on_the_command_line_reaches_the_tui(monkeypatch):
    seen = {}
    monkeypatch.setattr(soliterm.tui, "main", lambda *a, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    # whatever TERM the tests run under, curses can draw here
    monkeypatch.setattr(cli, "_terminal_problem", lambda: None)
    assert cli.main(["--game", "klondike", "--ascii"]) == 0
    assert seen["symbols"] is False
    cli.main(["--game", "klondike"])
    assert seen["symbols"] is True


def test_ascii_draws_the_cards_in_plain_characters(tui):
    scr = tui(["x", "q"], symbols=False)
    for frame in scr.frames[:2]:  # both views
        assert not any(ch in frame for ch in "┌│▒░♠♥♦♣")
    assert "+------+" in scr.frames[0]
    assert "#" in scr.frames[1]
    assert store.load_config()["symbols"] is True  # the flag is not saved


def test_the_game_names_cards_the_way_the_board_does(tui):
    # a game that can name its cards either way is told which to use
    scr = tui([], symbols=False)
    assert scr.uis[0].game.symbols is False


def test_a_terminal_that_cannot_show_unicode_gets_plain_cards(tui, monkeypatch):
    # LC_ALL=C: curses refuses every string with a box corner or a suit in it,
    # which left the board blank but for the slot names
    monkeypatch.setattr(FakeScr, "encoding", "ascii")
    scr = tui(["x", "q"])
    for frame in scr.frames[:2]:  # both views
        assert "+------+" in frame or "#" in frame
    assert "+------+" in scr.frames[0]
    assert any(ui.symbols is False for ui in scr.uis)
    assert store.load_config()["symbols"] is True


def test_the_locale_decides_when_the_window_does_not_say(monkeypatch):
    import locale

    from soliterm.tui.board import can_draw_unicode

    class Window:
        encoding = None

    monkeypatch.setattr(locale, "getpreferredencoding", lambda *a: "ANSI_X3.4-1968")
    assert not can_draw_unicode(Window())
    monkeypatch.setattr(locale, "getpreferredencoding", lambda *a: "UTF-8")
    assert can_draw_unicode(Window())
    Window.encoding = "latin-1"  # has no box corners
    assert not can_draw_unicode(Window())


# -- a terminal too small for the board -----------------------------------------------


def test_keys_make_no_hidden_moves_while_the_board_does_not_fit(tui):
    scr = tui(["d", "d", ENTER, curses.KEY_RIGHT, ENTER, "a", "n", "o", "m", "q"], h=20, w=38)
    assert scr.rc == 0
    assert all("Terminal too small" in frame for frame in scr.frames)
    assert len(scr.uis) == 1 and scr.uis[0].game.moves == 0
    assert store.get_stat("klondike")["total"] == 0


def test_the_board_comes_back_as_it_was_once_the_terminal_grows(tui):
    scr = tui(["d", Resize(40, 120), "q"], h=20, w=38)
    assert "Terminal too small" in scr.frames[1]
    assert "Moves 0" in scr.frames[2] and "Stock: 24" in scr.frames[2]


@pytest.mark.parametrize(
    "key, h, w, small",
    [
        ("c", 17, 40, [False, True, False]),  # the code skin needs more columns
        ("x", 15, 80, [True, False, True]),  # and full cards more rows
    ],
)
def test_the_skin_and_view_toggles_still_work_on_a_small_terminal(tui, key, h, w, small):
    # so the toggle that hid the board can bring it back
    scr = tui([key, key, "q"], h=h, w=w)
    assert ["Terminal too small" in frame for frame in scr.frames[:3]] == small


def test_the_boss_key_still_works_on_a_small_terminal(tui):
    scr = tui(["b", "z"], h=20, w=38)
    assert "Terminal too small" not in scr.frames[1]
    assert "Terminal too small" in scr.frames[2]


# -- the clock ---------------------------------------------------------------------


def test_the_clock_runs_from_the_first_move_and_stops_behind_other_screens(tui, game_clock):
    # half a minute looking before the first move, ten seconds of play,
    # then a minute each in the help, the statistics and boss mode
    scr = tui(
        [Later(30, "d"), Later(10, "?"), Later(60, "z"), "s", Later(60, "z"), "b", Later(60, "z")]
    )
    assert times(scr) == ["0:00", "0:00", "0:10", "0:10", "0:10"]


def test_the_clock_on_the_status_line_ticks(tui, game_clock):
    # no key for a second at a time, and the board is drawn again each time
    scr = tui(["d", Later(1, -1), Later(1, -1)])
    assert times(scr) == ["0:00", "0:00", "0:01", "0:02"]


def test_the_clock_the_banner_and_the_statistics_agree_on_the_time(tui, game_clock):
    # moving a king to an empty column starts the clock; the win comes 10.6 s on
    keys = [ENTER] + [curses.KEY_RIGHT] * 4 + [ENTER, Later(10.6, -1), "a", "m"]
    scr = tui(keys, game=near_won())
    assert times(scr)[-1] == "0:11"
    assert any("Time        : 0:11" in frame for frame in scr.frames)
    assert store.get_stat("klondike")["best"] == 11


# -- recording results -------------------------------------------------------------


def test_quitting_before_moving_records_nothing(tui):
    tui(["q"])
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting() == {}


def test_quitting_mid_game_saves_it(tui):
    tui(["d", "q"])
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting()["klondike"]["moves"] == 1


def test_undoing_every_move_still_keeps_the_game(tui):
    # AisleRiot counts a game from its first move, however many are taken
    # back, so it is worth keeping from then on too
    scr = tui(["d", "d", "d", "u", "u", "u", "q"])
    assert "Moves 0" in scr.frames[-1]
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting()["klondike"]["moves"] == 0


def test_U_undoes_every_move_and_R_redoes_them(tui):
    scr = tui(["d", "d", "d", "U", "R", "U", "U", "R", "R"])
    undone, redone = scr.frames[4], scr.frames[5]
    assert "Moves 0" in undone and soliterm.tui.app.UNDONE_ALL in undone
    assert "Moves 3" in redone
    assert "nothing to undo" in scr.frames[7]
    assert "nothing to redo" in scr.frames[9]


def test_U_keeps_the_clock_running_and_the_game_under_way(tui, game_clock):
    # where N deals the hand again as a new game, at 0:00 and not kept
    scr = tui([Later(0, "d"), "d", Later(10, "U"), Later(5, -1)])
    assert "Moves 0" in scr.frames[-1]
    assert times(scr)[-1] == "0:15"
    assert saves.waiting()["klondike"] == {"seconds": 15, "moves": 0}


def test_restarting_the_deal_does_not_count_it(tui):
    # nor does AisleRiot's Restart, which deals the same hand again
    tui(["d", "N", "q"])
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting() == {}


def near_won(number=1, key="klondike", **options):
    """Klondike (or `key`) with A-Q home in every suit and the four kings on
    the tableau."""
    g = deal(key, number, **options)
    fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    for i, suit in enumerate("SHDC"):
        g.slots[fids[i]].cards = [up(r, suit) for r in range(1, 13)]
        g.slots[tids[i]].cards = [up(13, suit)]
    return g


def test_tui_a_finishes_and_wins(tui):
    # safe autoplay would send up the 5S and stop there
    scr = tui(["a", "m", "q"], game=stalled_klondike())
    assert "YOU WIN" in scr.frames[1]
    assert store.get_stat("klondike")["wins"] == 1


def queen_under_a_king():
    """near_won(), but with the queen of clubs face down under the king of
    spades, so it can't be finished until the king moves."""
    g = near_won()
    t0, clubs = g.ids_of("tableau")[0], g.ids_of("foundation")[3]
    g.slots[t0].cards.insert(0, g.slots[clubs].cards.pop().up(False))
    return g


def test_the_offer_shows_after_the_move_that_allows_it(tui):
    # moving the king turns the queen over; undo turns it back down
    scr = tui(KING_TO_EMPTY + ["u"], game=queen_under_a_king())
    offer = soliterm.tui.app.FINISH_OFFER
    moved = len(KING_TO_EMPTY)
    assert not any(offer in frame for frame in scr.frames[:moved])
    assert offer in scr.frames[moved]
    assert offer not in scr.frames[moved + 1]


# -- the finish, played out ------------------------------------------------------------


@pytest.fixture
def animated(tui, monkeypatch):
    """tui with the cards moving on their own, as on a real terminal."""
    monkeypatch.setenv("TERM", "xterm")
    return functools.partial(tui, animation=True)


def test_the_finish_lands_one_card_a_frame(animated):
    scr = animated(["a", -1, -1, -1, -1], game=near_won())
    for n in range(1, 5):
        rows = scr.frames[n].split("\n")
        assert (rows[5].count("K"), rows[10].count("K")) == (n, 4 - n)
    # each card waits a moment for a key, where the play screen waits a second
    assert scr.delays[:5] == [1000, 80, 80, 80, 80]
    assert store.get_stat("klondike")["wins"] == 1


def test_a_key_cuts_the_finish_short(animated):
    # the rest go up at once, and the key goes no further
    scr = animated(["a", "z", "m"], game=near_won())
    assert scr.frames[1].split("\n")[5].count("K") == 1
    assert "Replay this deal" in scr.frames[2]
    assert "choose a game" in scr.frames[3]
    assert store.get_stat("klondike")["wins"] == 1


def test_the_boss_key_hides_the_finish_at_once(animated):
    scr = animated(["a", "b", "x", "m"], game=near_won())
    assert scr.frames[1].split("\n")[5].count("K") == 1
    board = {line for line in scr.frames[1].split("\n") if line.strip()}
    assert not board & set(scr.frames[2].split("\n"))
    assert "Replay this deal" in scr.frames[3]


def test_a_left_press_cuts_the_finish_short_and_a_release_does_not(animated):
    let_go, press = Mouse(10, 10, curses.BUTTON1_RELEASED), Mouse(10, 10, curses.BUTTON1_PRESSED)
    scr = animated(["a", let_go, press, "m"], game=near_won())
    assert scr.frames[2].split("\n")[5].count("K") == 2
    assert "Replay this deal" in scr.frames[3]
    assert "choose a game" in scr.frames[4]


def test_the_clock_is_paused_while_the_finish_plays(animated, game_clock):
    scr = animated(KING_TO_EMPTY + ["a", Later(5, -1), -1, -1, -1], game=near_won())
    banner = next(frame for frame in scr.frames if "Replay this deal" in frame)
    assert "Time        : 0:00\n" in banner


def test_the_offer_goes_once_it_is_taken_up(animated):
    scr = animated(KING_TO_EMPTY + ["a", -1, -1, -1, -1], game=near_won())
    offer = soliterm.tui.app.FINISH_OFFER
    moved = len(KING_TO_EMPTY)
    assert offer in scr.frames[moved]
    assert not any(offer in frame for frame in scr.frames[moved + 1 :])


def test_ctrl_c_during_the_finish_leaves_as_q_does(animated):
    # a finish as the first move leaves nothing to keep, one after a move is
    # kept with the cards it has sent up so far
    assert animated(["a", -1, KeyboardInterrupt], game=near_won()).rc == 130
    assert saves.waiting() == {}
    assert animated(KING_TO_EMPTY + ["a", KeyboardInterrupt], game=near_won()).rc == 130
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting()["klondike"]["moves"] == 2


# -- the win's cascade ------------------------------------------------------------------

LANDINGS = ["a", -1, -1, -1, -1]  # near_won() finished, a card a frame


def test_any_key_skips_the_cascade(animated):
    # and goes no further: n would deal again from the banner
    scr = animated([*LANDINGS, -1, "n", "m"], game=near_won())
    assert all("Moves 1" in frame for frame in scr.frames[5:7])
    assert "Replay this deal" in scr.frames[7]
    assert "choose a game" in scr.frames[8]
    assert len(scr.uis) == 1


def test_the_cascade_waits_a_frame_for_a_key(animated):
    scr = animated([*LANDINGS, -1, -1, "z", "m"], game=near_won())
    assert scr.delays[5:9] == [cascade.FRAME_MS] * 3 + [1000]


def test_a_left_press_skips_the_cascade_and_a_release_does_not(animated):
    let_go, press = Mouse(10, 10, curses.BUTTON1_RELEASED), Mouse(10, 10, curses.BUTTON1_PRESSED)
    scr = animated([*LANDINGS, let_go, press, "m"], game=near_won())
    assert "Replay this deal" not in scr.frames[6]
    assert "Replay this deal" in scr.frames[7]


def test_the_boss_key_hides_the_cascade_at_once(animated):
    scr = animated([*LANDINGS, "b", "x", "m"], game=near_won())
    board = {line for line in scr.frames[5].split("\n") if line.strip()}
    assert "Moves 1" in scr.frames[5]
    assert not board & set(scr.frames[6].split("\n"))
    assert "Replay this deal" in scr.frames[7]


def test_a_resize_stops_the_cascade(animated):
    scr = animated([*LANDINGS, Resize(30, 100), "m"], game=near_won())
    assert "Moves 1" in scr.frames[5]
    assert "Replay this deal" in scr.frames[6]


def test_ctrl_c_during_the_cascade_keeps_the_win(animated):
    scr = animated([*LANDINGS, -1, KeyboardInterrupt], game=near_won())
    assert scr.rc == 130
    assert store.get_stat("klondike")["wins"] == 1


def test_no_cascade_under_the_code_skin(animated):
    # card boxes flying about would give the game away
    code_skin_on()
    scr = animated([*LANDINGS, "m"], game=near_won())
    assert "Replay this deal" in scr.frames[5]


@pytest.mark.parametrize("way", ["flag", "config", "dumb terminal"])
def test_no_cascade_without_the_animation(tui, monkeypatch, way):
    monkeypatch.setenv("TERM", "dumb" if way == "dumb terminal" else "xterm")
    if way == "config":
        store.save_config({**store.load_config(), "animation": False})
    scr = tui(["a", "m"], game=near_won(), animation=False if way == "flag" else None)
    assert "Replay this deal" in scr.frames[1]


@pytest.mark.parametrize("ending", [["z"], ["b", "x"]], ids=["a key", "the boss key"])
def test_no_cascade_after_a_finish_cut_short(animated, ending):
    # the key that stopped the cards stops the cascade too, however soon
    scr = animated(["a", *ending, "m"], game=near_won())
    assert "Replay this deal" in scr.frames[1 + len(ending)]
    assert store.get_stat("klondike")["wins"] == 1


@pytest.mark.parametrize("keys", [["d"], ["d", "b"], ["d", "?"]])
def test_ctrl_c_mid_game_quits_quietly_and_saves_it(tui, keys):
    scr = tui(keys + [KeyboardInterrupt])
    assert scr.rc == 130
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting()["klondike"]["moves"] == 1


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")
@pytest.mark.parametrize("name", ["SIGHUP", "SIGTERM"])
def test_a_signal_mid_game_saves_it(tui, monkeypatch, name):
    # SIGHUP would otherwise point this process's output at devnull
    monkeypatch.setattr(cli, "_quiet_output", lambda: None)
    with cli._leave_on_signals():
        scr = tui(["d", Signal(name)])
    assert scr.rc == 130
    assert saves.waiting()["klondike"]["moves"] == 1


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")
@pytest.mark.parametrize("name", ["SIGINT", "SIGHUP", "SIGTERM"])
def test_a_signal_as_q_saves_the_game_keeps_it_once(tui, monkeypatch, name):
    monkeypatch.setattr(cli, "_quiet_output", lambda: None)
    signal_once_written(monkeypatch, saves.save_path("klondike"), getattr(signal, name))
    with cli._leave_on_signals():
        scr = tui(["d", "q"])
    assert scr.rc == 130
    assert saves.waiting()["klondike"]["moves"] == 1
    assert store.get_stat("klondike")["total"] == 0
    assert store.notices() == []


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")
def test_a_signal_as_n_counts_the_game_leaves_it_unsaved(tui, monkeypatch):
    signal_once_written(monkeypatch, store.stats_path(), signal.SIGTERM)
    with cli._leave_on_signals():
        scr = tui(["d", "n"])
    assert scr.rc == 130
    assert store.get_stat("klondike")["total"] == 1
    assert [e["result"] for e in history.games()] == ["lost"]
    assert saves.waiting() == {}


def test_ctrl_c_before_a_move_or_on_the_menu_records_nothing(tui):
    assert tui([KeyboardInterrupt]).rc == 130
    assert tui([KeyboardInterrupt], start_key=None).rc == 130
    assert store.get_stat("klondike")["total"] == 0


def test_finishing_a_game_records_the_win_and_shows_the_banner(tui):
    scr = tui(["a", "m", "q"], game=near_won())
    assert scr.rc == 0
    assert "YOU WIN" in scr.frames[1]
    s = store.get_stat("klondike")
    assert s["wins"] == 1 and s["total"] == 1


def test_a_win_and_a_loss_both_go_in_the_history(tui):
    tui(["a", "n", "d", "n", "q"], game=near_won())
    assert [(e["result"], e["moves"]) for e in history.games()] == [("won", 1), ("lost", 1)]


def test_playing_again_from_the_menu_does_not_double_aisleriot_stats(tui, keyfile):
    # every return to the menu and every toggle saves the config the TUI
    # loaded at start, which must not undo the one-time merge
    keyfile("[klondike.scm]\nStatistic=10;40;120;900;\n")
    tui(["d", "n", "m", ENTER, "v", "d", "n", "q"])
    assert ar.read_stat("klondike.scm") == {"wins": 10, "total": 42, "best": 120, "worst": 900}


def one_move_left():
    """Golf with one move to make, the 6C onto the 5H, and none after it."""
    g = deal("golf", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[g.ids_of("waste")[0]].cards = [up(5, "H")]
    g.slots[t[0]].cards = [up(13, "S"), up(6, "C")]
    for sid, rank in zip(t[1:], (9, 10, 11, 12, 9, 10)):
        g.slots[sid].cards = [up(rank, "SH"[sid % 2])]
    return g


def test_the_no_moves_banner_can_take_the_last_move_back(tui):
    # f plays the 6C and leaves no moves; u on the banner takes it back
    scr = tui(["f", "u", "f", "m", "q"], start_key="golf", game=one_move_left())
    assert "No moves left" in scr.frames[1] and "Undo move" in scr.frames[1]
    assert "Moves 0" in scr.frames[2] and "No moves left" not in scr.frames[2]
    assert "No moves left" in scr.frames[3]
    assert "choose a game" in scr.frames[4]
    assert store.get_stat("golf")["total"] == 1  # counted once, on m


def test_the_no_moves_banner_counts_the_game_it_ends(tui):
    # the loss is only recorded on leaving the banner, but the numbers on it
    # should already be what the statistics will say
    scr = tui(["f", "m"], start_key="golf", game=one_move_left())
    assert "Wins/Total  : 0/1  (0%)" in scr.frames[1]
    assert store.get_stat("golf")["total"] == 1


@pytest.mark.parametrize("k", ["n", "m", KeyboardInterrupt])
def test_a_game_with_no_moves_left_counts_once_the_player_gives_it_up(tui, k):
    tui(["f", k], start_key="golf", game=one_move_left())
    assert store.get_stat("golf") == {"wins": 0, "total": 1, "best": 0, "worst": 0}


def test_replaying_a_deal_with_no_moves_left_does_not_count_it(tui):
    # AisleRiot's Restart on its game over dialog records nothing, like N
    scr = tui(["f", "s", "q"], start_key="golf", game=one_move_left())
    assert "No moves left" in scr.frames[1]
    assert "replaying the same deal" in scr.frames[2]
    assert store.get_stat("golf")["total"] == 0


def test_a_win_after_taking_back_the_dead_end_counts_as_a_win(tui):
    # 4D first leaves the 6C and 5S stuck; 6C, 5S, 4D clears the board
    g = deal("golf", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[g.ids_of("waste")[0]].cards = [up(5, "H")]
    g.slots[t[0]].cards = [up(4, "D")]
    g.slots[t[1]].cards = [up(5, "S"), up(6, "C")]
    scr = tui(
        ["f", "u", curses.KEY_RIGHT, "f", "f", curses.KEY_LEFT, "f", "m", "q"],
        start_key="golf",
        game=g,
    )
    assert "No moves left" in scr.frames[1]
    assert "YOU WIN" in scr.frames[7]
    assert store.get_stat("golf")["wins"] == 1
    assert store.get_stat("golf")["total"] == 1


# the banner's choices sit on rows 14-16 from column 6, marker included
BANNER_ROW = {"same": 14, "new": 15, "menu": 16}


def test_the_banner_ignores_the_pointer_the_wheel_and_other_buttons(tui):
    new = BANNER_ROW["new"]
    scr = tui(
        [
            "a",
            Mouse(new, 8, curses.REPORT_MOUSE_POSITION),
            Mouse(BANNER_ROW["same"], 8, curses.BUTTON4_PRESSED),
            Mouse(BANNER_ROW["menu"], 8, curses.BUTTON3_PRESSED),
            Mouse(new, 8, curses.BUTTON1_RELEASED),
            Mouse(new, 40, curses.BUTTON1_CLICKED),  # right of the label
            "m",
        ],
        game=near_won(),
    )
    assert all("YOU WIN" in frame for frame in scr.frames[1:7])
    assert "choose a game" in scr.frames[7]
    assert len(scr.uis) == 1


@pytest.mark.parametrize("bstate", [curses.BUTTON1_CLICKED, curses.BUTTON1_PRESSED])
def test_a_left_click_on_a_banner_choice_takes_it(tui, bstate):
    scr = tui(["a", Mouse(BANNER_ROW["new"], 8, bstate)], game=near_won())
    assert "YOU WIN" in scr.frames[1]
    assert "new deal" in scr.frames[2]


def test_the_banner_keeps_its_rows(tui, game_clock):
    won = tui(["a", "m"], game=near_won()).frames[1].split("\n")
    assert won[2:15] == [
        "      *** YOU WIN! ***",
        "",
        "      Game        : Klondike",
        "      Deal        : 1   share code klondike:1",
        "      Time        : 0:00",
        "      Score       : 4",
        "      Moves       : 1",
        "",
        "      Wins/Total  : 1/1  (100%)",
        "      Best time   : 0:01  (your first Klondike win!)",
        "",  # no streak on a first win
        "",
        "      > Replay this deal",
    ]
    # with no best time or streak their rows stay empty, so the choices
    # don't move up
    stuck = tui(["f", "m"], start_key="golf", game=one_move_left()).frames[1].split("\n")
    assert stuck[10:15] == ["      Wins/Total  : 0/1  (0%)", "", "", "", "      > Undo move"]


def test_the_banner_shows_the_deal_and_share_code(tui):
    banner = tui(["a", "m"], game=near_won(48213, draw=3)).frames[1]
    assert "      Deal        : 48213   share code klondike:d3:48213\n" in banner


def played_before(key, results):
    """Games of `key` won (True) or lost before the one about to be played."""
    g = deal(key, 1)
    for won in results:
        history.record(g, won, 60)


@pytest.mark.parametrize(
    "before, streak",
    [
        ([True], "Streak      : 2 wins in a row, your longest yet"),
        ([True, True, True, False, True], "Streak      : 2 wins in a row (longest 3)"),
        ([True, False], ""),
    ],
    ids=["two in a row", "short of the longest", "one after a loss"],
)
def test_the_banner_shows_a_streak_of_two_or_more(tui, before, streak):
    played_before("klondike", before)
    banner = tui(["a", "m"], game=near_won()).frames[1].split("\n")
    assert banner[12].strip() == streak
    assert banner[14] == "      > Replay this deal"


def test_the_no_moves_banner_shows_no_streak(tui):
    played_before("golf", [True, True, True])
    stuck = tui(["f", "m"], start_key="golf", game=one_move_left()).frames[1].split("\n")
    assert stuck[12] == ""


def banner_after_a_win_in_11_seconds(tui):
    # moving a king starts the clock, and the win comes 10.6 s on
    scr = tui(KING_TO_EMPTY + [Later(10.6, -1), "a", "m"], game=near_won())
    return next(frame for frame in scr.frames if "YOU WIN" in frame)


def test_win_note_on_a_first_win(tui, game_clock):
    banner = banner_after_a_win_in_11_seconds(tui)
    assert "Best time   : 0:11  (your first Klondike win!)\n" in banner


def test_win_note_on_a_new_best(tui, game_clock):
    store.record_result("klondike", won=True, seconds=300)
    banner = banner_after_a_win_in_11_seconds(tui)
    assert "Best time   : 0:11  (new best, was 5:00)\n" in banner


@pytest.mark.parametrize("best", [11, 5], ids=["equal", "slower"])
def test_a_win_equal_to_the_best_gets_no_note(tui, game_clock, best):
    store.record_result("klondike", won=True, seconds=best)
    banner = banner_after_a_win_in_11_seconds(tui)
    assert f"Best time   : {store.fmt_time(best)}\n" in banner


def test_the_banner_choices_follow_its_lines(tui, monkeypatch):
    lines = [f"Line {i}" for i in range(9)]  # rows 4 to 12
    monkeypatch.setattr(soliterm.tui.app.App, "banner_lines", lambda self, *args: lines)
    scr = tui(["a", Mouse(14, 8)], game=near_won())
    banner = scr.frames[1].split("\n")
    assert banner[12:19] == [
        "      Line 8",
        "",
        "      > Replay this deal",
        "        New deal",
        "        Back to menu",
        "",
        "      Up/Down + Enter, or s/n/m. Click to choose.",
    ]
    assert "replaying the same deal" in scr.frames[2]


# -- saved games ---------------------------------------------------------------------


def keep_one():
    """Put a Klondike game one deal in, 31 moves and 0:42 on, in the saves
    folder, as leaving it would have."""
    g = deal("klondike", 4)
    g.deal()
    g.moves = 31
    assert saves.keep(g, 42)


def test_the_menu_offers_a_saved_game(tui):
    keep_one()
    menu = tui(["q"], start_key=None).frames[0]
    assert "> Klondike         Resume your game: 0:42, 31 moves" in menu
    assert f"  Spider           {engine.GAMES['spider'].blurb}" in menu


def test_enter_on_it_resumes_with_the_clock_at_0_42(tui, game_clock):
    keep_one()
    scr = tui([ENTER, Later(10, -1), "n", "q"], start_key=None)
    assert "Resumed your game (0:42, 31 moves). n deals a new hand." in scr.frames[1]
    assert "Moves 31   Stock: 23  Waste: 1" in scr.frames[1]
    assert times(scr) == ["0:42", "0:52", "0:00"]
    assert saves.waiting() == {}


def test_game_flag_resumes_a_saved_game(tui):
    keep_one()
    scr = tui(["n", "q"])
    assert "Resumed your game (0:42, 31 moves)" in scr.frames[0]
    assert "Moves 31   Stock: 23  Waste: 1" in scr.frames[0]
    assert saves.waiting() == {}


@pytest.mark.parametrize(
    "start",
    [Deal("klondike", 5), Deal("klondike", None, {"draw": 3})],
    ids=["a deal number", "an option"],
)
def test_a_chosen_deal_leaves_the_save_waiting_and_says_so(tui, start):
    keep_one()
    scr = tui(["d", "q"], start=start)
    assert "a saved Klondike game is waiting, so this one won't be kept" in scr.frames[0]
    assert scr.uis[-1].game.moves == 1
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 31}}
    assert store.get_stat("klondike")["total"] == 1


def test_play_a_deal_from_the_menu_leaves_the_save_waiting(tui):
    keep_one()
    scr = tui([Mouse(PLAY_A_DEAL, 8), "5", ENTER, "q"], start_key=None)
    assert "Resume your game" in scr.frames[0]
    assert scr.uis[-1].game.deal_number == 5
    assert "a saved Klondike game is waiting, so this one won't be kept" in scr.frames[-1]
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 31}}


UNKEPT = "a saved Klondike game is waiting, so this one won't be kept"


@pytest.mark.parametrize(
    "keys",
    [["g", "6", ENTER], ["n"], ["o", curses.KEY_RIGHT, ENTER]],
    ids=["g", "n", "new options"],
)
def test_every_new_deal_says_the_save_waiting_leaves_no_room(tui, keys):
    keep_one()
    scr = tui([*keys, "q"], deal=5)
    assert UNKEPT in scr.frames[0]
    assert UNKEPT in scr.frames[len(keys)]


def test_the_banners_new_deal_says_so_too(tui):
    keep_one()
    scr = tui(KING_TO_EMPTY + ["a", "n", "q"], start=Deal("klondike", 5), game=near_won())
    assert "YOU WIN!" in scr.frames[-2]
    assert UNKEPT in scr.frames[-1]


def test_a_resumed_game_leaves_the_slot_free_for_the_next(tui):
    keep_one()
    scr = tui(["g", "6", ENTER, "y", "q"])
    assert "Resumed your game" in scr.frames[0]
    assert "playing klondike:6" in scr.frames[4]
    assert UNKEPT not in scr.frames[4]


def test_an_unreadable_save_deals_a_new_hand_and_says_so(tui):
    keep_one()
    path = saves.save_path("klondike")
    with open(path, encoding="utf-8") as fh:
        save = json.load(fh)
    # a card too many in the waste
    save["position"] = save["position"].replace("\ns1|waste|none|0|", "\ns1|waste|none|0|1SU,")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(save, fh)
    scr = tui([ENTER, "n", "q"], start_key=None)
    assert "Resume your game" in scr.frames[0]
    assert "Your saved game couldn't be read, so this is a new deal." in scr.frames[1]
    assert "Moves 0" in scr.frames[1]
    # set aside, it leaves room to keep the next
    assert "new deal" in scr.frames[2]
    assert glob.glob(path + ".corrupt-*")
    assert "was damaged" in store.notices()[0]


def test_a_save_picked_up_in_another_window_says_so(tui, monkeypatch):
    keep_one()
    listed = saves.waiting()
    # taken somewhere else once the menu has listed it
    monkeypatch.setattr(saves, "waiting", lambda: listed)
    os.remove(saves.save_path("klondike"))
    scr = tui([ENTER, "n", "q"], start_key=None)
    assert "Resume your game" in scr.frames[0]
    assert "Your saved game was picked up somewhere else, so this is a new deal." in scr.frames[1]
    assert "new deal" in scr.frames[2]
    assert store.notices() == []


def test_m_mid_game_saves_it(tui):
    scr = tui(["d", "m", "q"])
    assert "> Klondike         Resume your game: 0:00, 1 move" in scr.frames[2]
    assert store.get_stat("klondike")["total"] == 0


def test_q_with_the_slot_taken_counts_a_loss_and_says_why(tui):
    keep_one()
    tui(["d", "q"], deal=5)
    assert store.get_stat("klondike")["total"] == 1
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 31}}
    assert store.notices() == [
        "a saved Klondike game was already waiting, so this one counted as lost"
    ]


def test_n_on_a_resumed_game_counts_one_loss_with_the_whole_time(tui, game_clock, monkeypatch):
    counted = []
    real = store.record_result
    monkeypatch.setattr(store, "record_result", lambda *args: counted.append(args) or real(*args))
    tui(["d", Later(5, "q")])
    tui([Later(3, "n")])
    assert counted == [("klondike", False, 8)]
    assert saves.waiting() == {}


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX file modes, not root"
)
def test_a_save_that_cant_be_written_counts_a_loss(tui):
    os.makedirs(saves.saves_dir())
    os.chmod(saves.saves_dir(), 0o500)
    try:
        tui(["d", "q"])
    finally:
        os.chmod(saves.saves_dir(), 0o700)
    assert store.get_stat("klondike")["total"] == 1
    assert store.notices() == [
        f"couldn't save your Klondike game to {saves.save_path('klondike')}, so it counts as lost"
    ]


# -- options -------------------------------------------------------------------------

KING_TO_EMPTY = [ENTER] + [curses.KEY_RIGHT] * 4 + [ENTER]  # a first move on near_won()


def saved_draw():
    return store.game_options(store.load_config(), "klondike").get("draw")


def test_esc_on_the_options_goes_back_to_the_game_untouched(tui):
    scr = tui(KING_TO_EMPTY + ["o", curses.KEY_RIGHT, ESC, -1, "a", "m"], game=near_won())
    assert any("Klondike - options" in frame for frame in scr.frames)
    assert len(scr.uis) == 1 and saved_draw() is None
    # nothing was recorded when the options came up, so the win is a win
    s = store.get_stat("klondike")
    assert s["wins"] == 1 and s["total"] == 1


def test_leaving_the_options_as_they_were_keeps_the_game(tui):
    scr = tui(["d", "o", ENTER])
    assert len(scr.uis) == 1
    assert "Moves 1" in scr.frames[-1] and "options unchanged" in scr.frames[-1]
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting()["klondike"]["moves"] == 1  # from the q


def test_new_options_mid_game_ask_before_dealing_again(tui):
    scr = tui(["d", "o", curses.KEY_RIGHT, ENTER, "n", "o", curses.KEY_RIGHT, ENTER, "y"])
    asked = [i for i, frame in enumerate(scr.frames) if "count as lost" in frame]
    assert len(asked) == 2
    # n: the same game, and nothing saved or counted
    assert "Moves 1" in scr.frames[asked[0] + 1]
    # y: the old game counts as lost and the new one draws three
    assert len(scr.uis) == 2 and scr.uis[1].game.options["draw"] == 3
    assert saved_draw() == 3
    assert store.get_stat("klondike")["total"] == 1


def test_enter_twice_on_new_options_keeps_the_game(tui):
    # the second Enter lands on the question the first one raised
    scr = tui(["d", "o", curses.KEY_RIGHT, ENTER, ENTER])
    assert "count as lost" in scr.frames[4] and "Enter  no" in scr.frames[4]
    assert len(scr.uis) == 1 and "Moves 1" in scr.frames[5]
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting()["klondike"]["moves"] == 1  # from the q


def test_new_options_before_a_move_just_deal_again(tui):
    scr = tui(["o", curses.KEY_RIGHT, ENTER])
    assert not any("count as lost" in frame for frame in scr.frames)
    assert len(scr.uis) == 2 and scr.uis[1].game.options["draw"] == 3
    assert store.get_stat("klondike")["total"] == 0


def test_the_options_screen_deals_on_like_n(tui):
    # a session on a chosen deal goes on to the next one, whichever key
    # asked for the new deal
    scr = tui(["o", curses.KEY_LEFT, ENTER], start_key="spider", deal=6)
    game = scr.uis[-1].game
    assert game.options["suits"] == 2
    assert game.deal_number == 7
    want = deal("spider", 7, suits=2)
    assert [s.cards for s in game.slots] == [s.cards for s in want.slots]


NO_OPTIONS = [key for key in engine.GAME_ORDER if not engine.GAMES[key].option_spec()]


@pytest.mark.parametrize("key", NO_OPTIONS)
def test_o_leaves_a_game_without_options_as_it_was(tui, game_clock, key):
    # a move, o ten seconds on, and the statistics five seconds after that
    g = deal(key, 3)
    moved = g.clone()
    best = g.best_move()
    if best is None:
        # Golf deals with the waste empty, so its first move is a deal
        assert moved.deal()
        move = ["d"]
    else:
        src, dst, n = best
        assert moved.attempt_move(src, dst, n)
        move = [Click(src, len(g.cards(src)) - n), Click(dst, max(0, len(g.cards(dst)) - 1))]
    m = len(move)
    scr = tui(move + [Later(10, "o"), Later(5, "s"), "z"], start_key=key, game=g)
    name = g.gamedef.name
    assert f"{name} has no options" in scr.frames[m + 1]
    assert re.search(rf"{name} +0 +0 ", scr.frames[m + 2])
    assert "Moves 1" in scr.frames[m + 3]
    assert times(scr)[m : m + 3] == ["0:00", "0:10", "0:15"]
    assert len(scr.uis) == 1 and scr.uis[0].game is g
    assert g.serialize() == moved.serialize()
    assert store.get_stat(key)["total"] == 0
    assert saves.waiting() == {key: {"seconds": 15, "moves": 1}}  # from the q


# -- the menu ------------------------------------------------------------------------


def test_q_on_the_menu_exits(tui):
    scr = tui(["q"], start_key=None)
    assert scr.rc == 0
    assert "choose a game" in scr.frames[0]
    assert not scr.uis


def test_the_menu_the_board_and_the_help_are_titled_soliterm(tui):
    scr = tui([ENTER, "?", "z", "m", "q"], start_key=None)
    menu, board, help_screen = scr.frames[:3]
    assert "Soliterm  -  choose a game" in menu
    assert "Soliterm  -  Klondike" in board
    assert "Soliterm - controls" in help_screen
    assert not any("AisleRiot CLI" in frame for frame in scr.frames)


def test_the_release_of_the_click_on_the_menu_does_nothing_on_the_board(tui):
    klondike = 4  # the first game on the menu
    scr = tui(
        [
            Mouse(klondike, 8, curses.BUTTON1_PRESSED),
            Mouse(klondike, 8, curses.BUTTON1_RELEASED),
            "q",
        ],
        start_key=None,
    )
    assert scr.uis[0].hit_test(klondike, 8) is not None
    assert "Moves 0" in scr.frames[2]
    assert scr.uis[0].selections[-1] is None
    assert store.get_stat("klondike")["total"] == 0


def test_the_release_of_the_click_on_the_banner_does_nothing_on_the_new_deal(tui):
    new = BANNER_ROW["new"]
    # FreeCell, as its next deal has a card under the choice
    scr = tui(
        ["a", Mouse(new, 12, curses.BUTTON1_PRESSED), Mouse(new, 12, curses.BUTTON1_RELEASED)],
        start_key="freecell",
        game=near_won(key="freecell"),
    )
    ui = scr.uis[0]
    assert ui.hit_test(new, 12) is not None
    assert "new deal" in scr.frames[3]
    assert ui.selections[-1] is None


def test_the_release_of_the_click_on_back_to_menu_leaves_the_menu_cursor_alone(tui):
    menu = BANNER_ROW["menu"]  # the row of Quit on the menu
    scr = tui(
        [
            "a",
            Mouse(menu, 8, curses.BUTTON1_PRESSED),
            Mouse(menu, 8, curses.BUTTON1_RELEASED),
            ENTER,
            "q",
        ],
        game=near_won(),
    )
    assert "choose a game" in scr.frames[2]
    assert "> Klondike" in scr.frames[3]
    assert "> Quit" not in scr.frames[3]
    assert len(scr.uis) == 2  # Enter played Klondike, not quit


def test_the_menu_starts_the_chosen_game_and_remembers_it(tui):
    scr = tui([curses.KEY_DOWN, ENTER, "m", "q"], start_key=None)
    assert scr.rc == 0
    assert [ui.game.gamedef.key for ui in scr.uis] == ["spider"]
    assert store.load_config()["last_game"] == "spider"


PLAY_A_DEAL = 4 + len(engine.GAME_ORDER) + 1  # the menu's row under the games


def test_play_a_deal_from_the_menu_plays_the_last_game_for_a_bare_number(tui):
    cfg = store.load_config()
    cfg["last_game"] = "spider"
    store.set_game_options(cfg, "spider", {"suits": 2})
    store.save_config(cfg)
    scr = tui([Mouse(PLAY_A_DEAL, 8), "7", ENTER], start_key=None)
    assert "  Play a deal" in scr.frames[0].split("\n")[PLAY_A_DEAL]
    box = scr.frames[1]
    assert "Play a deal" in box and "A number on its own plays Spider." in box
    assert "This deal" not in box
    # with the saved options, as a game picked from the menu has
    g = scr.uis[-1].game
    assert (g.gamedef.key, g.deal_number, g.options) == ("spider", 7, {"suits": 2})
    assert soliterm.tui.app.START_MESSAGE in scr.frames[3]


def test_play_a_deal_from_the_menu_takes_a_share_code(tui):
    scr = tui([Mouse(PLAY_A_DEAL, 8), *"golf:5", ENTER], start_key=None)
    g = scr.uis[-1].game
    assert (g.gamedef.key, g.deal_number) == ("golf", 5)
    assert store.load_config()["last_game"] == "golf"


def test_esc_on_play_a_deal_goes_back_to_the_menu(tui):
    scr = tui([Mouse(PLAY_A_DEAL, 8), ESC, -1], start_key=None)
    assert "A number on its own plays" in scr.frames[1]
    assert "choose a game" in scr.frames[-1]
    assert not scr.uis


# -- colour --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "saved, flag, no_color, shown",
    [
        (True, False, False, False),  # --no-color beats the saved choice
        (True, None, True, False),  # and so does NO_COLOR
        (False, True, True, True),  # --color beats both
        (False, None, False, False),  # with neither, the saved choice holds
        (None, None, False, True),  # and with nothing saved, the terminal's
    ],
)
def test_colour_goes_by_the_flag_then_no_color_then_the_saved_choice(
    tui, monkeypatch, saved, flag, no_color, shown
):
    if saved is not None:
        cfg = store.load_config()
        cfg["color"] = saved
        store.save_config(cfg)
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    scr = tui([], color=flag)
    assert scr.uis[0].initial_has_color is shown
    assert store.load_config().get("color") == saved  # only v saves it


def test_the_tui_hears_whether_a_colour_flag_was_given(monkeypatch):
    seen = {}
    monkeypatch.setattr(soliterm.tui, "main", lambda *a, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_terminal_problem", lambda: None)
    for argv, color in ([], None), (["--color"], True), (["--no-color"], False):
        cli.main(["--game", "klondike"] + argv)
        assert seen["color"] is color


def test_no_animation_reaches_the_tui(monkeypatch):
    seen = {}
    monkeypatch.setattr(soliterm.tui, "main", lambda *a, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_terminal_problem", lambda: None)
    for argv, animation in ([], None), (["--no-animation"], False):
        cli.main(["--game", "klondike"] + argv)
        assert seen["animation"] is animation


def pair_of(attr, scr):
    """The (fg, bg) of the colour pair in attr, as the tui fixture set it up."""
    n = (attr >> 8) & 0xFF
    return next(pair[1:] for pair in scr.pairs if pair[0] == n)


# what washes out on a white background
PALE = {curses.COLOR_YELLOW, curses.COLOR_CYAN, curses.COLOR_WHITE}


def test_a_light_terminal_gets_text_that_shows_on_white(tui, monkeypatch):
    # rxvt and Konsole put "foreground;background" here: black on white
    monkeypatch.setenv("COLORFGBG", "0;15")
    scr = tui(["q"])
    on_the_terminal = [pair[1] for pair in scr.pairs if pair[2] == -1]
    assert on_the_terminal and not PALE & set(on_the_terminal)


def test_a_dark_terminal_keeps_cyan_and_yellow_text(tui, monkeypatch):
    monkeypatch.setenv("COLORFGBG", "15;0")
    scr = tui(["q"])
    on_the_terminal = {pair[1] for pair in scr.pairs if pair[2] == -1}
    assert on_the_terminal == {curses.COLOR_CYAN, curses.COLOR_YELLOW}


def test_a_hinted_card_has_a_background_of_its_own(tui):
    # so it reads on a light terminal as well as a dark one
    g = deal("klondike", 1)
    scr = tui(["h"], game=g)
    ui = scr.uis[-1]
    card = g.slots[g.hint()[0]].top
    fg, bg = pair_of(ui.card_attr(card, False, True), scr)
    assert bg not in (-1, fg)


def test_v_on_a_mono_terminal_just_says_so(tui):
    scr = tui(["v"], color_capable=False)
    assert "this terminal has no colour support" in scr.frames[1]
    assert scr.pairs == []
    assert "color" not in store.load_config()


def test_v_turns_colour_off_and_on_and_saves_it(tui):
    scr = tui(["v", "v"])
    assert len(scr.pairs) == 9
    ui = scr.uis[0]
    assert ui.initial_has_color
    assert "colour off" in scr.frames[1]
    assert "colour on" in scr.frames[2]
    assert ui.has_color is True
    assert store.load_config()["color"] is True


def test_v_after_no_color_turns_colour_on(tui):
    # pairs are set up on capability, so colour can come on later
    scr = tui(["v"], color=False)
    assert len(scr.pairs) == 9
    ui = scr.uis[0]
    assert not ui.initial_has_color
    assert ui.has_color is True
    assert store.load_config()["color"] is True


@pytest.mark.parametrize("key, title", [("?", "Soliterm - controls"), ("s", "Statistics")])
def test_help_and_stats_stay_up_until_a_key_is_pressed(tui, key, title):
    scr = tui(
        [
            key,
            Mouse(9, 9, curses.REPORT_MOUSE_POSITION),
            Mouse(9, 9, curses.BUTTON1_RELEASED),
            Mouse(9, 9, curses.BUTTON4_PRESSED),
            Resize(30, 100),
            "z",
        ]
    )
    assert all(title in frame for frame in scr.frames[1:6])
    assert "Score" in scr.frames[6]
    # drawn again after the resize
    assert len(scr.frames[5].split("\n")) == 30


def test_the_stats_screen_shows_streak_columns(tui):
    for key, results in [("klondike", [True, True, False, True]), ("golf", [True, True])]:
        g = deal(key, 1)
        for won in results:
            history.record(g, won, 60)
    lines = [line.rstrip() for line in tui(["s", "z"]).frames[1].split("\n")]
    assert "      Game              Wins  Total   Win%    Best   Worst  Streak Longest" in lines
    assert "      Klondike             3      4    75%    1:00    1:00       1       2" in lines
    assert "      Golf                 2      2   100%    1:00    1:00       2       2" in lines
    # a game with no history here has no streak to show
    assert "      Spider               0      0    N/A     N/A     N/A     N/A     N/A" in lines


def test_the_help_screen_lists_the_toggles(tui):
    scr = tui(["?", "z"])
    assert "toggle colour" in scr.frames[1]
    assert "boss mode" in scr.frames[1]


# -- boss mode, code skin and view --------------------------------------------------------


@pytest.mark.parametrize("key", ["b", curses.KEY_F2])
def test_the_boss_key_hides_the_board_until_a_key_is_pressed(tui, key):
    scr = tui([key, "z"])
    assert "Score" in scr.frames[0]
    camo = scr.frames[1]
    assert camo.strip() and "Score" not in camo and "+--" not in camo
    assert "Score" in scr.frames[2]


# how to reach each screen that isn't the board: a line it shows, the game
# to start (None for the menu), a board to start on and the keys to get there
EVERY_SCREEN = [
    ("choose a game", None, None, []),
    ("Statistics", "klondike", None, ["s"]),
    ("Soliterm - controls", "klondike", None, ["?"]),
    ("Klondike - options", "klondike", None, ["o"]),
    ("count as lost", "klondike", None, ["d", "o", curses.KEY_RIGHT, ENTER]),
    ("YOU WIN", "klondike", near_won, ["a"]),
    ("No moves left", "golf", one_move_left, ["f"]),
    ("Play a deal", "klondike", None, ["g"]),
    ("A number on its own plays", None, None, [Mouse(PLAY_A_DEAL, 8)]),
]
# the screens where b is a letter to type, so only F2 hides them
TYPED_IN = ("Play a deal", "A number on its own plays")
# Esc then leaves the pick-deal box, where q is a letter to type. It changes
# nothing on the other screens, and the -1 says no key came in behind it.
OUT = [ESC, -1]


@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_the_boss_key_works_on_every_screen_and_comes_back_to_it(
    tui, screen, start_key, game, keys
):
    boss = curses.KEY_F2 if screen in TYPED_IN else "b"
    scr = tui(keys + [boss, "z", *OUT], start_key=start_key, game=game and game())
    shown, hidden, back = scr.frames[len(keys) : len(keys) + 3]
    assert screen in shown
    assert hidden.strip() and screen not in hidden and "Score" not in hidden
    assert screen in back


def test_only_a_key_ends_boss_mode_not_the_mouse_or_a_resize(tui):
    scr = tui(
        [
            "b",
            Mouse(9, 40, curses.REPORT_MOUSE_POSITION),
            Mouse(9, 40, curses.BUTTON4_PRESSED),
            Mouse(9, 40, curses.BUTTON1_PRESSED),  # clicking to focus the window
            Resize(30, 100),
            "z",
        ]
    )
    assert "Score" in scr.frames[0]
    hidden = scr.frames[1:6]
    assert all(frame.strip() and "Score" not in frame for frame in hidden)
    assert "Score" in scr.frames[6]
    # the disguise is drawn again to fill the new size
    assert len(scr.frames[5].split("\n")) == 30
    assert max(len(line) for line in scr.frames[5].split("\n")) > 80


def test_tab_in_boss_mode_switches_and_saves_the_disguise(tui):
    tui(["b", "\t", "z"])
    assert store.load_config()["camo_theme"] == "test"


def test_c_toggles_the_code_skin_and_saves_it(tui):
    scr = tui(["c"])
    assert "solver.py" in scr.frames[1]
    assert store.load_config()["code_skin"] is True
    tui(["c"])  # the saved skin comes back on, and c turns it off
    assert store.load_config()["code_skin"] is False


def code_skin_on():
    cfg = store.load_config()
    cfg["code_skin"] = True
    store.save_config(cfg)


@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_the_code_skin_keeps_every_screen_inside_the_code_file(tui, screen, start_key, game, keys):
    code_skin_on()
    scr = tui(keys + OUT, start_key=start_key, game=game and game())
    rows = scr.frames[len(keys)].split("\n")
    assert "solver.py" in rows[0]
    # a line number down every row, and the screen written as a comment
    assert all(re.match(r" *\d+\b", row) for row in rows[1:-1])
    shown = [row for row in rows if screen in row]
    assert shown and all(re.match(r" *\d+  # ", row) for row in shown)


def test_the_code_skin_keeps_the_too_small_notice_inside_the_code_file(tui):
    code_skin_on()
    scr = tui([], h=15, w=80)
    rows = scr.frames[0].split("\n")
    assert "solver.py" in rows[0]
    shown = [row for row in rows if "Terminal too small" in row or "needs" in row]
    assert len(shown) == 2 and all(re.match(r" *\d+  # ", row) for row in shown)


@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_a_screen_too_tall_for_the_terminal_says_so(tui, screen, start_key, game, keys):
    # rather than lose its last lines off the bottom
    scr = tui(keys + [Resize(40, 120), *OUT], start_key=start_key, game=game and game())
    rows = scr.frames[len(keys)].rstrip().split("\n")
    need = len(rows)
    scr = tui(
        keys + [Resize(need - 1, 120), Resize(need, 120), *OUT],
        start_key=start_key,
        game=game and game(),
    )
    small, roomy = scr.frames[len(keys) + 1 : len(keys) + 3]
    assert "Terminal too small" in small and f"needs 40x{need}" in small
    assert screen not in small
    shown = roomy.rstrip().split("\n")
    assert len(shown) == need and shown[-1] == rows[-1]


def test_keys_the_player_cannot_see_do_nothing_on_a_small_menu(tui):
    # Enter here would start whichever game is highlighted
    scr = tui([ENTER, curses.KEY_DOWN, ENTER, "q"], start_key=None, h=12)
    assert "Terminal too small" in scr.frames[0]
    assert scr.uis == []
    assert scr.rc == 0


def test_a_click_on_a_banner_choice_finds_it_under_the_code_skin(tui):
    code_skin_on()
    new = BANNER_ROW["new"]
    # the skin moves the choices right, past the comment mark
    scr = tui(["a", Mouse(new, 8), Mouse(new, 18)], game=near_won())
    assert "YOU WIN" in scr.frames[2]
    assert "new deal" in scr.frames[3]


def test_x_toggles_the_view_and_the_next_game_uses_it(tui):
    scr = tui(["x"])
    assert scr.uis[0].view == "legacy"
    assert store.load_config()["view"] == "legacy"
    scr = tui([])
    assert scr.uis[-1].view == "legacy"


SCREENSHOTS = os.path.join(os.path.dirname(__file__), "..", "tools", "screenshots.py")
# the tmux key names the screenshot tool sends, as curses hands them over
TMUX_KEYS = {
    "Enter": ENTER,
    "Left": curses.KEY_LEFT,
    "Right": curses.KEY_RIGHT,
    "Up": curses.KEY_UP,
    "Down": curses.KEY_DOWN,
}


def screenshot_tool():
    spec = importlib.util.spec_from_file_location("screenshots", SCREENSHOTS)
    shots = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shots)
    return shots


def scene_start(scene):
    """What the TUI starts on for a scene's --deal."""
    return deals.deal_of(deals.parse(scene.deal), "klondike") if scene.deal else None


@pytest.mark.skipif(not os.path.exists(SCREENSHOTS), reason="no tools/ in this tree")
def test_the_spider_screenshot_deals_two_suits_and_makes_its_move(tui):
    shots = screenshot_tool()
    (scene,) = [s for s in shots.SCENES if s.name == "spider"]
    keys = [TMUX_KEYS.get(k, k) for step in scene.steps for k in step.keys.split()]
    scr = tui(keys, start=scene_start(scene), h=shots.ROWS, w=shots.COLS)
    last = scr.frames[len(keys)]
    assert "♥" in last and "♠" in last
    assert "Moves 1 " in last and "Hint: Move" in last


# the moves each scene makes on its way to its last shot, and whether that
# shot shows a hint
SCENE_MOVES = {
    "klondike-in-play": (5, True),
    "freecell": (1, True),
    "spider": (1, True),
    "code-skin": (1, False),
    "boss-mode": (0, False),
    "hero": (3, False),
}


@pytest.mark.skipif(not os.path.exists(SCREENSHOTS), reason="no tools/ in this tree")
def test_screenshot_scenes_still_reach_their_shots(tui):
    # the keys were worked out by hand for each deal, so they go stale the
    # moment a deal number deals another hand
    shots = screenshot_tool()
    scenes = [s for s in shots.SCENES if s.deal]
    assert sorted(s.name for s in scenes) == sorted(SCENE_MOVES)
    for scene in scenes:
        keys = [TMUX_KEYS.get(k, k) for step in scene.steps for k in step.keys.split()]
        # b and c would hide the board this test reads
        keys = [k for k in keys if k not in ("b", "c")]
        scr = tui(keys, start=scene_start(scene), h=shots.ROWS, w=shots.COLS)
        frames = scr.frames[: len(keys) + 1]
        assert not any("illegal move" in frame for frame in frames), scene.name
        moves, hint = SCENE_MOVES[scene.name]
        assert f"Moves {moves} " in frames[-1], scene.name
        assert ("Hint: Move" in frames[-1]) is hint, scene.name
