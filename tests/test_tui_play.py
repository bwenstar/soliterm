"""Drive the real curses loop, soliterm.tui.run(), with scripted keys and clicks.

The curses calls that need a real terminal are stubbed out, and the window is
a FakeScr that plays back a key script and remembers what was on screen each
time the game asked for a key.
"""

import base64
import curses
import functools
import glob
import importlib.util
import json
import os
import re
import signal
import sys
import threading
from datetime import date
from types import SimpleNamespace

import pytest

import soliterm.tui
from soliterm import aisleriot as ar
from soliterm import cli, clipboard, deals, engine, history, saves, store, themes
from soliterm.deals import Deal
from soliterm.engine import Card, GameDef
from soliterm.tui import cascade
from soliterm.tui.app import basic_colours, note_pages
from soliterm.tui.board import CODE_GUTTER
from soliterm.tui.keys import help_lines
from soliterm.tui.screens import DEAL_TEXT_MAX

from helpers import (
    PDCURSES_NUMPAD,
    FakeScr,
    FakeWin32,
    OtherCopy,
    clear_board,
    crashed,
    deal,
    from_before_the_counts,
    in_play_elsewhere,
    more_keys,
    nothing_in_play,
    saved,
    signal_as_it_waits,
    signal_once_written,
    stalled_klondike,
)

ENTER = "\n"
ESC = 27
DAY = date(2026, 9, 24)  # the day of the daily deals here


class Click:
    """A left click on card idx of slot sid, found through the live hit map."""

    def __init__(self, sid, idx, bstate=curses.BUTTON1_CLICKED):
        self.sid, self.idx, self.bstate = sid, idx, bstate


class Again:
    """Another mouse event where the last one was, as a double-click makes."""

    def __init__(self, bstate):
        self.bstate = bstate


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


class Meanwhile:
    """Key k, pressed once fn has run, as another window would run it."""

    def __init__(self, fn, k):
        self.fn, self.k = fn, k


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
        # what was drawn in the cursor's colours each time, by row
        self.cursor_rows = []
        self.mouse = None
        self.spare = 0
        self.delay = -1  # how long getch waits for a key, in ms; -1 for ever
        self.delays = []  # the delay each key was read with

    def erase(self):
        super().erase()
        self.lit = {}

    def addnstr(self, y, x, text, n, attr=0):
        super().addnstr(y, x, text, n, attr)
        if attr & curses.A_COLOR == curses.color_pair(themes.CURSOR) and text.strip():
            self.lit[y] = text

    def nodelay(self, flag):
        self.delay = 0 if flag else -1

    def timeout(self, ms):
        self.delay = ms

    def getch(self):
        self.frames.append(self.text())
        self.cursor_rows.append(dict(self.lit))
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
        if isinstance(k, Meanwhile):
            k.fn()
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
        if isinstance(k, Again):
            self.mouse = (*self.mouse[:4], k.bstate)
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
    built by hand, and via_main=True to go through main(). The returned screen
    has .frames, .rc, .uis (every BoardUI made, each with .selections and
    .said), .pairs (init_pair calls), .masks (mousemask calls) and
    .intervals (mouseinterval calls).
    """
    uis, pairs, masks, intervals = [], [], [], []

    class RecordingBoardUI(soliterm.tui.BoardUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.initial_has_color = self.has_color
            self.selections = []  # the selected slot at every draw
            self.said = []  # and what the message line said
            uis.append(self)

        def draw(self, selected_slot, selected_n, cursor, hint, elapsed, message, *args):
            self.selections.append(selected_slot)
            self.said.append(message)
            return super().draw(selected_slot, selected_n, cursor, hint, elapsed, message, *args)

    monkeypatch.setattr(soliterm.tui.app, "BoardUI", RecordingBoardUI)
    # set here rather than in run() so a test can put its own in first
    monkeypatch.setattr(curses, "curs_set", lambda n: None)
    monkeypatch.setattr(curses, "use_default_colors", lambda: None)
    # a test that wants a light background sets COLORFGBG itself, and one
    # in Windows Terminal or ConEmu sets what windows-curses goes by there
    monkeypatch.delenv("COLORFGBG", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("CONEMUANSI", raising=False)

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
        colours=8,
        color_pairs=256,
        via_main=False,
        **kwargs,
    ):
        scr = ScriptedScr(h, w, keys, uis)
        kwargs.setdefault("animation", False)  # a test that wants it says so
        monkeypatch.setattr(curses, "mousemask", lambda mask: masks.append(mask) or (mask, 0))
        monkeypatch.setattr(curses, "mouseinterval", intervals.append)
        monkeypatch.setattr(curses, "has_colors", lambda: color_capable)
        monkeypatch.setattr(curses, "start_color", lambda: None)
        # curses only has these once start_color has run
        monkeypatch.setattr(curses, "COLORS", colours, raising=False)
        monkeypatch.setattr(curses, "COLOR_PAIRS", color_pairs, raising=False)

        def init_pair(*pair):
            # as curses does, near enough, for a pair the terminal has no
            # room for
            if pair[0] >= color_pairs:
                raise ValueError(f"Color pair is greater than COLOR_PAIRS-1 ({color_pairs - 1}).")
            pairs.append(pair)

        monkeypatch.setattr(curses, "init_pair", init_pair)
        monkeypatch.setattr(curses, "color_pair", lambda n: n << 8)
        # where color_pair puts the pair, as ncurses has it (PDCurses keeps
        # it higher up)
        monkeypatch.setattr(curses, "A_COLOR", 0xFF00)

        def pair_content(n):
            # the colours init_pair last gave n, and pair 0 the terminal's
            return next((pair[1:] for pair in reversed(pairs) if pair[0] == n), (-1, -1))

        monkeypatch.setattr(curses, "pair_content", pair_content)
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
            if via_main:
                # the way the command line starts it, curses handing main() the screen
                monkeypatch.setattr(curses, "wrapper", lambda fn, *args, **kw: fn(scr, *args, **kw))
                scr.rc = soliterm.tui.main(start, color=color, **kwargs)
            else:
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


# -- the numpad on Windows -----------------------------------------------------------


@pytest.fixture
def pad(monkeypatch):
    """curses as windows-curses has it, with codes of its own for some of
    the numpad keys. Returns the codes by name."""
    for name, code in PDCURSES_NUMPAD.items():
        monkeypatch.setattr(curses, name, code, raising=False)
    return SimpleNamespace(**PDCURSES_NUMPAD)


def test_numpad_enter_picks_up_and_drops_on_windows(tui, pad):
    g, _a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(5, "H")], suits=4)
    tui([pad.PADENTER, curses.KEY_RIGHT, pad.PADENTER], start_key="spider", game=g)
    assert names(g, b) == ["5H", "4S", "3S"]


def test_numpad_minus_and_plus_change_the_lift_on_windows(tui, pad):
    g, a, b = board("spider", [up(9, "H"), up(7, "S"), up(6, "S"), up(5, "S")], [], suits=4)
    keys = [ENTER, pad.PADMINUS, pad.PADMINUS, pad.PADPLUS, curses.KEY_RIGHT, ENTER]
    tui(keys, start_key="spider", game=g)
    assert names(g, b) == ["6S", "5S"]
    assert names(g, a) == ["9H", "7S"]


def test_the_numpad_arrows_move_the_cursor_on_windows(tui, pad):
    # with NumLock off: two right and one left is the next column
    g, _a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(5, "H")], suits=4)
    tui([ENTER, pad.KEY_B3, pad.KEY_B3, pad.KEY_B1, ENTER], start_key="spider", game=g)
    assert names(g, b) == ["5H", "4S", "3S"]
    # and up is the stock, where Enter deals, until down comes back
    waste = deal("klondike", 1).ids_of("waste")[0]
    scr = tui([pad.KEY_A2, ENTER], deal=1)
    assert len(scr.uis[-1].game.cards(waste)) == 1
    scr = tui([pad.KEY_A2, pad.KEY_C2, ENTER], deal=1)
    assert len(scr.uis[-1].game.cards(waste)) == 0


def test_numpad_enter_plays_from_the_menu_on_windows(tui, pad):
    scr = tui([pad.PADENTER], start_key=None)
    assert [ui.game.gamedef.key for ui in scr.uis] == ["klondike"]


def test_the_numpad_types_a_share_code_and_enter_plays_it_on_windows(tui, pad):
    scr = tui(["g", *"spider", pad.PADSLASH, "7", pad.PADENTER], deal=5)
    assert "> spider/7_" in scr.frames[9]
    assert [(ui.game.gamedef.key, ui.game.deal_number) for ui in scr.uis][-1] == ("spider", 7)


@pytest.mark.parametrize("target", [(9, "D"), (4, "H")])
def test_a_clicked_split_is_never_shrunk_to_fit(tui, target):
    # clicking the 4S lifts 4S-3S exactly; on 4H the 3S alone would fit, but
    # the player asked for two cards
    g, a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(*target)], suits=4)
    before = g.serialize()
    scr = tui([Click(a, 1), Click(b, 0)], start_key="spider", game=g)
    assert "picked up 2 cards from 4♠" in scr.frames[1]
    assert "illegal move" in scr.frames[2]
    assert g.serialize() == before


@pytest.mark.parametrize(
    "symbols, encoding, spade",
    [(True, "utf-8", "♠"), (False, "utf-8", "S"), (True, "ascii", "S")],
)
def test_what_is_lifted_is_named_as_the_board_shows_it(tui, monkeypatch, symbols, encoding, spade):
    # --ascii, or a terminal that can't show the suits, gets the letter
    monkeypatch.setattr(FakeScr, "encoding", encoding)
    g, a, _b = board("spider", [up(9, "H"), up(5, "S"), up(4, "S"), up(3, "S")], [], suits=4)
    scr = tui([Click(a, 1), "-", "-"], start_key="spider", game=g, symbols=symbols)
    assert f"picked up 3 cards from 5{spade}" in scr.frames[1]
    assert f"holding 2 cards from 4{spade}" in scr.frames[2]
    assert f"holding 3{spade}" in scr.frames[3]


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
    assert "picked up 11 cards from J♠" in scr.frames[1]
    assert "holding 10 cards from 10♠" in scr.frames[4]
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


def test_the_hint_key_names_a_move_when_nothing_gains(tui):
    scr = tui(["h"], start_key="freecell", game=deal("freecell", 1))
    assert "Hint: Move 6♠ to a free cell" in scr.frames[1]


def test_the_hint_lights_up_as_many_cards_as_it_moves(tui, monkeypatch):
    # K♣ and Q♥ go aside to free 5♠; K♦ could take all four, for nothing
    g, _, _ = board("yukon", [up(13, "D"), up(5, "S"), up(13, "C"), up(12, "H")], [])
    g.slots[g.ids_of("foundation")[0]].cards = [up(r, "S") for r in range(1, 5)]
    lit = []
    real = soliterm.tui.BoardUI.draw

    def draw(self, *args):
        lit.append(args[-1])  # how many cards the hint lights up
        return real(self, *args)

    monkeypatch.setattr(soliterm.tui.BoardUI, "draw", draw)
    scr = tui(["h"], start_key="yukon", game=g)
    assert "Hint: Move K♣ to the empty column" in scr.frames[1]
    assert lit[1] == 2


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


def test_the_title_names_a_daily(tui):
    scr = tui([], start=deals.daily("fortythieves", DAY))
    assert "Soliterm  -  Forty Thieves  -  Daily 2026-09-24" in scr.frames[0]


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


def test_g_on_a_daily_names_its_day(tui):
    scr = tui(["g", *"klondike:20260924", ENTER], start=deals.daily("klondike", DAY))
    box = scr.frames[1]
    assert "This deal   : daily 2026-09-24" in box
    assert "Share code  : klondike:20260924" in box
    assert "that's the deal in play (N starts it over)" in scr.frames[-1]
    assert scr.uis[-1].game.daily == "2026-09-24"


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
    monkeypatch.setattr(cli, "_check_terminal", lambda: ("", ""))
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


class WideWindow:
    """A window of a curses built wide, as ncursesw and windows-curses
    are, which is what gives it get_wch."""

    def __init__(self, encoding):
        self.encoding = encoding

    def get_wch(self):
        return -1


class NarrowWindow:
    """A window of a curses built narrow, which encodes every string
    through its encoding."""

    def __init__(self, encoding):
        self.encoding = encoding


@pytest.mark.parametrize(
    "platform, window, drawn",
    [
        # windows-curses says the console's code page, which has no suits,
        # but hands the console the characters themselves
        ("win32", WideWindow("cp850"), True),
        ("win32", WideWindow("cp1252"), True),
        # a narrow build would encode them through it, and can't
        ("win32", NarrowWindow("cp850"), False),
        ("win32", NarrowWindow("utf-8"), True),
        # elsewhere the encoding is the locale's, which ncursesw goes by
        ("linux", WideWindow("ascii"), False),
        ("linux", WideWindow("cp850"), False),
        ("linux", WideWindow("utf-8"), True),
        ("darwin", WideWindow("ascii"), False),
    ],
)
def test_the_suits_are_drawn_where_the_console_takes_them(platform, window, drawn, monkeypatch):
    from soliterm.tui.board import can_draw_unicode

    monkeypatch.setattr(sys, "platform", platform)
    assert can_draw_unicode(window) is drawn


def test_a_windows_console_gets_the_card_art(tui, monkeypatch):
    # windows-curses says cp850 and draws the suits all the same, where the
    # board used to fall back to ASCII for it
    def addnstr(self, y, x, text, n, attr=0):
        # built wide, it hands the console the characters as they are
        for i, ch in enumerate(text[:n]):
            if 0 <= y < self.h and 0 <= x + i < self.w:
                self.grid[y][x + i] = ch

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(FakeScr, "encoding", "cp850")
    monkeypatch.setattr(FakeScr, "get_wch", WideWindow.get_wch, raising=False)
    monkeypatch.setattr(FakeScr, "addnstr", addnstr)
    scr = tui(["q"], deal=1)
    assert scr.uis[0].symbols is True
    assert "┌" in scr.frames[0] and "♠" in scr.frames[0]


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


needs_sigcont = pytest.mark.skipif(not hasattr(signal, "SIGCONT"), reason="needs POSIX signals")


@needs_sigcont
def test_the_clock_leaves_out_the_time_stopped_with_ctrl_z(tui, game_clock):
    # ten seconds of play, then an hour stopped: ncurses stops the game on
    # Ctrl-Z, and all that is seen here is SIGCONT once it goes on
    scr = tui(["d", Later(10, -1), Later(3600, Signal("SIGCONT")), Later(1, -1)])
    assert times(scr) == ["0:00", "0:00", "0:10", "0:10", "0:11"]


@needs_sigcont
def test_ctrl_z_leaves_a_clock_not_yet_running_or_standing_still_alone(tui, game_clock):
    # an hour stopped before the first move, and another behind the help
    scr = tui(
        [Later(3600, Signal("SIGCONT")), "d", Later(10, "?"), Later(3600, Signal("SIGCONT")), "z"]
        + [Later(1, -1)]
    )
    assert times(scr) == ["0:00", "0:00", "0:00", "0:10", "0:11"]


@needs_sigcont
def test_the_handler_for_sigcont_goes_back_after(tui):
    def before(signum, frame):
        pass

    old = signal.signal(signal.SIGCONT, before)
    try:
        tui(["d", "q"])
        assert signal.getsignal(signal.SIGCONT) is before
    finally:
        signal.signal(signal.SIGCONT, old)


def test_the_clock_plays_on_where_there_is_no_sigcont(tui, game_clock, monkeypatch):
    # Windows
    monkeypatch.delattr(signal, "SIGCONT", raising=False)
    scr = tui(["d", Later(10, -1)])
    assert times(scr) == ["0:00", "0:00", "0:10"]


def test_leaving_out_a_stop_takes_off_no_more_than_the_clock_ran(game_clock):
    clock = soliterm.tui.app.GameClock()
    alive = game_clock.now
    game_clock.now += 2  # the move that starts the clock came after the last key
    clock.start()
    game_clock.now += 60
    clock.leave_out(alive)
    assert clock.elapsed() == 0
    game_clock.now += 5
    assert clock.elapsed() == 5


def test_the_clock_the_banner_and_the_statistics_agree_on_the_time(tui, game_clock):
    # moving a king to an empty column starts the clock; the win comes 10.6 s on
    keys = [ENTER] + [curses.KEY_RIGHT] * 4 + [ENTER, Later(10.6, -1), "a", "m"]
    scr = tui(keys, game=near_won())
    assert times(scr)[-1] == "0:11"
    assert any("Time        : 0:11" in frame for frame in scr.frames)
    assert store.get_stat("klondike")["best"] == 11


# -- the pause ---------------------------------------------------------------------


@pytest.mark.parametrize("key", ["p", "P"])
def test_p_pauses_the_game_with_the_clock_standing_still(tui, game_clock, key):
    # ten seconds of play, then twenty minutes paused, the page drawn again
    # after ten of them as it is each second
    scr = tui(["d", Later(10, key), Later(600, -1), Later(600, "z"), Later(1, -1)])
    assert times(scr) == ["0:00", "0:00", "0:10", "0:11"]
    for paused in scr.frames[2:4]:
        assert "Game paused" in paused and "Score" not in paused
        assert "Time played so far: 0:10" in paused
    assert "Press any key or click to go back to the game." in scr.frames[2]


def test_the_game_pauses_before_the_first_move_too(tui, game_clock):
    scr = tui([Later(30, "p"), Later(60, "z"), Later(5, "d"), Later(10, -1)])
    paused = scr.frames[1]
    assert "Game paused" in paused and "Time played so far: 0:00" in paused
    assert "The clock starts at the first move." in paused
    assert times(scr) == ["0:00", "0:00", "0:00", "0:10"]


def test_the_cards_picked_up_are_still_held_after_the_pause(tui):
    # as after the help
    scr = tui([ENTER, "p", "z"])
    assert "Game paused" in scr.frames[2]
    before, picked, after = scr.uis[0].selections
    assert before is None and picked is not None and after == picked


@pytest.mark.parametrize("click", [curses.BUTTON1_PRESSED, curses.BUTTON1_CLICKED])
def test_a_click_ends_the_pause_but_not_the_pointer_the_wheel_or_a_resize(tui, click):
    scr = tui(
        [
            "p",
            Mouse(9, 40, curses.REPORT_MOUSE_POSITION),
            Mouse(9, 40, curses.BUTTON4_PRESSED),
            Resize(30, 100),
            Mouse(9, 40, click),
            "z",
        ]
    )
    assert all("Game paused" in frame for frame in scr.frames[1:5])
    # drawn again to the new size
    assert len(scr.frames[4].split("\n")) == 30
    assert "Score" in scr.frames[5]
    # the click went back to the game and did nothing more
    assert "Moves 0" in scr.frames[5] and scr.uis[0].selections[-1] is None


@pytest.mark.parametrize(
    "leave",
    [
        pytest.param(
            Signal("SIGHUP"),
            marks=pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals"),
        ),
        KeyboardInterrupt,  # Ctrl-C, and Ctrl-Break on Windows
    ],
)
def test_a_game_saved_from_behind_the_pause_keeps_the_time_without_it(
    tui, game_clock, monkeypatch, leave
):
    monkeypatch.setattr(cli, "_quiet_output", lambda: None)
    with cli._leave_on_signals():
        scr = tui(["d", Later(10, "p"), Later(600, leave)])
    assert scr.rc == 130
    assert saves.waiting()["klondike"]["seconds"] == 10


# -- recording results -------------------------------------------------------------


def test_quitting_before_moving_records_nothing(tui):
    tui(["q"])
    assert store.get_stat("klondike")["total"] == 0
    assert saves.waiting() == {}


@pytest.mark.skipif(store.fcntl is None, reason="needs flock")
@pytest.mark.parametrize("leave", [["q"], ["m", "q"], [KeyboardInterrupt]])
def test_leaving_an_untouched_deal_does_not_wait_for_the_lock(tui, monkeypatch, leave):
    os.makedirs(store.data_dir(), exist_ok=True)
    waits = []
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:

        def another_copy_takes_it():
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_EX)

        def let_go(app):
            waits.append(store.LOCK_WAIT)
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)

        monkeypatch.setattr(soliterm.tui.app.App, "say_waiting", let_go)
        first, *rest = leave
        tui([Meanwhile(another_copy_takes_it, first), *rest])
    # there was nothing to keep or count, so nothing to wait for
    assert waits == []
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


def test_U_on_a_resumed_game_says_when_it_stops_short_of_the_deal(tui, monkeypatch):
    # a save keeps only the newest undo steps
    monkeypatch.setattr(saves, "SAVED_STEPS", 3)
    g = deal("klondike", 4)
    for _ in range(5):
        g.deal()
    assert saves.keep(g, 42)
    scr = tui(["U", "R", "U", "q"])
    undone = scr.frames[1]
    assert "Moves 2" in undone and soliterm.tui.app.UNDONE_ALL not in undone
    assert soliterm.tui.app.UNDONE_KEPT in undone
    assert "Moves 5" in scr.frames[2]
    # and after a move played since, with the steps it adds
    scr = tui(["d", "U"])
    assert soliterm.tui.app.UNDONE_KEPT in scr.frames[2]


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


@pytest.mark.parametrize("key", ["t", "v", "4", "x", "c"])
def test_a_change_of_look_still_offers_the_finish(tui, key):
    scr = tui(KING_TO_EMPTY + [key, key], game=queen_under_a_king())
    moved = len(KING_TO_EMPTY)
    for frame in scr.frames[moved + 1 : moved + 3]:
        assert "; a to finish" in frame


@pytest.mark.parametrize("skin", [False, True])
def test_the_longest_note_and_the_offer_fit_at_80_columns(tui, skin):
    if skin:
        code_skin_on()
    keys = KING_TO_EMPTY + ["4", "4"]
    scr = tui(keys, game=queen_under_a_king(), h=24, w=80, color=False)
    note = "four-colour deck off (colour is off, v turns it on); a to finish"
    assert note in scr.frames[len(keys)]


def test_a_change_of_look_offers_no_finish_there_is_not(tui):
    scr = tui(["t", "4"])
    assert not any("a to finish" in frame for frame in scr.frames)


def test_R_back_to_where_every_card_can_go_up_offers_the_finish(tui):
    scr = tui(KING_TO_EMPTY + ["U", "R"], game=queen_under_a_king())
    offer = soliterm.tui.app.FINISH_OFFER
    moved = len(KING_TO_EMPTY)
    assert offer not in scr.frames[moved + 1]
    assert offer in scr.frames[moved + 2]


def test_U_back_to_a_deal_where_every_card_can_go_up_offers_the_finish(tui):
    scr = tui(KING_TO_EMPTY + ["U"], game=near_won())
    assert soliterm.tui.app.FINISH_OFFER in scr.frames[len(KING_TO_EMPTY) + 1]


def test_a_game_resumed_where_every_card_can_go_up_offers_the_finish(tui):
    tui(KING_TO_EMPTY + ["q"], game=near_won())
    scr = tui(["a", "m"])
    assert soliterm.tui.app.FINISH_OFFER in scr.frames[0]
    assert "YOU WIN!" in scr.frames[1]


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


def test_a_finish_on_a_slow_terminal_lands_the_rest_once_time_is_up(animated, game_clock):
    # the waits add up to FINISH_S at most, but drawing each card takes time too
    late = Later(soliterm.tui.app.FINISH_S, -1)
    scr = animated(["a", -1, late, "z", "m"], game=near_won())
    assert scr.delays[:4] == [1000, 80, 80, cascade.FRAME_MS]
    assert store.get_stat("klondike")["wins"] == 1


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


def test_ctrl_c_as_the_last_card_lands_counts_the_win(animated):
    assert animated(["a", -1, -1, -1, KeyboardInterrupt], game=near_won()).rc == 130
    s = store.get_stat("klondike")
    assert (s["wins"], s["total"]) == (1, 1)
    assert [e["result"] for e in history.games()] == ["won"]
    assert saves.waiting() == {}


# -- the win's cascade ------------------------------------------------------------------

LANDINGS = ["a", -1, -1, -1, -1]  # near_won() finished, a card a frame


def test_any_key_skips_the_cascade(animated):
    # and goes no further: n would deal again from the banner
    scr = animated([*LANDINGS, -1, "n", "m"], game=near_won())
    assert all("Moves 1" in frame for frame in scr.frames[5:7])
    assert "Replay this deal" in scr.frames[7]
    assert "choose a game" in scr.frames[8]
    assert len(scr.uis) == 1


def test_a_scorpion_win_has_a_cascade_too(animated):
    g = deal("scorpion", 1)
    clear_board(g)
    columns = g.ids_of("tableau")
    for t, suit in zip(columns, "SHD"):
        g.slots[t].cards = [up(r, suit) for r in range(13, 0, -1)]
    g.slots[columns[3]].cards = [up(r, "C") for r in range(13, 1, -1)]
    g.slots[columns[4]].cards = [up(1, "C")]
    scr = animated([Click(columns[4], 0), Click(columns[3], 11), -1, "z", "m"], game=g)
    assert g.is_won()
    assert scr.delays[2:4] == [cascade.FRAME_MS] * 2
    assert "Replay this deal" in scr.frames[4]


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
def test_a_signal_as_q_saves_the_game_keeps_it_once(tui, monkeypatch, ctrl_c, name):
    monkeypatch.setattr(cli, "_quiet_output", lambda: None)
    signal_once_written(monkeypatch, saves.save_path("klondike"), getattr(signal, name))
    with cli._leave_on_signals():
        scr = tui(["d", "q"])
    assert scr.rc == 130
    assert saves.waiting()["klondike"]["moves"] == 1
    assert store.get_stat("klondike")["total"] == 0
    assert store.notices() == []


@pytest.mark.skipif(store.fcntl is None, reason="needs flock")
def test_q_while_another_copy_has_the_lock_says_why_it_waits(tui, monkeypatch):
    os.makedirs(store.data_dir(), exist_ok=True)
    seen = []
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:
        real = soliterm.tui.app.App.say_waiting

        def say_waiting(self):
            real(self)
            seen.append(self.stdscr.text())
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)  # it lets go

        monkeypatch.setattr(soliterm.tui.app.App, "say_waiting", say_waiting)
        lock = functools.partial(store.fcntl.flock, other.fileno(), store.fcntl.LOCK_EX)
        scr = tui(["d", Meanwhile(lock, "q")])
    assert scr.rc == 0
    assert len(seen) == 1
    assert seen[0].splitlines()[-1] == store.LOCK_WAIT
    assert saves.waiting()["klondike"]["moves"] == 1


@pytest.mark.skipif(store.fcntl is None, reason="needs flock")
@pytest.mark.parametrize("second", ["broken off", "let go"])
def test_ctrl_c_twice_as_q_waits_for_the_lock_says_what_was_lost(tui, monkeypatch, second):
    os.makedirs(store.data_dir(), exist_ok=True)
    waits = []
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:

        def say_waiting(self):
            waits.append(self.game.moves)
            if len(waits) == 1 or second == "broken off":
                raise KeyboardInterrupt  # Ctrl-C as it waits
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)  # it lets go

        monkeypatch.setattr(soliterm.tui.app.App, "say_waiting", say_waiting)
        lock = functools.partial(store.fcntl.flock, other.fileno(), store.fcntl.LOCK_EX)
        scr = tui(["d", Meanwhile(lock, "q")])
    assert scr.rc == 130
    assert waits == [1, 1]  # on q, then on the way out
    if second == "broken off":
        assert saves.waiting() == {}
        assert store.get_stat("klondike")["total"] == 0
        assert store.notices() == [
            "leaving was cut short, so your Klondike game was neither saved nor counted"
        ]
    else:
        assert saves.waiting()["klondike"]["moves"] == 1
        assert store.notices() == []


@pytest.mark.parametrize(
    "leave",
    [["q"], ["m", "q"], [KeyboardInterrupt], [Signal("SIGTERM")]],
    ids=["q", "m then q", "ctrl-c", "sigterm"],
)
def test_leaving_says_where_the_kept_game_went(tui, capsys, leave):
    if isinstance(leave[0], Signal) and not hasattr(signal, "SIGHUP"):
        pytest.skip("needs POSIX signals")
    with cli._leave_on_signals():
        scr = tui(["d", *leave], via_main=True)
    assert scr.rc == (0 if leave[0] in ("q", "m") else 130)
    assert saves.waiting("klondike")["klondike"]["moves"] == 1
    # once the screen is back, as the notices are told
    assert capsys.readouterr().err == (
        "soliterm: saved your Klondike game; run soliterm to pick it up\n"
    )


def test_two_kept_games_are_told_of_in_one_line(tui, capsys):
    tui(["d", "m", "j", ENTER, "d", "q"], via_main=True)
    assert set(saves.waiting()) == {"klondike", "spider"}
    assert capsys.readouterr().err == (
        "soliterm: saved your Klondike and Spider games; run soliterm to pick them up\n"
    )


def test_leaving_says_nothing_of_a_game_not_kept(tui, capsys, monkeypatch):
    tui(["q"], via_main=True)  # untouched
    # kept, then taken up again and won
    tui(["f", "m", ENTER, "a", "m", "q"], game=stalled_klondike(), via_main=True)
    assert store.get_stat("klondike")["wins"] == 1
    # a chosen deal, with a game of its kind already waiting
    assert saves.keep(deal("klondike", 7), 42)
    monkeypatch.setattr(saves, "_kept", [])  # as an earlier run left it
    tui(["d", "q"], deal=3, via_main=True)
    assert store.get_stat("klondike")["total"] == 2
    assert capsys.readouterr().err == ""


@pytest.mark.skipif(
    store.fcntl is None or not hasattr(signal, "SIGHUP"), reason="needs flock and POSIX signals"
)
@pytest.mark.parametrize("first, second", [("SIGTERM", "SIGTERM"), ("SIGHUP", "SIGTERM")])
def test_a_second_signal_as_it_waits_for_the_lock_says_what_was_lost(
    tui, monkeypatch, first, second
):
    monkeypatch.setattr(cli, "_quiet_output", lambda: None)
    os.makedirs(store.data_dir(), exist_ok=True)
    main_thread = threading.get_ident()
    killers = []
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:

        def say_waiting(self):
            killers.append(signal_as_it_waits(main_thread, getattr(signal, second), other))
            killers[-1].start()

        monkeypatch.setattr(soliterm.tui.app.App, "say_waiting", say_waiting)
        # another copy of the game takes the lock, and is stopped with it
        lock = functools.partial(store.fcntl.flock, other.fileno(), store.fcntl.LOCK_EX)
        with cli._leave_on_signals():
            scr = tui(["d", Meanwhile(lock, Signal(first))])
        for killer in killers:
            killer.join()
    assert scr.rc == 130
    assert [killer.seen for killer in killers] == [[True, True]]
    assert saves.waiting() == {}
    assert store.get_stat("klondike")["total"] == 0
    assert store.notices() == [
        "leaving was cut short, so your Klondike game was neither saved nor counted"
    ]


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


def test_the_banner_rounds_a_half_percent_up_as_aisleriot_does(tui):
    store.save_stats({"golf": {"wins": 1, "total": 7, "best": 50, "worst": 50}})
    scr = tui(["f", "m"], start_key="golf", game=one_move_left())
    assert "Wins/Total  : 1/8  (13%)" in scr.frames[1]


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


def test_a_played_card_moves_the_cursor_to_the_card_it_uncovered(tui):
    # the game starts on the 6H at the bottom left; once it's played, the
    # 7S it was covering turns up and the next f plays that
    g = deal("triplepeaks", 1)
    clear_board(g)
    peaks = g.ids_of("tableau")
    g.slots[g.ids_of("waste")[0]].cards = [up(5, "C")]
    g.slots[peaks[9]].cards = [Card(7, "S", False)]
    g.slots[peaks[18]].cards = [up(6, "H")]
    g.slots[peaks[27]].cards = [up(13, "D")]
    tui(["f", "f", "m", "q"], start_key="triplepeaks", game=g, h=24, w=80)
    assert [str(c) for c in g.cards(g.ids_of("waste")[0])] == ["5C", "6H", "7S"]
    assert not g.cards(peaks[9]) and not g.cards(peaks[18])


def test_a_played_card_moves_the_cursor_to_the_nearest_card_that_plays(tui):
    # once the 6H goes, the face-down 7S and the QD beside it are nearer,
    # but only the 7S across the board will play
    g = deal("triplepeaks", 1)
    clear_board(g)
    peaks = g.ids_of("tableau")
    g.slots[g.ids_of("waste")[0]].cards = [up(5, "C")]
    g.slots[peaks[9]].cards = [Card(7, "S", False)]
    g.slots[peaks[18]].cards = [up(6, "H")]
    g.slots[peaks[19]].cards = [up(12, "D")]
    g.slots[peaks[27]].cards = [up(7, "C")]
    tui(["f", "f", "m", "q"], start_key="triplepeaks", game=g, h=24, w=80)
    assert [str(c) for c in g.cards(g.ids_of("waste")[0])] == ["5C", "6H", "7C"]


def test_with_nothing_to_play_the_cursor_goes_to_a_face_up_card(tui):
    # once the 6H goes, only the stock plays; the face-down 7S above it is
    # nearer, but the QD beside it is a card to pick up
    g = deal("triplepeaks", 1)
    clear_board(g)
    peaks = g.ids_of("tableau")
    g.slots[g.ids_of("stock")[0]].cards = [Card(9, "S", False)]
    g.slots[g.ids_of("waste")[0]].cards = [up(5, "C")]
    g.slots[peaks[9]].cards = [Card(7, "S", False)]
    g.slots[peaks[18]].cards = [up(6, "H")]
    g.slots[peaks[19]].cards = [up(12, "D")]
    g.slots[peaks[27]].cards = [up(2, "C")]
    scr = tui(["f", "\n", "m", "q"], start_key="triplepeaks", game=g, h=24, w=80)
    assert peaks[19] in scr.uis[-1].selections


def one_to_play(key):
    """Golf or Triple Peaks with a 6H to play on the 5C where the cursor
    starts, at the bottom left, and a king left so the game goes on."""
    g = deal(key, 1)
    clear_board(g)
    tableau, waste = g.ids_of("tableau"), g.ids_of("waste")[0]
    card = tableau[18 if key == "triplepeaks" else 0]
    g.slots[waste].cards = [up(5, "C")]
    g.slots[card].cards = [up(6, "H")]
    g.slots[tableau[-1]].cards = [up(13, "S")]
    return g, card, waste


@pytest.mark.parametrize("how", ["enter", "click"])
@pytest.mark.parametrize("key", ["golf", "triplepeaks"])
def test_enter_or_a_click_plays_a_card_that_goes_on_the_waste(tui, key, how):
    # as a click does in AisleRiot
    g, card, waste = one_to_play(key)
    tui([ENTER if how == "enter" else Click(card, 0)], start_key=key, game=g)
    assert names(g, waste) == ["5C", "6H"]
    assert g.moves == 1 and g.score > 0


def test_a_double_click_plays_one_card_as_a_click_does(tui):
    # the first click plays the 6H; the second, where it was, lands on the
    # 7S under it, which goes on the 6H but was never clicked on its own
    g, card, waste = one_to_play("golf")
    g.slots[card].cards.insert(0, up(7, "S"))
    press, release = curses.BUTTON1_PRESSED, curses.BUTTON1_RELEASED
    tui([Click(card, 1, press), Again(release), Again(press)], start_key="golf", game=g)
    assert names(g, waste) == ["5C", "6H"]
    assert names(g, card) == ["7S"]


def test_quick_clicks_on_two_cards_play_both(tui):
    g, card, waste = one_to_play("golf")
    other = g.ids_of("tableau")[1]
    g.slots[other].cards = [up(7, "S")]
    press = curses.BUTTON1_PRESSED
    tui([Click(card, 0, press), Click(other, 0, press)], start_key="golf", game=g)
    assert names(g, waste) == ["5C", "6H", "7S"]


@pytest.mark.parametrize("how", ["enter", "click"])
@pytest.mark.parametrize("key", ["golf", "triplepeaks"])
def test_enter_or_a_click_picks_up_a_card_that_does_not_go(tui, key, how):
    g, card, waste = one_to_play(key)
    g.slots[waste].cards = [up(9, "C")]
    scr = tui([ENTER if how == "enter" else Click(card, 0)], start_key=key, game=g)
    assert names(g, waste) == ["9C"]
    assert scr.uis[-1].selections[-1] == card


@pytest.mark.parametrize("double", [False, True])
@pytest.mark.parametrize(
    "key, says",
    [
        ("klondike", "no foundation move for that card"),
        # these three have no foundations; f plays on the waste in two
        ("golf", "5♥ doesn't go on the waste"),
        ("triplepeaks", "5♥ doesn't go on the waste"),
        ("scorpion", "Scorpion has no foundations"),
        # its discard takes a King alone, and a pair together
        ("pyramid", "5♥ only goes in a pair making 13"),
    ],
)
def test_an_f_that_does_nothing_says_why(tui, key, says, double):
    g = deal(key, 1)
    clear_board(g)
    first = g.ids_of("tableau")[-1 if key in ("triplepeaks", "pyramid") else 0]  # a bottom card
    g.slots[first].cards = [up(5, "H")]
    for waste in g.ids_of("waste"):
        g.slots[waste].cards = [up(9, "S")]
    before = g.serialize()
    key_in = Click(first, 0, curses.BUTTON1_DOUBLE_CLICKED) if double else "f"
    scr = tui([key_in], start_key=key, game=g)
    assert says in scr.frames[1]
    assert g.serialize() == before


@pytest.mark.parametrize("key", ["golf", "triplepeaks"])
def test_f_plays_a_card_that_goes_on_the_waste(tui, key):
    g, _card, waste = one_to_play(key)
    scr = tui(["f"], start_key=key, game=g)
    assert names(g, waste) == ["5C", "6H"]
    assert "on the waste" not in scr.frames[1]


@pytest.mark.parametrize("symbols, heart", [(True, "♥"), (False, "H")])
@pytest.mark.parametrize("key", ["golf", "triplepeaks"])
def test_f_names_the_card_that_does_not_go_on_the_waste(tui, key, symbols, heart):
    # as text mode's f does, and as the board draws it
    g, _card, waste = one_to_play(key)
    g.slots[waste].cards = [up(9, "C")]
    scr = tui(["f"], start_key=key, game=g, symbols=symbols)
    assert f"6{heart} doesn't go on the waste" in scr.frames[1]
    assert names(g, waste) == ["9C"]


def test_f_on_a_face_down_card_does_not_give_it_away(tui):
    g, _card, _waste = one_to_play("triplepeaks")
    peak = g.ids_of("tableau")[9]  # under the 6H
    g.slots[peak].cards = [Card(7, "S", False)]
    scr = tui([Click(peak, 0, curses.BUTTON1_DOUBLE_CLICKED)], start_key="triplepeaks", game=g)
    assert "that face-down card doesn't go on the waste" in scr.frames[1]
    assert "7♠" not in scr.frames[1]


# an empty peak is off the board, so Triple Peaks has only its waste
@pytest.mark.parametrize(
    "key, on", [("golf", "empty"), ("golf", "waste"), ("triplepeaks", "waste")]
)
def test_an_f_with_no_card_to_play_names_none(tui, key, on):
    g = deal(key, 1)
    clear_board(g)
    tableau, waste = g.ids_of("tableau"), g.ids_of("waste")[0]
    g.slots[waste].cards = [up(9, "S")]
    g.slots[tableau[-1]].cards = [up(5, "H")]  # a card left to play, so not won
    before = g.serialize()
    target = tableau[0] if on == "empty" else waste
    scr = tui([Click(target, 0, curses.BUTTON1_DOUBLE_CLICKED)], start_key=key, game=g)
    assert "nothing there goes on the waste" in scr.frames[1]
    assert g.serialize() == before


@pytest.mark.parametrize("how", ["d", "click"])
def test_a_card_dealt_from_the_stock_clears_the_last_message(tui, how):
    g = deal("triplepeaks", 1)
    clear_board(g)
    first = g.ids_of("tableau")[-1]
    g.slots[first].cards = [up(5, "H")]
    stock, waste = g.ids_of("stock")[0], g.ids_of("waste")[0]
    g.slots[waste].cards = [up(9, "S")]
    g.slots[stock].cards = [Card(2, "C", False), Card(3, "D", False)]
    dealt = "d" if how == "d" else Click(stock, 1)
    scr = tui(["f", dealt], start_key="triplepeaks", game=g)
    assert "doesn't go on the waste" in scr.frames[1]
    assert names(g, waste)[-1] == "3D"
    assert "doesn't go on the waste" not in scr.frames[2]


def pyramid(cards, waste=(), stock=((9, "D"),)):
    """Pyramid with just the pyramid cards given as {index: card}, and a
    card left on the stock so the game goes on."""
    g = deal("pyramid", 1)
    clear_board(g)
    tableau = g.ids_of("tableau")
    for i, card in cards.items():
        g.slots[tableau[i]].cards = [card]
    g.slots[g.ids_of("waste")[0]].cards = list(waste)
    g.slots[g.ids_of("stock")[0]].cards = [Card(r, s, False) for r, s in stock]
    return g, tableau, g.ids_of("foundation")[0]


@pytest.mark.parametrize("how", ["keys", "clicks"])
def test_a_card_dropped_on_its_partner_takes_both_off(tui, how):
    # the cursor starts on the 8H, the first card that's face up
    g, tableau, discard = pyramid({26: up(8, "H"), 27: up(5, "C")})
    if how == "keys":
        keys = [ENTER, curses.KEY_RIGHT, ENTER]
    else:
        keys = [Click(tableau[26], 0), Click(tableau[27], 0)]
    scr = tui(keys, start_key="pyramid", game=g, h=24, w=80)
    assert names(g, discard) == ["5C", "8H"]  # the one dropped on top
    assert not g.cards(tableau[26]) and not g.cards(tableau[27])
    assert (g.moves, g.score) == (1, 2)
    assert not {tableau[26], tableau[27]} & {sid for sid, _ in scr.uis[-1].hit.values()}


@pytest.mark.parametrize("how", ["f", "double-click", "drop"])
def test_a_king_is_taken_off_alone(tui, how):
    g, tableau, discard = pyramid({26: up(13, "S"), 27: up(5, "C")})
    king = tableau[26]
    keys = {
        "f": ["f"],
        "double-click": [Click(king, 0, curses.BUTTON1_DOUBLE_CLICKED)],
        "drop": [Click(king, 0), Click(discard, 0)],
    }[how]
    tui(keys, start_key="pyramid", game=g, h=24, w=80)
    assert names(g, discard) == ["KS"]
    assert not g.cards(king)
    assert (g.moves, g.score) == (1, 1)


@pytest.mark.parametrize("how", ["d", "click"])
def test_the_stock_turns_a_card_onto_the_waste(tui, how):
    g, _tableau, _discard = pyramid({27: up(5, "C")}, stock=((2, "C"), (9, "D")))
    stock, waste = g.ids_of("stock")[0], g.ids_of("waste")[0]
    tui(["d" if how == "d" else Click(stock, 1)], start_key="pyramid", game=g, h=24, w=80)
    assert names(g, waste) == ["9D"]
    assert names(g, stock) == ["2C"]


def test_an_emptied_stock_and_waste_are_still_there_to_click(tui):
    # the 9S and 4H are left to pair, so the game goes on
    cards = {1: up(9, "S"), 25: up(4, "H"), 27: up(5, "C")}
    g, tableau, _discard = pyramid(cards, waste=[up(8, "H")], stock=())
    stock, waste = g.ids_of("stock")[0], g.ids_of("waste")[0]
    keys = [Click(tableau[27], 0), Click(waste, 0), Click(stock, 0), Click(waste, 0)]
    scr = tui(keys, start_key="pyramid", game=g)
    assert not g.cards(waste) and not g.cards(tableau[27])
    assert "the stock is empty" in scr.frames[3]
    assert "nothing to pick up there" in scr.frames[4]


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


# the banner's choices sit on rows 15-17 from column 6, marker included
BANNER_ROW = {"same": 15, "new": 16, "menu": 17}


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
    assert won[2:16] == [
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
        "",  # nothing on the deal or a streak on a first win
        "",
        "",
        "      > Replay this deal (s)",
    ]
    # with no best time, deal or streak to show their rows stay empty, so
    # the choices don't move up
    stuck = tui(["f", "m"], start_key="golf", game=one_move_left()).frames[1].split("\n")
    assert stuck[10:16] == [
        "      Wins/Total  : 0/1  (0%)",
        "",
        "",
        "",
        "",
        "      > Undo move (u)",
    ]


def test_the_banner_shows_the_deal_and_share_code(tui):
    banner = tui(["a", "m"], game=near_won(48213, draw=3)).frames[1]
    assert "      Deal        : 48213   share code klondike:d3:48213\n" in banner


def test_the_banner_says_a_daily_is_one(tui):
    daily = deals.daily("klondike", DAY)
    banner = tui(["a", "m"], start=daily, game=near_won(daily.number)).frames[1]
    assert "      Deal        : daily 2026-09-24   share code klondike:20260924\n" in banner


def test_the_banner_prints_the_share_line_for_a_daily(tui):
    daily = deals.daily("klondike", DAY)
    rows = tui(["a", "m"], start=daily, game=near_won(daily.number)).frames[1].split("\n")
    footer = BANNER_ROW["menu"] + 2
    assert rows[footer].startswith("      Up/Down + Enter")
    assert rows[footer + 1 : footer + 4] == [
        "",
        "      Soliterm daily 2026-09-24, Klondike: won in 0:00, 1 move",
        "",
    ]
    # and under the Undo move choice when no moves are left
    golf = deals.daily("golf", DAY)
    rows = tui(["f", "m"], start=golf, game=one_move_left()).frames[1].split("\n")
    assert rows[footer + 3] == "      Soliterm daily 2026-09-24, Golf: stuck after 0:00, 1 move"
    # a deal that isn't a daily has no line to share
    assert "Soliterm daily" not in tui(["a", "m"], game=near_won()).frames[1]


@pytest.mark.parametrize("won", [True, False])
def test_the_share_line_is_left_off_a_banner_it_would_not_fit_on(tui, won):
    # the banner fits 21 rows, or 22 with Undo move, without the line
    daily = deals.daily("klondike" if won else "golf", DAY)
    keys, rows = (["a", "m"], 21) if won else (["f", "m"], 22)
    for h, shared in [(rows, False), (rows + 1, True)]:
        game = near_won(daily.number) if won else one_move_left()
        banner = tui(keys, start=daily, game=game, h=h, w=80).frames[1]
        assert "Terminal too small" not in banner
        assert ("Soliterm daily" in banner) is shared


@pytest.mark.parametrize("skin", [False, True])
def test_every_banner_choice_shows_its_key_at_80x24(tui, skin):
    if skin:
        code_skin_on()
    # the most a banner holds: a line on the deal, four choices and a
    # daily's share line
    history.record(deal("golf", 1), True, 5999)
    golf = deals.daily("golf", DAY)
    banner = tui(["f", "m"], start=golf, game=one_move_left(), h=24, w=80).frames[1]
    assert "Terminal too small" not in banner
    assert "On this deal: your best is 99:59, 0 moves" in banner
    for choice in ["Undo move (u)", "Replay this deal (s)", "New deal (n)", "Back to menu (m)"]:
        assert choice in banner
    assert "Up/Down + Enter, or click to choose; y copies the share line." in banner
    assert "Soliterm daily 2026-09-24, Golf" in banner


@pytest.mark.parametrize("skin", [False, True])
def test_the_longest_share_line_fits_80_columns(tui, monkeypatch, skin):
    if skin:
        code_skin_on()
    longest = deals.share_line("Forty Thieves", "2026-09-24", False, 59 * 60 + 59, 1000)
    monkeypatch.setattr(deals, "share_line", lambda *args: longest)
    daily = deals.daily("klondike", DAY)
    banner = tui(["a", "m"], start=daily, game=near_won(daily.number), h=24, w=80).frames[1]
    assert "Terminal too small" not in banner
    (row,) = [row for row in banner.split("\n") if "Soliterm daily" in row]
    # all of it, at the banner's margin, or nearer the edge under the skin
    assert row.endswith(longest)
    assert row.index(longest) == (CODE_GUTTER + 2 if skin else 6)


# -- y: copying what there is to share ------------------------------------------------


@pytest.fixture
def sent(monkeypatch):
    """Copying as it goes off Windows, outside tmux and screen, with a pipe
    standing in for the terminal. Call it for what the game sent there."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    read, write = os.pipe()
    monkeypatch.setattr(clipboard, "TERMINAL", write)
    still_open = [read, write]

    def written():
        os.close(write)
        still_open.remove(write)
        return os.read(read, 4096)

    yield written
    for fd in still_open:
        os.close(fd)


def changed_rows(before, after):
    """The rows of frame `after` that aren't as they were in `before`."""
    pairs = zip(before.split("\n"), after.split("\n"))
    return [row for row, (was, now) in enumerate(pairs) if was != now]


@pytest.mark.parametrize("key", ["y", "Y"])
def test_y_on_the_board_sends_its_share_code_to_the_terminal_to_copy(tui, sent, key):
    scr = tui([key, "q"], game=deal("klondike", 48213, draw=3))
    assert sent() == b"\x1b]52;c;a2xvbmRpa2U6ZDM6NDgyMTM=\x07"
    # the code it sent is on the message line, and the rest is as it was
    (row,) = changed_rows(*scr.frames[:2])
    said = scr.frames[1].split("\n")[row]
    assert "sent klondike:d3:48213 to the terminal to copy, if it can" in said


@pytest.mark.parametrize(
    "env, wrapped, said",
    [
        ("TMUX", False, "sent klondike:1 to tmux to copy, if set-clipboard is on"),
        ("STY", True, "sent klondike:1 to the terminal to copy, if it can"),
    ],
)
def test_y_under_tmux_or_screen_goes_the_way_each_passes_it_on(
    tui, sent, monkeypatch, env, wrapped, said
):
    monkeypatch.setenv(env, "set by tmux or screen")
    scr = tui(["y", "q"], deal=1)
    osc52 = b"\x1b]52;c;" + base64.b64encode(b"klondike:1") + b"\x07"
    assert sent() == (b"\x1bP" + osc52 + b"\x1b\\" if wrapped else osc52)
    assert said in scr.frames[1]


def test_y_is_not_a_move(tui, sent, game_clock):
    scr = tui(["y", Later(5, -1), "q"], deal=1)
    assert "Moves 0 " in scr.frames[2]
    assert times(scr) == ["0:00"] * 3  # the clock waits for the first move
    assert saves.waiting() == {}


@pytest.fixture
def on_windows(monkeypatch, sent):
    """Copying as it goes on Windows, onto a FakeWin32 it hands back. Call
    it with FakeWin32's arguments."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(clipboard.time, "sleep", lambda s: None)

    def make(**kw):
        fake = FakeWin32(**kw)
        monkeypatch.setattr(clipboard, "win32", fake)
        return fake

    return make


def test_y_on_windows_puts_the_share_code_on_the_clipboard(tui, on_windows, sent):
    fake = on_windows()
    scr = tui(["y", "q"], game=deal("klondike", 48213, draw=3))
    assert fake.pasted == "klondike:d3:48213\0"
    assert "copied klondike:d3:48213 to the clipboard" in scr.frames[1]
    assert sent() == b""  # and nothing for the terminal


def test_y_on_windows_says_when_the_clipboard_is_in_use(tui, on_windows):
    on_windows(busy=100)
    scr = tui(["y", "q"], deal=1)
    assert "couldn't copy klondike:1: the clipboard is in use" in scr.frames[1]


def rows_of(scr, i):
    return scr.frames[i].split("\n")


@pytest.mark.parametrize("won", [True, False], ids=["won", "stuck"])
@pytest.mark.parametrize("daily", [True, False], ids=["daily", "deal"])
def test_y_on_the_banner_copies_the_share_line_or_code(tui, sent, won, daily):
    key, keys = ("klondike", ["a", "y", -1, "m"]) if won else ("golf", ["f", "y", -1, "m"])
    start = deals.daily(key, DAY) if daily else None
    if won:
        game = near_won(start.number) if daily else near_won(48213, draw=3)
    else:
        game = one_move_left()
    scr = tui(keys, start_key=key, start=start, game=game)
    banner = rows_of(scr, 1)
    footer = BANNER_ROW["menu"] + (2 if won else 3)
    if daily:
        what, below = "the share line", footer + 3
        text = banner[footer + 2].strip()
        assert text.startswith("Soliterm daily 2026-09-24")
    else:
        what, below = "the share code", footer + 2
        text = deals.code_of(game)
        assert f"share code {text}\n" in scr.frames[1]
    assert banner[footer] == f"      Up/Down + Enter, or click to choose; y copies {what}."
    assert banner[below] == ""
    assert sent() == clipboard.osc52(text, {})
    # what came of it goes under the rest, and stays
    for i in (2, 3):
        assert changed_rows(scr.frames[1], scr.frames[i]) == [below]
        assert rows_of(scr, i)[below] == f"      sent {what} to the terminal to copy, if it can"
    assert "choose a game" in scr.frames[4]


def test_y_on_a_daily_banner_on_windows_copies_the_share_line(tui, on_windows):
    fake = on_windows()
    daily = deals.daily("klondike", DAY)
    rows = rows_of(tui(["a", "y", "m"], start=daily, game=near_won(daily.number)), 2)
    line = "Soliterm daily 2026-09-24, Klondike: won in 0:00, 1 move"
    assert fake.pasted == line + "\0"
    footer = BANNER_ROW["menu"] + 2
    assert rows[footer + 2 : footer + 4] == [
        f"      {line}",
        "      copied the share line to the clipboard",
    ]


@pytest.mark.parametrize("won", [True, False], ids=["won", "stuck"])
def test_a_daily_banner_too_short_for_the_share_line_copies_the_code(tui, sent, won):
    # the banner fits 21 rows, or 22 with Undo move, with no share line and
    # no row under it, so what came of y goes in place of the footer
    daily = deals.daily("klondike" if won else "golf", DAY)
    keys, h = (["a", "y", "m"], 21) if won else (["f", "y", "m"], 22)
    game = near_won(daily.number) if won else one_move_left()
    scr = tui(keys, start=daily, game=game, h=h, w=80)
    code, footer = deals.code_of(game), h - 2
    assert "Soliterm daily" not in scr.frames[1]
    assert f"share code {code}\n" in scr.frames[1]
    assert rows_of(scr, 1)[footer] == (
        "      Up/Down + Enter, or click to choose; y copies the share code."
    )
    assert sent() == clipboard.osc52(code, {})
    assert "Terminal too small" not in scr.frames[2]
    assert rows_of(scr, 2)[footer] == "      sent the share code to the terminal to copy, if it can"


@pytest.mark.parametrize("skin", [False, True])
def test_the_most_a_banner_holds_and_what_y_did_fit_80x24(tui, sent, monkeypatch, skin):
    if skin:
        code_skin_on()
    # four choices, the best on this deal, the daily's share line and the
    # longest thing y says there
    monkeypatch.setenv("TMUX", "set by tmux")
    won = deal("golf", 1)
    won.moves = 40
    history.record(won, True, 60)
    golf = deals.daily("golf", DAY)
    banner = tui(["f", "y", "m"], start=golf, game=one_move_left(), h=24, w=80).frames[2]
    sent()
    assert "Terminal too small" not in banner
    assert "On this deal: your best is 1:00, 40 moves" in banner
    for choice in ["Undo move (u)", "Replay this deal (s)", "New deal (n)", "Back to menu (m)"]:
        assert choice in banner
    rows = banner.split("\n")
    at = (CODE_GUTTER if skin else 0) + 6
    footer = BANNER_ROW["menu"] + 3
    assert [rows[footer][at:], rows[footer + 2][at:], rows[footer + 3][at:]] == [
        "Up/Down + Enter, or click to choose; y copies the share line.",
        "Soliterm daily 2026-09-24, Golf: stuck after 0:00, 1 move",
        "sent the share line to tmux to copy, if set-clipboard is on",
    ]


def test_what_y_did_stays_through_the_boss_key_and_a_resize(tui, sent):
    daily = deals.daily("klondike", DAY)
    keys = ["a", "y", "b", "z", Resize(20, 80), Resize(40, 120), "m"]
    scr = tui(keys, start=daily, game=near_won(daily.number))
    sent()
    said = "      sent the share line to the terminal to copy, if it can"
    footer = BANNER_ROW["menu"] + 2
    assert rows_of(scr, 2)[footer + 3] == said
    assert "YOU WIN" not in scr.frames[3]  # the boss screen
    assert rows_of(scr, 4)[footer + 3] == said
    # too short for the share line and a row under it, the share code is
    # what y would copy now, and what it did copy takes the footer's place
    assert "Terminal too small" not in scr.frames[5]
    assert rows_of(scr, 5)[footer] == said
    assert rows_of(scr, 6)[footer + 3] == said


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
    assert banner[15] == "      > Replay this deal (s)"


def test_the_no_moves_banner_shows_no_streak(tui):
    played_before("golf", [True, True, True])
    stuck = tui(["f", "m"], start_key="golf", game=one_move_left()).frames[1]
    assert "Streak" not in stuck


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


def test_no_new_best_when_the_best_comes_from_the_games_shared_at_last(tui, game_clock, keyfile):
    # 0:05 from before sharing, which the first shared win folds in
    store.record_result("klondike", won=True, seconds=5)
    keyfile("[klondike.scm]\nStatistic=3;5;300;400;\n")
    banner = banner_after_a_win_in_11_seconds(tui)
    assert "Best time   : 0:05\n" in banner


@pytest.mark.parametrize("best", [11, 5], ids=["equal", "slower"])
def test_a_win_equal_to_the_best_gets_no_note(tui, game_clock, best):
    store.record_result("klondike", won=True, seconds=best)
    banner = banner_after_a_win_in_11_seconds(tui)
    assert f"Best time   : {store.fmt_time(best)}\n" in banner


def won_before(seconds, moves, number=1, key="klondike", **options):
    """A win of deal `number` of `key` in the history, in seconds and moves."""
    g = deal(key, number, **options)
    g.moves = moves
    history.record(g, True, seconds)


def deal_row(banner):
    """The banner's line about the deal, or None."""
    rows = [row.strip() for row in banner.split("\n") if "On this deal" in row]
    assert len(rows) <= 1
    return rows[0] if rows else None


@pytest.mark.parametrize(
    "before, row",
    [
        ([], None),
        ([(300, 150)], "On this deal: a new best, was 5:00, 150 moves"),
        ([(300, 150), (5, 30), (40, 3)], "On this deal: your best is 0:05, 30 moves"),
        # the same time, and the moves decide
        ([(11, 40)], "On this deal: a new best, was 0:11, 40 moves"),
        ([(11, 1)], "On this deal: your best is 0:11, 1 move"),
        ([(11, 2)], "On this deal: your best is 0:11, 2 moves"),
    ],
    ids=["first", "faster", "slower", "fewer-moves", "more-moves", "the-same"],
)
def test_the_banner_says_how_a_win_stood_on_its_deal(tui, game_clock, before, row):
    won_before(1, 10, number=2)  # the game's best, on another deal
    for seconds, moves in before:
        won_before(seconds, moves)
    history.record(deal("klondike", 3), False, 60)  # and no streak
    banner = banner_after_a_win_in_11_seconds(tui)
    assert "Moves       : 2\n" in banner
    assert deal_row(banner) == row
    lines = banner.split("\n")
    assert lines[11].strip() == "Best time   : 0:01"
    assert lines[12].strip() == (row or "")  # under the best time
    assert lines[15] == "      > Replay this deal (s)"


def test_a_win_on_other_options_is_another_deal(tui, game_clock):
    won_before(300, 150, draw=3)
    won_before(300, 150, number=2)
    assert deal_row(banner_after_a_win_in_11_seconds(tui)) is None


@pytest.mark.parametrize(
    "elsewhere, was, row",
    [
        (None, "5:00", None),
        # when the game's best was on another deal, both are news
        (120, "2:00", "On this deal: a new best, was 5:00, 150 moves"),
    ],
    ids=["the-deal-had-the-games-best", "another-deal-had-it"],
)
def test_a_new_best_on_the_deal_is_said_once(tui, game_clock, elsewhere, was, row):
    won_before(300, 150)
    if elsewhere:
        won_before(elsewhere, 60, number=2)
    banner = banner_after_a_win_in_11_seconds(tui)
    assert f"Best time   : 0:11  (new best, was {was})\n" in banner
    assert deal_row(banner) == row


def test_the_deal_line_goes_over_the_streak(tui, game_clock):
    won_before(1, 10, number=2)
    won_before(300, 150)
    lines = banner_after_a_win_in_11_seconds(tui).split("\n")
    assert [line.strip() for line in lines[10:16]] == [
        "Wins/Total  : 3/3  (100%)",
        "Best time   : 0:01",
        "On this deal: a new best, was 5:00, 150 moves",
        "Streak      : 3 wins in a row, your longest yet",
        "",
        "> Replay this deal (s)",
    ]


@pytest.mark.parametrize(
    "before, row",
    [
        ([], None),
        ([False], None),
        ([True, False], "On this deal: your best is 1:00, 0 moves"),
    ],
    ids=["first", "after-a-loss", "after-a-win"],
)
def test_the_no_moves_banner_gives_the_best_win_on_its_deal(tui, before, row):
    played_before("golf", before)
    won_before(1, 10, number=2, key="golf")  # not this deal
    stuck = tui(["f", "m"], start_key="golf", game=one_move_left()).frames[1]
    assert "No moves left" in stuck
    assert deal_row(stuck) == row
    if row:
        assert stuck.split("\n")[12] == f"      {row}"


def test_a_daily_stands_on_the_same_deal_played_plainly(tui, game_clock):
    won_before(1, 10, number=2)
    won_before(300, 150, number=20260924)
    daily = deals.daily("klondike", DAY)
    scr = tui(KING_TO_EMPTY + [Later(10.6, -1), "a", "m"], start=daily, game=near_won(20260924))
    banner = next(frame for frame in scr.frames if "YOU WIN" in frame)
    assert "Deal        : daily 2026-09-24" in banner
    assert deal_row(banner) == "On this deal: a new best, was 5:00, 150 moves"
    # and the plain deal after it has the daily to beat
    banner = tui(["a", "m"], game=near_won(20260924)).frames[1]
    assert deal_row(banner) == "On this deal: a new best, was 0:11, 2 moves"


def test_the_banner_choices_follow_its_lines(tui, monkeypatch):
    lines = [f"Line {i}" for i in range(9)]  # rows 4 to 12
    monkeypatch.setattr(soliterm.tui.app.App, "banner_lines", lambda self, *args: lines)
    scr = tui(["a", Mouse(14, 8)], game=near_won())
    banner = scr.frames[1].split("\n")
    assert banner[12:19] == [
        "      Line 8",
        "",
        "      > Replay this deal (s)",
        "        New deal (n)",
        "        Back to menu (m)",
        "",
        "      Up/Down + Enter, or click to choose; y copies the share code.",
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
    assert f"  Spider           {engine.GAMES['spider'].short_blurb}" in menu


def test_enter_on_it_resumes_with_the_clock_at_0_42(tui, game_clock):
    keep_one()
    scr = tui([ENTER, Later(10, -1), "n", "q"], start_key=None)
    assert "Resumed your game (0:42, 31 moves). n deals a new hand." in scr.frames[1]
    assert "Moves 31   Stock: 23  Waste: 1" in scr.frames[1]
    assert times(scr) == ["0:42", "0:52", "0:00"]
    assert saves.waiting() == {}


def signal_once_taken(monkeypatch, signum):
    """Send signum to this process the moment a save has been taken out of
    the saves folder, before the game it holds is set up."""
    real = saves.take

    def take(key):
        taken = real(key)
        os.kill(os.getpid(), signum)
        return taken

    monkeypatch.setattr(saves, "take", take)


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")
@pytest.mark.parametrize("name", ["SIGINT", "SIGTERM"])
def test_a_signal_as_a_save_is_resumed_puts_it_back(tui, monkeypatch, game_clock, ctrl_c, name):
    keep_one()
    signal_once_taken(monkeypatch, getattr(signal, name))
    with cli._leave_on_signals():
        scr = tui([])
    assert scr.rc == 130
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 31}}
    assert store.get_stat("klondike")["total"] == 0


def test_ctrl_c_before_the_first_deal_leaves_quietly(tui, monkeypatch):
    def interrupted(deal, saved):
        raise KeyboardInterrupt

    monkeypatch.setattr(deals, "resumes", interrupted)
    assert tui([]).rc == 130


def test_game_flag_resumes_a_saved_game(tui):
    keep_one()
    scr = tui(["n", "q"])
    assert "Resumed your game (0:42, 31 moves)" in scr.frames[0]
    assert "Moves 31   Stock: 23  Waste: 1" in scr.frames[0]
    assert saves.waiting() == {}


@pytest.mark.parametrize("keys", [["n"], ["a", "n"]], ids=["n", "the banner's new deal"])
def test_a_resumed_chosen_deal_goes_on_to_the_next_number(tui, keys):
    assert saves.keep(near_won(5), 42)
    scr = tui([*keys, "q"])
    assert "Klondike  -  Deal 5" in scr.frames[0]
    assert "Klondike  -  Deal 6" in scr.frames[len(keys)]


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


@pytest.mark.parametrize(
    "keys",
    [["g", "6", ENTER], ["n"], ["o", curses.KEY_RIGHT, ENTER]],
    ids=["g", "n", "new options"],
)
def test_a_game_saved_in_another_window_meanwhile_is_told_of_too(tui, keys):
    scr = tui([Meanwhile(keep_one, keys[0]), *keys[1:], "q"], deal=5)
    assert UNKEPT not in scr.frames[0]
    assert UNKEPT in scr.frames[len(keys)]


def test_play_a_deal_says_so_of_a_game_saved_since_the_menu(tui):
    scr = tui([Mouse(PLAY_A_DEAL, 8), Meanwhile(keep_one, "5"), ENTER, "q"], start_key=None)
    assert "Resume your game" not in scr.frames[0]
    assert UNKEPT in scr.frames[-1]


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


def keep_a_daily(day=DAY):
    """Put Klondike's daily deal of `day`, one deal in and 0:42 on, in the
    saves folder."""
    g = deals.deal_game(deals.daily("klondike", day), {})
    g.deal()
    assert saves.keep(g, 42)


def test_opening_todays_daily_resumes_its_save(tui):
    keep_a_daily()
    scr = tui(["q"], start=deals.daily("klondike", DAY))
    assert "Resumed your game (0:42, 1 move). n deals a new hand." in scr.frames[0]
    assert "Klondike  -  Daily 2026-09-24" in scr.frames[0]
    assert "Moves 1 " in scr.frames[0]
    # and q puts it back as the same daily
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 1, "daily": "2026-09-24"}}


@pytest.fixture
def on_the_day(monkeypatch):
    """Make today 2026-09-24, as far as the daily deal goes."""
    monkeypatch.setattr(deals, "today", lambda: DAY)


def test_a_saved_daily_says_daily_on_the_menu(tui):
    keep_a_daily()
    scr = tui([ENTER, "q"], start_key=None)
    assert "> Klondike         Resume your daily game: 0:42, 1 move" in scr.frames[0]
    # a plain pick from the menu resumes it, still a daily
    assert "Resumed your game (0:42, 1 move)" in scr.frames[1]
    assert "Klondike  -  Daily 2026-09-24" in scr.frames[1]


def test_the_daily_list_resumes_todays_saved_daily(tui, on_the_day):
    keep_a_daily()
    scr = tui([Mouse(DAILY_DEAL, 8), ENTER, "q"], start_key=None)
    assert "Resumed your game (0:42, 1 move)" in scr.frames[2]
    assert "Klondike  -  Daily 2026-09-24" in scr.frames[2]


@pytest.mark.parametrize(
    "keep",
    [keep_one, lambda: keep_a_daily(date(2026, 9, 23))],
    ids=["a deal", "yesterday's daily"],
)
def test_opening_the_daily_over_another_save_says_it_wont_be_kept(tui, on_the_day, keep):
    keep()
    before = saves.waiting()
    scr = tui([Mouse(DAILY_DEAL, 8), ENTER, "q"], start_key=None)
    assert "a saved Klondike game is waiting, so this one won't be kept" in scr.frames[2]
    g = scr.uis[-1].game
    assert (g.deal_number, g.daily, g.moves) == (20260924, "2026-09-24", 0)
    assert saves.waiting() == before


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
    listed, real = saves.waiting(), saves.waiting
    # taken somewhere else once the menu has listed it
    monkeypatch.setattr(saves, "waiting", lambda *keys: real(*keys) if keys else listed)
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


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")
def test_a_signal_after_a_save_that_cant_be_kept_still_counts_the_loss(tui, monkeypatch):
    keep_one()
    real = saves.keep

    def keep(g, seconds):
        kept = real(g, seconds)
        # the waiting game is picked up in another window just then
        os.remove(saves.save_path("klondike"))
        os.kill(os.getpid(), signal.SIGTERM)
        return kept

    monkeypatch.setattr(saves, "keep", keep)
    with cli._leave_on_signals():
        tui(["d", "q"], deal=5)
    # as the notice says, the game counted as lost, and it wasn't kept after
    assert store.notices() == [
        "a saved Klondike game was already waiting, so this one counted as lost"
    ]
    assert store.get_stat("klondike")["total"] == 1
    assert saves.waiting() == {}


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


# -- a resumed game, whichever way it goes -------------------------------------------


@pytest.mark.parametrize(
    "leave",
    [["q"], ["m", "q"], [KeyboardInterrupt], [Signal("SIGHUP")], [Signal("SIGTERM")]],
    ids=["q", "m", "ctrl-c", "sighup", "sigterm"],
)
def test_leaving_a_resumed_game_keeps_it_again(tui, monkeypatch, game_clock, leave):
    if isinstance(leave[0], Signal) and not hasattr(signal, "SIGHUP"):
        pytest.skip("needs POSIX signals")
    monkeypatch.setattr(cli, "_quiet_output", lambda: None)
    keep_one()
    with cli._leave_on_signals():
        tui(["d", *leave])
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 32}}
    assert store.get_stat("klondike")["total"] == 0
    assert nothing_in_play()


def test_an_error_mid_game_keeps_it_and_goes_on(tui, game_clock):
    keep_one()
    with pytest.raises(RuntimeError):
        tui(["d", RuntimeError])
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 32}}
    assert store.get_stat("klondike")["total"] == 0
    assert nothing_in_play()


def test_an_error_keeping_it_doesnt_hide_the_error_that_led_there(tui, monkeypatch):
    keep_one()

    def keep(g, seconds):
        raise ValueError("and this")

    monkeypatch.setattr(saves, "keep", keep)
    with pytest.raises(RuntimeError):
        tui(["d", RuntimeError])
    # neither kept nor counted, so what was taken up is still in play, for
    # the next run to offer
    crashed()
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 31}}


@pytest.mark.parametrize("after", [["m", "q"], [KeyboardInterrupt]], ids=["m", "ctrl-c"])
def test_winning_a_resumed_game_takes_it_out_of_play(tui, after):
    assert saves.keep(near_won(5), 42)
    scr = tui(["a", *after])
    assert "YOU WIN" in scr.frames[1]
    assert store.get_stat("klondike")["wins"] == 1
    assert saves.waiting() == {}
    assert nothing_in_play()


@pytest.mark.parametrize(
    "keys, lost",
    [(["n"], 1), (["N"], 0), (["g", "6", ENTER, "y"], 1), (["o", curses.KEY_RIGHT, ENTER, "y"], 1)],
    ids=["n", "N", "g", "new options"],
)
def test_dealing_over_a_resumed_game_takes_it_out_of_play(tui, keys, lost):
    keep_one()
    tui([*keys, "q"])
    assert store.get_stat("klondike")["total"] == lost
    assert saves.waiting() == {}
    assert nothing_in_play()


def played_out():
    """Golf deal 1 played by its hints to where no move is left, as a real
    game gets there, with every move before it to undo."""
    g = deal("golf", 1)
    while not g.is_stuck():
        move = g.best_move()
        if move is None:
            assert g.deal()
        else:
            g.attempt_move(*move)
    return g


@pytest.mark.parametrize(
    "keys, lost, kept",
    [
        (["n", "q"], 1, False),
        (["m", "q"], 1, False),
        ([KeyboardInterrupt], 1, False),
        (["s", "q"], 0, False),  # replayed, which counts nothing
        (["u", "q"], 0, True),  # and played on
    ],
    ids=["n", "m", "ctrl-c", "same deal", "undo"],
)
def test_a_resumed_game_with_no_moves_left_comes_out_of_play(tui, keys, lost, kept):
    assert saves.keep(played_out(), 42)
    scr = tui(keys, start_key="golf")
    assert "No moves left" in scr.frames[0]
    assert store.get_stat("golf")["total"] == lost
    assert ("golf" in saves.waiting()) == kept
    assert nothing_in_play()


def test_a_game_resumed_again_in_the_same_run_is_taken_up_afresh(tui, game_clock):
    keep_one()
    scr = tui([ENTER, "d", "m", ENTER, "d", "m", "j", ENTER, "d", "q"], start_key=None)
    assert "Resumed your game (0:42, 32 moves)" in scr.frames[4]
    assert saves.waiting() == {
        "klondike": {"seconds": 42, "moves": 33},
        "spider": {"seconds": 0, "moves": 1},
    }
    assert nothing_in_play()


def test_a_resumed_game_outlasts_an_error_and_a_kill(tui, game_clock):
    keep_one()
    with pytest.raises(RuntimeError):
        tui(["d", RuntimeError])
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 32}}
    # taken up in text mode, played on, and the process killed
    with OtherCopy() as other:
        other.says("Resumed your Klondike game (0:42, 32 moves)")
        other.types("d")
        other.says("moves=33 ")
        other.kill()
    # the next run offers it as it was taken up
    scr = tui([ENTER, "d", "q"], start_key=None)
    assert "> Klondike         Resume your game: 0:42, 32 moves" in scr.frames[0]
    assert "Resumed your game (0:42, 32 moves)" in scr.frames[1]
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 33}}
    assert nothing_in_play()


ELSEWHERE = "a saved Klondike game is being played somewhere else, so this one won't be kept"


def test_a_game_another_copy_has_in_play_isnt_offered_here(tui):
    keep_one()
    with OtherCopy() as other:
        other.says("Resumed your Klondike game (0:42, 31 moves)")
        scr = tui([ENTER, "d", "q"], start_key=None)
        assert other.quits() == 0
    assert "Resume your game" not in scr.frames[0]
    # at the start, too long for the line at 80 columns, it goes over two
    assert ELSEWHERE[: -len(" won't be kept")] + " ..." in scr.frames[1]
    assert "\n  won't be kept\n" in scr.frames[2]
    # the game played here had no room to be kept; the other one did
    assert store.get_stat("klondike")["total"] == 1
    assert saves.waiting()["klondike"]["moves"] == 31


# -- a message too long for the line ------------------------------------------------


def message_line(frame):
    """What the message line says in a frame of the board, drawn with the
    code skin off: the row above the last."""
    return frame.split("\n")[-2].strip()


def elsewhere_note(key):
    """What a new deal of `key` says with a saved game of its kind in play
    in another copy of the game."""
    name = engine.GAMES[key].name
    return f"a saved {name} game is being played somewhere else, so this one won't be kept"


def one_up(key):
    """`key` with its first game kept in the saves folder, one move in."""
    g = deal(key, 4)
    g.moves = 1
    assert saves.keep(g, 42)


def all_but_a_king_up():
    """Klondike with every card home but the King of Clubs, in the first
    column."""
    g = near_won()
    fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
    for i, suit in enumerate("SHD"):
        g.slots[fids[i]].cards.append(up(13, suit))
        g.slots[tids[i]].cards = []
    g.slots[tids[0]].cards = [up(13, "C")]
    return g


@pytest.mark.parametrize(
    "start, key, keys, game",
    [
        ("fortythieves", "fortythieves", ["n"], None),
        ("fortythieves", "fortythieves", ["g", "5", ENTER], None),
        ("golf", "fortythieves", ["g", *"fortythieves:5", ENTER], None),
        ("golf", "fortythieves", ["m", *"jjjjj", ENTER], None),
        ("triplepeaks", "triplepeaks", ["o", curses.KEY_RIGHT, ENTER], None),
        ("klondike", "klondike", ["a", "n"], near_won),
    ],
    ids=["n", "g", "g-other-game", "menu", "o", "banner"],
)
def test_a_game_played_elsewhere_is_said_in_full_whenever_a_deal_comes(tui, start, key, keys, game):
    # each, too long for the line at 80 columns, goes over two, as it does
    # when the run starts
    note = elsewhere_note(key)
    assert len(note) > 72
    one_up(key)
    with in_play_elsewhere(key):
        scr = tui(
            [curses.KEY_RIGHT, *keys, curses.KEY_RIGHT, "q"],
            start_key=start,
            game=game and game(),
            h=24,
            w=80,
        )
    at = 1 + len(keys)  # the frame after the keys that bring the deal
    assert [message_line(frame) for frame in scr.frames[at : at + 2]] == note_pages(note)


def test_the_longest_game_played_elsewhere_goes_over_two_lines():
    notes = [elsewhere_note(key) for key in engine.GAME_ORDER]
    assert max(notes, key=len) == elsewhere_note("fortythieves")
    assert len(note_pages(elsewhere_note("fortythieves"))) == 2


def scorpion_with_only_kings_to_slide():
    g = deal("scorpion", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [up(13, "H"), up(2, "C")]
    g.slots[t[1]].cards = [up(13, "S"), up(3, "D")]
    return g


def spider_with_nothing_to_score():
    # a column empty and the stock not, and every card below another in its suit
    g = deal("spider", 1, suits=4)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = []
    for sid in t[1:]:
        g.slots[sid].cards = [up(6, "S"), up(5, "S")]
    return g


def spider_with_too_few_cards_to_deal():
    g = deal("spider", 1, suits=4)
    for sid in g.ids_of("tableau")[1:]:
        g.slots[sid].cards = []
    return g


def spiderette_with_two_empty_columns():
    g = deal("spiderette", 1)
    for sid in g.ids_of("tableau")[:2]:
        g.slots[sid].cards = []
    return g


@pytest.mark.parametrize(
    "key, make, k",
    [
        ("scorpion", scorpion_with_only_kings_to_slide, "h"),
        ("spider", spider_with_nothing_to_score, "h"),
        ("spider", spider_with_too_few_cards_to_deal, "d"),
        ("spiderette", spiderette_with_two_empty_columns, "d"),
    ],
    ids=["scorpion-hint", "spider-hint", "spider-deal", "spiderette-deal"],
)
def test_a_reason_too_long_for_the_line_goes_over_two(tui, key, make, k):
    g = make()
    why = g.no_hint_reason() if k == "h" else g.deal_blocked_reason()
    assert len(why) > 72
    scr = tui([k, curses.KEY_RIGHT, "q"], start_key=key, game=g, h=24, w=80)
    assert [message_line(frame) for frame in scr.frames[1:3]] == note_pages(why)


def test_the_rest_of_a_long_message_goes_once_the_line_says_something_else(tui, monkeypatch):
    long = "no move clearly helps from here, " * 5 + "so undo"
    monkeypatch.setattr(engine.Solitaire, "hint", lambda self: None)
    monkeypatch.setattr(engine.Solitaire, "no_hint_reason", lambda self: long)
    first, second, third = note_pages(long)
    # the King going up says nothing, so the second piece follows, and the
    # win comes; after the banner's new deal the third has gone with it
    scr = tui(["h", "f", "n", curses.KEY_RIGHT, "q"], game=all_but_a_king_up(), h=24, w=80)
    assert message_line(scr.frames[1]) == first
    assert "YOU WIN" in scr.frames[2]
    assert [message_line(frame) for frame in scr.frames[3:5]] == ["new deal", "new deal"]
    # the second piece was on the line as the win came, and the third never
    said = scr.uis[0].said
    assert second in said and third not in said


# -- hints and undos ---------------------------------------------------------------


def test_the_hints_and_undos_of_a_game_go_in_its_history_line(tui):
    tui(["h", "d", "d", "h", "u", "r", "U", "d", "n", "q"], deal=4)
    (e,) = history.games()
    assert (e["result"], e["moves"], e["hints"], e["undos"]) == ("lost", 1, 2, 3)


def test_undo_with_no_moves_left_counts_and_the_game_carries_on_counting(tui):
    g = played_out()
    g.hints, g.undos = 2, 5
    assert saves.keep(g, 42)
    tui(["u", "h", "q"], start_key="golf")
    assert (saved("golf")["hints"], saved("golf")["undos"]) == (3, 6)


def test_a_game_from_a_save_before_the_counts_has_none_in_its_line(tui):
    keep_one()
    from_before_the_counts()
    tui(["h", "d", "n", "q"])
    (e,) = history.games()
    assert e["moves"] == 32
    assert not {"hints", "undos"} & set(e)


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


DAILY_DEAL = 4 + len(engine.GAME_ORDER) + 1  # the menu's row under the games
DAILY_TOP = 4  # the daily list's first row
PLAY_A_DEAL = DAILY_DEAL + 1


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


@pytest.mark.parametrize("skin", [False, True])
def test_the_daily_list_shows_every_game_and_fits_80x24(tui, on_the_day, skin):
    if skin:
        code_skin_on()
    scr = tui([Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None, h=24, w=80)
    menu, daily = scr.frames[:2]
    assert menu.split("\n")[DAILY_DEAL].endswith("  Daily deal")
    assert "Terminal too small" not in daily
    rows = daily.split("\n")
    x = 6 + (CODE_GUTTER if skin else 0)
    assert rows[1][x - 2 :] == "Daily deals for 2026-09-24"
    assert rows[2][x - 2 :] == "Daily streak: none yet, win a daily to start one"
    # one row a game, starting on the last one played
    assert [row[x:] for row in rows[DAILY_TOP : DAILY_TOP + len(engine.GAME_ORDER)]] == [
        f"{'> ' if key == 'klondike' else '  '}{engine.GAMES[key].name:<16} {key}:20260924"
        for key in engine.GAME_ORDER
    ]
    footer = rows[DAILY_TOP + len(engine.GAME_ORDER) + 1]
    assert footer[x:] == "Up/Down move - Enter play - Esc back"
    assert "choose a game" in scr.frames[-1]
    assert not scr.uis


def test_the_daily_list_deals_the_chosen_games_daily(tui, on_the_day):
    # saved options, which a daily doesn't play by
    cfg = store.load_config()
    store.set_game_options(cfg, "spider", {"suits": 2})
    store.save_config(cfg)
    # from Klondike up past Quit, View statistics and Play a deal
    keys = [curses.KEY_UP] * 4 + [ENTER, "k", "j", curses.KEY_DOWN, ENTER]
    scr = tui(keys, start_key=None)
    assert "> Daily deal" in scr.frames[4]
    assert "> Klondike" in scr.frames[5]
    assert "> Pyramid" in scr.frames[6]  # k from the top goes round to the bottom
    assert "> Spider" in scr.frames[8]
    g = scr.uis[-1].game
    assert (g.gamedef.key, g.deal_number, g.options) == ("spider", 20260924, {"suits": 4})
    assert g.daily == "2026-09-24"
    assert "Spider  -  Daily 2026-09-24" in scr.frames[9]
    assert soliterm.tui.app.START_MESSAGE in scr.frames[9]
    assert store.load_config()["last_game"] == "spider"


def test_a_click_on_the_daily_list_plays_that_game(tui, on_the_day):
    freecell = DAILY_TOP + engine.GAME_ORDER.index("freecell")
    keys = [
        Mouse(DAILY_DEAL, 8),
        Mouse(freecell, 8, curses.BUTTON4_PRESSED),  # the wheel does nothing
        Mouse(freecell, 8, curses.BUTTON1_RELEASED),  # nor does letting go
        Mouse(1, 8),  # nor a click off the rows
        Mouse(freecell, 8),
    ]
    scr = tui(keys, start_key=None)
    assert all("> Klondike" in frame for frame in scr.frames[1:5])
    g = scr.uis[-1].game
    assert (g.gamedef.key, g.deal_number, g.daily) == ("freecell", 20260924, "2026-09-24")


@pytest.mark.parametrize("back", [[ESC, -1], ["q"], ["Q"]], ids=["Esc", "q", "Q"])
def test_esc_or_q_on_the_daily_list_goes_back_to_the_menu(tui, back):
    scr = tui([Mouse(DAILY_DEAL, 8), *back], start_key=None)
    assert "Daily deals for" in scr.frames[1]
    assert "choose a game" in scr.frames[-1]
    assert not scr.uis


def test_a_daily_keeps_its_day_past_midnight(tui, game_clock, monkeypatch):
    # the list opens a minute before midnight, and Enter comes after it
    midnight = game_clock.now + 60
    monkeypatch.setattr(
        deals, "today", lambda: DAY if game_clock.now < midnight else date(2026, 9, 25)
    )
    keys = [Mouse(DAILY_DEAL, 8), Later(120, ENTER), "d", "N", "d", "m"]
    scr = tui(keys + [Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None)
    assert "Daily deals for 2026-09-24" in scr.frames[1]
    assert "Klondike  -  Daily 2026-09-24" in scr.frames[2]
    assert "Klondike  -  Daily 2026-09-24" in scr.frames[4]  # after N
    assert scr.uis[-1].game.daily == "2026-09-24"
    assert "Resume your daily game" in scr.frames[6]
    assert saves.waiting()["klondike"]["daily"] == "2026-09-24"
    # a list opened now has the new day's deals
    assert "Daily deals for 2026-09-25" in scr.frames[7]
    assert "klondike:20260925" in scr.frames[7]


@pytest.mark.parametrize("skin", [False, True])
def test_the_menu_with_the_daily_deal_fits_80x24(tui, skin):
    if skin:
        code_skin_on()
    # the widest row there can be: a daily kept at 59:59 and a thousand moves
    g = deals.deal_game(deals.daily("klondike", DAY), {})
    g.moves = 1000
    assert saves.keep(g, 3599)
    scr = tui([Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None, h=24, w=80)
    menu = scr.frames[0]
    assert "Terminal too small" not in menu
    rows = menu.split("\n")
    x = 6 + (CODE_GUTTER if skin else 0)
    assert rows[4][x:] == "> Klondike         Resume your daily game: 59:59, 1000 moves"
    assert all(cls.name in menu for cls in engine.GAMES.values())
    assert [row[x:] for row in rows[DAILY_DEAL : DAILY_DEAL + 4]] == [
        "  Daily deal",
        "  Play a deal",
        "  View statistics",
        "  Quit",
    ]
    assert rows[DAILY_DEAL + 5][x:] == "Up/Down move - Enter select - mouse click - q quit"
    assert "Daily deals for" in scr.frames[1]
    assert "Terminal too small" not in scr.frames[1]


def played_daily(key, won, seconds=60, moves=40, day=DAY):
    """A daily deal of `key` on `day` in the history, won or lost."""
    g = deals.deal_game(deals.daily(key, day), {})
    g.moves = moves
    history.record(g, won, seconds)


def keep_daily(key, seconds, moves, day=DAY):
    """A daily deal of `key` on `day` left under way in the saves folder."""
    g = deals.deal_game(deals.daily(key, day), {})
    g.moves = moves
    assert saves.keep(g, seconds)


def daily_rows(frame, x=6):
    """The daily list's rows in frame, by game, without the > of the one
    picked."""
    rows = frame.split("\n")[DAILY_TOP:]
    return {key: row[x + 2 :] for key, row in zip(engine.GAME_ORDER, rows)}


def test_the_daily_list_says_how_each_daily_went(tui, on_the_day):
    # won twice and lost once: the faster win, with its moves
    played_daily("klondike", True, 192, 87)
    played_daily("klondike", False)
    played_daily("klondike", True, 161, 98)
    played_daily("pyramid", False)
    # played and left under way, or lost and then left under way
    keep_daily("yukon", 42, 31)
    played_daily("golf", False)
    keep_daily("golf", 75, 1)
    # none of which is today's daily
    played_daily("freecell", True, day=date(2026, 9, 23))
    keep_daily("spider", 42, 31, day=date(2026, 9, 23))
    history.record(deal("canfield", 20260924), True, 60)
    scr = tui([Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None)
    rows = daily_rows(scr.frames[1])
    assert rows["klondike"] == "Klondike         klondike:20260924      won in 2:41, 98 moves"
    assert rows["pyramid"] == "Pyramid          pyramid:20260924       played, not won yet"
    assert rows["yukon"] == "Yukon            yukon:20260924         saved at 0:42, 31 moves"
    assert rows["golf"] == "Golf             golf:20260924          saved at 1:15, 1 move"
    for key in ["freecell", "spider", "canfield", "spiderette"]:
        assert rows[key] == f"{engine.GAMES[key].name:<16} {key}:20260924", key


@pytest.mark.parametrize(
    "won, streak",
    [
        ([], "none yet, win a daily to start one"),
        ([24], "1 day"),
        ([22, 23, 24], "3 days"),
        ([23], "1 day, win one today to keep it"),
        ([19, 20, 21, 23, 24], "2 days (longest 3)"),
        ([18, 19, 20, 23], "1 day (longest 3), win one today to keep it"),
        ([19, 20, 21], "none now (longest 3 days), win a daily to start one"),
        ([22], "none now (longest 1 day), win a daily to start one"),
    ],
)
def test_the_daily_list_shows_the_daily_streak(tui, on_the_day, won, streak):
    for day in won:
        played_daily("golf", True, day=date(2026, 9, day))
    played_daily("klondike", False)  # a daily lost today doesn't count
    frame = tui([Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None).frames[1]
    assert frame.split("\n")[2] == f"    Daily streak: {streak}"


def test_the_daily_list_reads_the_history_once_each_time_it_opens(
    tui, on_the_day, game_clock, monkeypatch
):
    reads = []
    games = history.games
    monkeypatch.setattr(history, "games", lambda: reads.append(1) or games())
    seen = []
    keys = [
        Mouse(DAILY_DEAL, 8),
        curses.KEY_DOWN,
        Resize(30, 100),
        Resize(40, 120),
        # a daily won in another window while the list is up
        Meanwhile(lambda: (seen.append(len(reads)), played_daily("golf", True, 75, 30)), ESC),
        -1,
        Mouse(DAILY_DEAL, 8),
        # and one played here and left under way
        ENTER,
        "d",
        "m",
        Mouse(DAILY_DEAL, 8),
        ESC,
        -1,
    ]
    scr = tui(keys, start_key=None)
    assert seen == [1]  # not again on a key or a resize
    assert all("won in" not in frame for frame in scr.frames[1:6])
    assert daily_rows(scr.frames[7])["golf"].endswith("won in 1:15, 30 moves")
    assert "Klondike  -  Daily 2026-09-24" in scr.frames[8]
    assert daily_rows(scr.frames[11])["klondike"].endswith("saved at 0:00, 1 move")
    assert len(reads) == 3


@pytest.mark.parametrize("won", [True, False], ids=["won", "lost"])
def test_a_daily_played_today_can_be_played_again(tui, on_the_day, won):
    played_daily("klondike", won, 192, 87)
    scr = tui([Mouse(DAILY_DEAL, 8), ENTER, "q"], start_key=None)
    said = "won in 3:12, 87 moves" if won else "played, not won yet"
    assert daily_rows(scr.frames[1])["klondike"].endswith(said)
    g = scr.uis[-1].game
    assert (g.gamedef.key, g.deal_number, g.daily) == ("klondike", 20260924, "2026-09-24")
    fresh = deals.deal_game(deals.daily("klondike", DAY), {})
    assert [s.cards for s in g.slots] == [s.cards for s in fresh.slots]
    assert "Klondike  -  Daily 2026-09-24" in scr.frames[2]


def test_the_daily_list_keeps_its_day_past_midnight(tui, game_clock, monkeypatch):
    played_daily("klondike", True, 192, 87)
    # the list opens a minute before midnight and is drawn again after it
    midnight = game_clock.now + 60
    monkeypatch.setattr(
        deals, "today", lambda: DAY if game_clock.now < midnight else date(2026, 9, 25)
    )
    keys = [Mouse(DAILY_DEAL, 8), Later(120, Resize(30, 100)), ESC, -1]
    scr = tui(keys + [Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None)
    for frame in scr.frames[1:4]:
        assert "Daily deals for 2026-09-24" in frame
        assert frame.split("\n")[2] == "    Daily streak: 1 day"
        assert daily_rows(frame)["klondike"].endswith("won in 3:12, 87 moves")
    assert len(scr.frames[2].split("\n")) == 30  # drawn again after midnight
    # opened again, it's the new day's, not won yet
    frame = scr.frames[5]
    assert "Daily deals for 2026-09-25" in frame
    assert frame.split("\n")[2] == "    Daily streak: 1 day, win one today to keep it"
    assert daily_rows(frame)["klondike"] == "Klondike         klondike:20260925"


@pytest.mark.parametrize("skin", [False, True], ids=["plain", "code-skin"])
@pytest.mark.parametrize("more", [0, 24], ids=["the-games", "24-more"])
def test_the_widest_daily_row_fits_80x24(tui, on_the_day, monkeypatch, skin, more):
    monkeypatch.setattr(FakeScr, "encoding", "ascii")  # the C locale
    if skin:
        code_skin_on()
    order = add_games(monkeypatch, more) if more else engine.GAME_ORDER
    # the longest name and the longest code there are, won in the longest
    # time the list makes room for, and a save of as long
    played_daily("fortythieves", True, 5999, 999)
    keep_daily("triplepeaks", 5999, 999)
    frame = tui([Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None, h=24, w=80).frames[1]
    assert "Terminal too small" not in frame
    x = 6 + (CODE_GUTTER if skin else 0)
    rows = daily_rows(frame, x)
    widest = "Forty Thieves    fortythieves:20260924  won in 99:59, 999 moves"
    assert rows["fortythieves"] == widest
    assert (
        rows["triplepeaks"] == "Triple Peaks     triplepeaks:20260924   saved at 99:59, 999 moves"
    )
    # with a column to spare, as every screen leaves the last one empty
    assert x + 2 + len(widest) < 80
    # the list scrolls, if it has to, under the streak and over the footer
    lines = frame.split("\n")
    assert len(lines) == 24
    assert lines[2][x - 2 :] == "Daily streak: 1 day"
    shown = min(len(order), 24 - DAILY_TOP - 2)
    assert ("more below" in frame) == (shown < len(order))
    assert lines[DAILY_TOP + shown + 1][x:] == "Up/Down move - Enter play - Esc back"


@pytest.mark.parametrize("skin", [False, True])
def test_every_game_s_menu_row_fits_80_columns(tui, skin):
    if skin:
        code_skin_on()
    rows = tui(["q"], start_key=None, h=24, w=80).frames[0].split("\n")
    x = 6 + (CODE_GUTTER if skin else 0)
    for i, cls in enumerate(engine.GAMES[key] for key in engine.GAME_ORDER):
        assert cls.short_blurb
        # the whole line, as the menu leaves the last column empty
        assert rows[4 + i][x + 2 :] == f"{cls.name:<16} {cls.short_blurb}"


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
    monkeypatch.setattr(cli, "_check_terminal", lambda: ("", ""))
    for argv, color in ([], None), (["--color"], True), (["--no-color"], False):
        cli.main(["--game", "klondike"] + argv)
        assert seen["color"] is color


def test_no_animation_reaches_the_tui(monkeypatch):
    seen = {}
    monkeypatch.setattr(soliterm.tui, "main", lambda *a, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_check_terminal", lambda: ("", ""))
    for argv, animation in ([], None), (["--no-animation"], False):
        cli.main(["--game", "klondike"] + argv)
        assert seen["animation"] is animation


def test_theme_flag_is_for_one_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(soliterm.tui, "main", lambda *a, **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_check_terminal", lambda: ("", ""))
    for argv, theme in ([], None), (["--theme", "light"], "light"):
        cli.main(["--game", "klondike"] + argv)
        assert seen["theme"] == theme
    assert "theme" not in store.load_config()


def curses_pairs(theme, colours, **kwargs):
    """themes.pair_colours in curses' own numbers for the basic 8, as the
    tui hands them to init_pair."""
    return themes.pair_colours(theme, colours, basic=basic_colours(), **kwargs)


def test_a_theme_for_one_run_leaves_the_saved_one_alone(tui):
    store.save_config({**store.load_config(), "theme": "dark"})
    scr = tui(["v"], theme="light", colours=256)
    assert scr.pairs == curses_pairs(themes.LIGHT, 256)
    assert store.load_config()["theme"] == "dark"


def test_t_after_a_theme_for_one_run_saves_the_next_one(tui):
    scr = tui(["t"], theme="light")
    assert "contrast theme" in scr.frames[1]
    assert store.load_config()["theme"] == "contrast"


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
    pairs = {n: (fg, bg) for n, fg, bg in scr.pairs}
    assert pairs[themes.CHROME] == (curses.COLOR_CYAN, -1)
    assert pairs[themes.MESSAGE] == (curses.COLOR_YELLOW, -1)


@pytest.mark.parametrize(
    "colorfgbg, chrome, note",
    [
        pytest.param("15;0", curses.COLOR_CYAN, curses.COLOR_YELLOW, id="dark background"),
        pytest.param("0;15", curses.COLOR_BLUE, curses.COLOR_MAGENTA, id="light background"),
    ],
)
def test_classic_draws_the_pairs_1_0_0_drew(tui, monkeypatch, colorfgbg, chrome, note):
    monkeypatch.setenv("COLORFGBG", colorfgbg)
    scr = tui(["q"])
    assert [pair for pair in scr.pairs if pair[0] <= 9] == [
        (1, curses.COLOR_RED, curses.COLOR_WHITE),
        (2, curses.COLOR_BLACK, curses.COLOR_WHITE),
        (3, curses.COLOR_BLACK, curses.COLOR_GREEN),
        (4, chrome, -1),
        (5, curses.COLOR_BLACK, curses.COLOR_YELLOW),
        (6, note, -1),
        (7, curses.COLOR_WHITE, curses.COLOR_BLUE),
        (8, curses.COLOR_WHITE, curses.COLOR_GREEN),
        (9, curses.COLOR_BLACK, curses.COLOR_CYAN),
    ]


# PDCurses, the curses windows-curses brings, numbers the basic 8 by their
# blue, green and red bits, where ncurses has them in the ANSI order
PDCURSES = {
    "BLACK": 0,
    "BLUE": 1,
    "GREEN": 2,
    "CYAN": 3,
    "RED": 4,
    "MAGENTA": 5,
    "YELLOW": 6,
    "WHITE": 7,
}


def test_the_pairs_are_in_the_colour_numbers_of_the_curses_at_hand(tui, monkeypatch):
    for name, n in PDCURSES.items():
        monkeypatch.setattr(curses, "COLOR_" + name, n)
    scr = tui(["4"], colours=256)
    size = len(themes.CLASSIC.pairs)
    first, again = scr.pairs[:size], scr.pairs[size:]
    # red cards and blue backs, cyan labels and yellow messages, not the
    # other way round
    assert (themes.FACE_RED, 4, 7) in first
    assert (themes.BACK, 7, 1) in first
    assert (themes.CHROME, 3, -1) in first
    assert (themes.MESSAGE, 6, -1) in first
    # while the four-colour deck's tuned colours are xterm's on any curses
    assert (themes.DIAMOND_FACE, 166, 7) in again
    assert (themes.CLUB_FACE, 28, 7) in again
    scr.pairs.clear()
    # and on 8 colours its diamonds are blue
    scr = tui(["q"])
    assert (themes.DIAMOND_FACE, 1, 7) in scr.pairs


@pytest.mark.parametrize(
    "platform, env, colours, picked",
    [
        # PDCurses says 768 in any console, and writes xterm's colour codes,
        # the first 256 of them xterm's, in Windows Terminal and in ConEmu
        # with its ANSI on
        ("win32", {"WT_SESSION": "1f0c"}, 768, 256),
        ("win32", {"CONEMUANSI": "ON"}, 768, 256),
        # the classic console has the nearest of its own 16 for each
        ("win32", {}, 768, 16),
        ("win32", {"CONEMUANSI": "OFF"}, 768, 16),
        ("linux", {}, 256, 256),
        ("linux", {}, 88, 88),
        # direct colour would draw the 256 as dark blues
        ("linux", {}, 16777216, 16777216),
    ],
)
@pytest.mark.parametrize("name", ["dark", "light", "contrast"])
def test_the_tuned_colours_go_where_curses_has_them(
    tui, monkeypatch, platform, env, colours, picked, name
):
    monkeypatch.setattr(sys, "platform", platform)
    if platform == "win32":
        for colour, n in PDCURSES.items():
            monkeypatch.setattr(curses, "COLOR_" + colour, n)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    scr = tui(["q"], theme=name, colours=colours)
    assert scr.pairs == curses_pairs(themes.by_name(name), picked)


def test_the_classic_console_keeps_the_four_colour_deck_apart(tui, monkeypatch):
    # there the tuned orange, 166, would be drawn in the hearts' dark red
    monkeypatch.setattr(sys, "platform", "win32")
    for colour, n in PDCURSES.items():
        monkeypatch.setattr(curses, "COLOR_" + colour, n)
    scr = tui(["4"], colours=768)
    pairs = {n: (fg, bg) for n, fg, bg in scr.pairs}
    assert pairs[themes.DIAMOND_FACE] == (PDCURSES["BLUE"], PDCURSES["WHITE"])
    assert pairs[themes.FACE_RED] == (PDCURSES["RED"], PDCURSES["WHITE"])


def bold_text_colours(tui, monkeypatch, platform, theme, colours):
    """The text colour of everything drawn bold in a short game: the board
    with its cursor, a card picked up and the stock's count, and the menu,
    in theme on `platform` with `colours` colours."""
    drawn = []
    real = FakeScr.addnstr

    def addnstr(self, y, x, text, n, attr=0):
        drawn.append(attr)
        real(self, y, x, text, n, attr)

    monkeypatch.setattr(FakeScr, "addnstr", addnstr)
    monkeypatch.setattr(sys, "platform", platform)
    if platform == "win32":
        for colour, n in PDCURSES.items():
            monkeypatch.setattr(curses, "COLOR_" + colour, n)
        # in Windows Terminal, where the tuned colours are drawn
        monkeypatch.setenv("WT_SESSION", "1f0c")
    scr = tui([ENTER, "m", "q"], deal=1, theme=theme, colours=colours)
    pairs = {n: (fg, bg) for n, fg, bg in scr.pairs}
    return [pairs.get((attr >> 8) & 0xFF, (-1, -1))[0] for attr in drawn if attr & curses.A_BOLD]


@pytest.mark.parametrize("theme", ["classic", "dark"])
def test_bold_leaves_the_colours_alone_on_windows(tui, monkeypatch, theme):
    # PDCurses has no bold type and draws A_BOLD as the text colour plus 8,
    # which would turn the cursor's black grey and the dark theme's white
    # (231) on a red card picked up the dark grey 239. Bold stays where it
    # brightens the text: the terminal's own colour and the basic ones
    bold = bold_text_colours(tui, monkeypatch, "win32", theme, 768)
    assert all(fg == -1 or 1 <= fg <= 7 for fg in bold), bold
    if theme == "classic":
        # the labels, in cyan, are still bright
        assert PDCURSES["CYAN"] in bold


def test_bold_goes_by_the_pair_where_pdcurses_keeps_it(monkeypatch):
    # windows-curses keeps the pair in the top 8 bits, and pair_number in
    # Python 3.9 gives 0 for every pair there
    from soliterm.tui.board import drawn_attr

    bold = 0x800000
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(curses, "A_COLOR", -0x1000000)
    monkeypatch.setattr(curses, "A_BOLD", bold)
    monkeypatch.setattr(curses, "COLOR_BLACK", 0)
    monkeypatch.setattr(curses, "pair_number", lambda attr: 0)
    # PDCurses answers 7 for the terminal's own text colour
    content = {0: (7, 0), 3: (0, 2), 4: (3, 7), 7: (231, 25)}
    monkeypatch.setattr(curses, "pair_content", content.__getitem__)
    assert drawn_attr(3 << 24 | bold) == 3 << 24  # black on green
    assert drawn_attr(7 << 24 | bold) == 7 << 24  # 231 on 25
    assert drawn_attr(4 << 24 | bold) == 4 << 24 | bold  # cyan, made bright
    assert drawn_attr(bold) == bold  # the terminal's own colours
    assert drawn_attr(3 << 24) == 3 << 24


def test_bold_is_bold_as_ever_off_windows(tui, monkeypatch):
    bold = bold_text_colours(tui, monkeypatch, "linux", "dark", 256)
    assert 16 in bold and 231 in bold


def pairs_on(tui, monkeypatch, colorfgbg, **kwargs):
    """The init_pair calls of a session on a terminal that says colorfgbg."""
    monkeypatch.setenv("COLORFGBG", colorfgbg)
    scr = tui(["q"], **kwargs)
    pairs = list(scr.pairs)
    scr.pairs.clear()  # the next session starts its own list
    return pairs


@pytest.mark.parametrize("colours", [8, 256])
@pytest.mark.parametrize("name", ["dark", "light"])
def test_dark_and_light_ignore_a_light_background(tui, monkeypatch, name, colours):
    theme = themes.by_name(name)
    assert theme.name == name
    on_dark = pairs_on(tui, monkeypatch, "15;0", theme=name, colours=colours)
    on_light = pairs_on(tui, monkeypatch, "0;15", theme=name, colours=colours)
    assert on_dark == on_light == curses_pairs(theme, colours)


@pytest.mark.parametrize("colours", [8, 256])
@pytest.mark.parametrize("name", ["classic", "contrast"])
def test_classic_and_contrast_follow_a_light_background(tui, monkeypatch, name, colours):
    theme = themes.by_name(name)
    assert theme.name == name
    on_dark = pairs_on(tui, monkeypatch, "15;0", theme=name, colours=colours)
    on_light = pairs_on(tui, monkeypatch, "0;15", theme=name, colours=colours)
    assert on_dark == curses_pairs(theme, colours, light=False)
    assert on_light == curses_pairs(theme, colours, light=True)


def test_pairs_past_the_terminals_limit_fall_back(tui):
    # a terminal with room for pairs 0 to 9 only
    scr = tui(["d", "q"], color_pairs=10)
    assert scr.rc == 0
    assert "Moves 1" in scr.frames[1]
    assert scr.pairs and all(n < 10 for n, _, _ in scr.pairs)
    ui = scr.uis[-1]
    assert ui.CP(themes.HINT) == curses.color_pair(themes.HINT)
    # the four-colour deck goes back to red and black
    assert ui.CP(themes.DIAMOND_FACE) == ui.CP(themes.FACE_RED)
    assert ui.CP(themes.CLUB_FACE) == ui.CP(themes.FACE_BLACK)
    # the code skin's comments look like its line numbers
    assert ui.CP(themes.COMMENT) == ui.CP(themes.CHROME)
    # and the terminal's own colours, for a pair with nothing to stand in
    for n in (themes.KEYWORD, themes.STRING, themes.NUMBER):
        assert ui.CP(n) == 0


def test_a_red_card_picked_up_stays_green_with_only_8_pairs(tui):
    # qnx and a few others have room for pairs 0 to 7 only
    scr = tui(["q"], color_pairs=8)
    assert scr.rc == 0
    assert scr.pairs and all(n < 8 for n, _, _ in scr.pairs)
    ui = scr.uis[-1]
    red, black = Card(1, "H", face_up=True), Card(1, "S", face_up=True)
    assert ui.card_attr(red, True, False) == ui.card_attr(black, True, False)
    assert ui.card_attr(red, True, False) & 0xFF00 == curses.color_pair(themes.SELECTED)
    # a hint is in the terminal's own colours, which no other card is drawn
    # in, so it can't be taken for the cursor or the selection
    hinted = ui.card_attr(red, False, True) & 0xFF00
    assert hinted == 0
    others = {ui.card_attr(red, False, False), ui.card_attr(black, False, False)}
    others |= {ui.card_attr(None, False, False), ui.card_attr(Card(1, "H"), False, False)}
    others |= {ui.card_attr(red, False, False, cursor=True)}
    assert hinted not in {attr & 0xFF00 for attr in others}


@pytest.mark.parametrize("room", [8, 10, 15])
def test_the_four_colour_deck_on_a_terminal_with_too_few_pairs(tui, room):
    # it needs pairs 14 and 15; the choice is kept for a terminal that has them
    scr = tui(["4", "4", "q"], color_pairs=room)
    assert scr.rc == 0
    assert "four-colour deck on (this terminal can't show it)" in scr.frames[1]
    assert "four-colour deck off" in scr.frames[2] and "show it" not in scr.frames[2]
    assert scr.pairs and all(n < room for n, _, _ in scr.pairs)
    tui(["4", "q"], color_pairs=room)
    assert store.load_config()["four_color"] is True


def test_the_four_colour_deck_on_a_terminal_with_room_for_it(tui):
    scr = tui(["4", "q"], color_pairs=16)
    assert "four-colour deck on" in scr.frames[1] and "show it" not in scr.frames[1]


@pytest.mark.parametrize("name", themes.NAMES)
def test_a_card_back_keeps_a_colour_with_only_7_pairs(tui, name):
    # pair 7 is the back's. In the terminal's own colours it would look
    # like a hint, which is drawn in those with fewer than 10 pairs, and
    # the contrast theme draws its chrome in them too
    scr = tui(["q"], color_pairs=7, theme=name)
    ui = scr.uis[-1]
    back = ui.card_attr(Card(1, "H"), False, False) & 0xFF00
    hint = ui.card_attr(Card(1, "H", face_up=True), False, True) & 0xFF00
    assert back == curses.color_pair(themes.FACE_BLACK) != hint


def test_a_hinted_card_has_a_background_of_its_own(tui):
    # so it reads on a light terminal as well as a dark one
    g = deal("klondike", 1)
    scr = tui(["h"], game=g)
    ui = scr.uis[-1]
    card = g.slots[g.hint()[0]].top
    fg, bg = pair_of(ui.card_attr(card, False, True), scr)
    assert bg not in (-1, fg)


@pytest.mark.parametrize("key", ["v", "t", "4"])
def test_the_colour_keys_on_a_mono_terminal_just_say_so(tui, key):
    scr = tui([key], color_capable=False)
    assert "this terminal has no colour support" in scr.frames[1]
    assert scr.pairs == []
    cfg = store.load_config()
    assert "color" not in cfg
    assert "theme" not in cfg
    assert "four_color" not in cfg


def test_4_turns_the_four_colour_deck_on_and_saves_it(tui):
    white = curses.COLOR_WHITE
    scr = tui(["4"], colours=256)
    assert "four-colour deck on" in scr.frames[1]
    assert "colour is off" not in scr.frames[1]
    size = len(themes.CLASSIC.pairs)
    first, again = scr.pairs[:size], scr.pairs[size:]
    assert (themes.DIAMOND_FACE, curses.COLOR_RED, white) in first
    # set up again, so the cards on screen change at once
    assert (themes.DIAMOND_FACE, 166, white) in again
    assert (themes.CLUB_FACE, 28, white) in again
    assert store.load_config()["four_color"] is True
    scr.pairs.clear()
    # and the next run starts with it, until 4 turns it off
    scr = tui(["4"], colours=256)
    assert (themes.DIAMOND_FACE, 166, white) in scr.pairs[:size]
    assert "four-colour deck off" in scr.frames[1]
    assert (themes.DIAMOND_FACE, curses.COLOR_RED, white) in scr.pairs[size:]
    assert store.load_config()["four_color"] is False


def test_4_with_colour_off_says_so(tui):
    scr = tui(["4"], color=False)
    assert "four-colour deck on (colour is off, v turns it on)" in scr.frames[1]
    assert store.load_config()["four_color"] is True


def test_t_cycles_the_themes_and_saves_the_choice(tui):
    scr = tui(["t", "t", "t", "t"], colours=256)
    assert "dark theme" in scr.frames[1]
    assert "light theme" in scr.frames[2]
    assert "contrast theme" in scr.frames[3]
    assert "classic theme" in scr.frames[4]
    assert "colour is off" not in scr.frames[1]
    # every press sets the pairs up again, and the board shows the new ones
    size = len(themes.CLASSIC.pairs)
    sets = [scr.pairs[i : i + size] for i in range(0, len(scr.pairs), size)]
    assert sets == [
        curses_pairs(themes.by_name(name), 256)
        for name in ("classic", "dark", "light", "contrast", "classic")
    ]
    assert scr.uis[-1].has_color
    assert store.load_config()["theme"] == "classic"


def test_t_with_colour_off_says_how_to_turn_it_on(tui):
    scr = tui(["t"], color=False)
    assert "dark theme (colour is off, v turns it on)" in scr.frames[1]
    assert not scr.uis[-1].has_color
    cfg = store.load_config()
    assert cfg["theme"] == "dark"
    assert "color" not in cfg


def test_the_saved_theme_is_the_one_played(tui):
    store.save_config({**store.load_config(), "theme": "light"})
    scr = tui(["q"], colours=256)
    assert scr.pairs == curses_pairs(themes.LIGHT, 256)


def test_an_unknown_theme_name_is_kept_and_plays_classic(tui):
    # a newer version's theme, say; this one plays classic and leaves it be
    store.save_config({**store.load_config(), "theme": "solarized"})
    scr = tui(["v"], colours=256)
    assert scr.pairs == curses_pairs(themes.CLASSIC, 256)
    cfg = store.load_config()
    assert cfg["color"] is False
    assert cfg["theme"] == "solarized"


def test_v_turns_colour_off_and_on_and_saves_it(tui):
    scr = tui(["v", "v"])
    assert sorted(pair[0] for pair in scr.pairs) == sorted(themes.CLASSIC.pairs)
    ui = scr.uis[0]
    assert ui.initial_has_color
    assert "colour off" in scr.frames[1]
    assert "colour on" in scr.frames[2]
    assert ui.has_color is True
    assert store.load_config()["color"] is True


def test_v_after_no_color_turns_colour_on(tui):
    # pairs are set up on capability, so colour can come on later
    scr = tui(["v"], color=False)
    assert sorted(pair[0] for pair in scr.pairs) == sorted(themes.CLASSIC.pairs)
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


@pytest.mark.parametrize(
    "kwargs, mark",
    [({}, "  "), ({"color": False}, "> "), ({"color_capable": False}, "> ")],
    ids=["colour", "off", "mono"],
)
def test_the_picked_statistics_row_can_be_seen_without_colour(tui, kwargs, mark):
    # lit up in colour, and with the menu's > where there's no colour
    lines = tui(["s", curses.KEY_DOWN, "z"], **kwargs).frames[2].split("\n")
    assert any(line.startswith(f"    {mark}Spider  ") for line in lines)
    assert any(line.startswith("      Klondike  ") for line in lines)


def test_the_stats_screen_rounds_a_half_percent_up_as_aisleriot_does(tui):
    store.save_stats({"golf": {"wins": 1, "total": 8, "best": 50, "worst": 50}})
    lines = [line.rstrip() for line in tui(["s", "z"]).frames[1].split("\n")]
    assert "      Golf                 1      8    13%    0:50    0:50     N/A     N/A" in lines


def test_the_stats_screen_says_they_are_shared_with_aisleriot(tui, keyfile):
    keyfile("")
    assert "(shared with GNOME AisleRiot - sol)" in tui(["s", "z"]).frames[1]


def test_the_stats_screen_says_sharing_waits_for_aisleriot_to_run(tui, monkeypatch):
    # sol is installed but has never been run, so its keyfile has no folder
    # to go in yet and results wait here
    monkeypatch.setattr(ar, "installed", lambda: True)
    frame = tui(["s", "z"]).frames[1]
    assert "(will be shared with GNOME AisleRiot once sol has run)" in frame
    assert "(shared with" not in frame


# -- a game's records ---------------------------------------------------------------------


def write_history(*lines):
    """A history of these lines and no others, as history.record writes them."""
    os.makedirs(store.data_dir(), exist_ok=True)
    with open(history.history_path(), "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e) + "\n" for e in lines)


def played(key="klondike", result="won", day="2026-09-20", **more):
    """A line of the history, of a game finished in the morning of `day`. A
    win scores what every win of Klondike does."""
    return {
        "at": f"{day}T10:00:00+10:00",
        "game": key,
        "options": engine.GAMES[key].default_options(),
        "deal": 7,
        "result": result,
        "seconds": 100,
        "moves": 50,
        "score": 52 if result == "won" else 0,
        "hints": 1,
        "undos": 0,
        **more,
    }


def a_full_history():
    """A history with something in every one of Klondike's records."""
    draw3 = {"draw": 3, "redeals": "standard"}
    write_history(
        played(result="lost", day="2026-09-01", options={"draw": 1, "redeals": "none"}, score=38),
        played(day="2026-09-02", options=draw3, deal=48213, seconds=141, moves=98, hints=0),
        played(day="2026-09-03", daily="2026-09-03", deal=20260903, seconds=300, moves=85),
        played(day="2026-09-04", daily="2026-09-04", deal=20260904, seconds=400, moves=99),
        played(result="lost", day="2026-09-05", score=20),
        played(day="2026-09-06", seconds=200, moves=110),
        *(played(key, day="2026-09-07") for key in ("spider", "golf", "freecell")),
    )


INTRO = [
    "Only the games played here in Soliterm count, so these can be fewer",
    "than the Wins and Total, which count AisleRiot's games when shared.",
]
FULL_RECORDS = [
    *INTRO,
    "",
    "Played        6 since 2026-09-01, and won 4",
    "Win streak    1 now, longest 3",
    "",
    "                  Time  Moves  Deal                       Date",
    "Fastest win       2:21     98  klondike:d3:48213          2026-09-02",
    "                               draw 3, redeals standard",
    "Fewest moves      5:00     85  daily 2026-09-03           2026-09-03",
    "",
    "Best score    52, a win        draw 1, redeals standard   2026-09-03",
    "              38 of 52         draw 1, redeals none       2026-09-01",
    "              52, a win        draw 3, redeals standard   2026-09-02",
    "",
    "Achievements",
    "Clean win     2026-09-02  a win with no hint and no undo",
    "Every game    4 of 13     to win: Spiderette, Eight Off and 7 more",
    "Seven dailies 2 of 7      the longest run of days with a daily won",
]
RECORDS_FOOTER = "Left/Right other games - any other key goes back"


def page_of(frame, dx=0):
    """The lines of a records page under its title, down to the gap above
    the footer, without the indent they all have. dx is how far the code
    skin moves the page right."""
    rows = [row[dx:].rstrip() for row in frame.split("\n")]
    (title,) = [y for y, row in enumerate(rows) if row.endswith(" - records")]
    (footer,) = [y for y, row in enumerate(rows) if RECORDS_FOOTER in row]
    assert rows[footer - 1] in ("", "#")
    return [row[6:] for row in rows[title + 1 : footer - 1]]


def test_enter_on_the_statistics_opens_the_records_of_the_game_picked(tui):
    a_full_history()
    scr = tui(["s", ENTER, "z"])
    frame = scr.frames[2]
    assert "    Klondike - records" in frame.split("\n")
    assert page_of(frame) == FULL_RECORDS
    assert "Statistics" not in frame and "Score" not in frame


def test_a_game_not_played_here_says_so_and_still_has_its_achievements(tui):
    scr = tui(["s", curses.KEY_DOWN, curses.KEY_DOWN, ENTER, "z"])
    assert "Spiderette - records" in scr.frames[4]
    assert page_of(scr.frames[4]) == [
        *INTRO,
        "",
        "No games of Spiderette played here yet.",
        "",
        "Achievements",
        "Clean win     not yet     a win with no hint and no undo",
        "Every game    0 of 13     a win in every game",
        "Seven dailies 0 of 7      the longest run of days with a daily won",
    ]


def test_a_game_played_but_not_won_has_no_fastest_win_yet(tui):
    write_history(played("golf", "lost", score=12), played("golf", "lost", day="2026-09-21"))
    frame = tui(["s", *[curses.KEY_DOWN] * 5, ENTER, "z"]).frames[7]
    assert page_of(frame)[3:10] == [
        "Played        2 since 2026-09-20, and won 0",
        "Win streak    0 now, longest 0",
        "",
        "Fastest win   no win yet",
        "Fewest moves  no win yet",
        "",
        "Best score    12 of 35         golf:7                     2026-09-20",
    ]


@pytest.mark.parametrize(
    "won, row",
    [
        (12, "Every game    12 of 13    to win: Pyramid"),
        (11, "Every game    11 of 13    to win: Canfield and Pyramid"),
        (1, "Every game    1 of 13     to win: Spider, Spiderette and 10 more"),
        (13, "Every game    2026-09-20  a win in every game"),
    ],
)
def test_the_games_left_to_win_are_named_as_far_as_they_fit(tui, won, row):
    write_history(*(played(key) for key in engine.GAME_ORDER[:won]))
    assert row in page_of(tui(["s", ENTER, "z"]).frames[2])


def test_seven_dailies_says_when_it_was_earned(tui):
    days = [f"2026-09-{d:02}" for d in range(1, 8)]
    write_history(*(played(day=day, daily=day) for day in days), played(hints=0, undos=0))
    lines = page_of(tui(["s", ENTER, "z"]).frames[2])
    assert "Seven dailies 2026-09-07  a daily won seven days in a row" in lines
    assert "Clean win     2026-09-20  a win with no hint and no undo" in lines


@pytest.mark.parametrize(
    "back",
    [[ESC, -1], ["q"], [ENTER], ["z"], [curses.KEY_DOWN], [curses.KEY_UP]],
    ids=["Esc", "q", "Enter", "z", "Down", "Up"],
)
def test_any_other_key_goes_back_to_the_statistics_with_the_game_picked(tui, back):
    # Up and Down too, when the page fits and they have nothing to scroll
    scr = tui(["s", curses.KEY_DOWN, ENTER, *back, "z"])
    assert "Spider - records" in scr.frames[3]
    after = 3 + len(back)
    assert "Statistics" in scr.frames[after] and "Spider - records" not in scr.frames[after]
    assert "Spider " in picked(scr, after)
    assert "Score" in scr.frames[after + 1]


def test_left_and_right_go_to_the_records_of_the_games_either_side(tui):
    keys = [curses.KEY_RIGHT, "l", curses.KEY_LEFT, "h", "h", curses.KEY_LEFT]
    scr = tui(["s", ENTER, *keys, "q", "z"])
    titles = [
        next(row.strip() for row in frame.split("\n") if row.rstrip().endswith(" - records"))
        for frame in scr.frames[2:9]
    ]
    # round from the first game to the last
    names = ["Klondike", "Spider", "Spiderette", "Spider", "Klondike", "Pyramid", "Canfield"]
    assert titles == [f"{name} - records" for name in names]
    # and back to the statistics with the game last shown picked
    assert "Canfield " in picked(scr, 9)


def test_the_records_and_the_daily_list_agree_on_the_dailies(tui, on_the_day):
    for day in [19, 20, 21, 23, 24]:
        played_daily("golf", True, day=date(2026, 9, day))
    played_daily("klondike", False)
    listed = tui([Mouse(DAILY_DEAL, 8), ESC, -1], start_key=None).frames[1]
    assert listed.split("\n")[2] == "    Daily streak: 2 days (longest 3)"
    rows = daily_rows(listed)
    assert rows["golf"].endswith("won in 1:00, 40 moves")
    assert rows["klondike"].endswith("played, not won yet")
    golf, klondike = (
        page_of(tui(["s", ENTER, "q", "z"], start_key=key).frames[2])
        for key in ("golf", "klondike")
    )
    seven = "Seven dailies 3 of 7      the longest run of days with a daily won"
    assert seven in golf and seven in klondike
    assert any(line.startswith("Played        5 since") and line.endswith("won 5") for line in golf)
    assert any(
        line.startswith("Played        1 since") and line.endswith("won 0") for line in klondike
    )


def test_p_and_y_on_the_statistics_and_the_records_only_go_back(tui, sent):
    # they're keys of the board, so they neither pause nor copy from here
    scr = tui(["s", ENTER, "p", "y", "p", "z"])
    assert "Klondike - records" in scr.frames[2]
    assert "Statistics" in scr.frames[3] and "Klondike - records" not in scr.frames[3]
    assert "Score" in scr.frames[4] and "Game paused" not in scr.frames[4]
    assert "Game paused" in scr.frames[5]
    assert sent() == b""
    assert not any("copy" in said for said in scr.uis[0].said if said)


def test_a_click_on_the_row_already_picked_opens_its_records(tui):
    # Klondike's row is picked to start with, and Spider's is under it
    scr = tui(["s", Mouse(5, 20), "q", Mouse(6, 20), Mouse(6, 20), "q", "z"])
    assert "Klondike - records" in scr.frames[2]
    # a click on another row only picks it
    assert "Spider " in picked(scr, 4) and "Statistics" in scr.frames[4]
    assert "Spider - records" in scr.frames[5]
    assert "Spider " in picked(scr, 6)


def test_a_double_click_on_a_row_opens_its_records(tui):
    # which, with the double-click left to the game, is two presses
    press = curses.BUTTON1_PRESSED
    scr = tui(["s", Mouse(7, 20, press), Again(press), "q", "z"])
    assert "Spiderette - records" in scr.frames[3]


def test_the_mouse_leaves_the_records_up(tui):
    a_full_history()
    scr = tui(
        [
            "s",
            ENTER,
            Mouse(9, 9, curses.REPORT_MOUSE_POSITION),
            Mouse(9, 9, curses.BUTTON1_RELEASED),
            Mouse(9, 9),
            Mouse(9, 9, WHEEL_DOWN),
            Resize(30, 100),
            "z",
        ]
    )
    assert all(page_of(frame) == FULL_RECORDS for frame in scr.frames[2:8])
    assert len(scr.frames[7].split("\n")) == 30
    assert "Statistics" in scr.frames[8]


def test_the_statistics_read_the_history_once_for_every_records_page(tui, monkeypatch):
    a_full_history()
    real, reads = history.games, []

    def counting():
        reads.append(1)
        return real()

    def count_from_here():
        monkeypatch.setattr(history, "games", counting)

    def stop_counting():
        monkeypatch.setattr(history, "games", real)

    keys = [ENTER, curses.KEY_RIGHT, Resize(30, 100), curses.KEY_LEFT, "q", curses.KEY_DOWN]
    scr = tui([Meanwhile(count_from_here, "s"), *keys, ENTER, "q", Meanwhile(stop_counting, "z")])
    assert "Spider - records" in scr.frames[3] and "Spider - records" in scr.frames[8]
    assert len(reads) == 1


@pytest.mark.parametrize("skin", [False, True], ids=["plain", "code-skin"])
def test_the_widest_records_fit_their_columns_at_80_columns(tui, skin):
    if skin:
        code_skin_on()
    multiplier = {"scoring": "multiplier"}
    most = {"seconds": 99999 * 60 + 59, "moves": 99999, "deal": 2147483647}
    write_history(
        played("triplepeaks", day="2026-12-31", options=multiplier, score=99999, **most),
        played("triplepeaks", "lost", day="2026-12-30", score=99998),
    )
    frame = tui(["s", ENTER, "z"], start_key="triplepeaks", h=24, w=80).frames[2]
    lines = page_of(frame, CODE_GUTTER if skin else 0)
    assert lines[6:13] == [
        "                  Time  Moves  Deal                       Date",
        "Fastest win   99999:59  99999  triplepeaks:sm:2147483647  2026-12-31",
        "                               scoring multiplier",
        "Fewest moves  99999:59  99999  triplepeaks:sm:2147483647  2026-12-31",
        "                               scoring multiplier",
        "",
        "Best score    99998            scoring standard           2026-12-30",
    ]
    assert lines[13] == "              99999            scoring multiplier         2026-12-31"
    assert max(map(len, lines)) == 68


def test_a_long_name_fits_on_its_records_page(tui):
    code_skin_on()
    write_history(played("fortythieves", "lost", score=999))
    scr = tui(["s", curses.KEY_UP, curses.KEY_UP, curses.KEY_UP, ENTER, "z"], h=24, w=80)
    frame = scr.frames[5]
    assert "Forty Thieves - records" in frame
    assert "Best score    999 of 1000      fortythieves:7" in frame


def test_the_records_fit_80x24_and_scroll_to_every_line_at_80x16(tui):
    code_skin_on()
    a_full_history()
    frame = tui(["s", ENTER, "z"], h=24, w=80).frames[2]
    assert "more below" not in frame and RECORDS_FOOTER in frame and "Up/Down" not in frame
    downs = [curses.KEY_DOWN] * 10
    scr = tui(["s", ENTER, *downs, curses.KEY_HOME, "z"], h=16, w=80)
    shown = scr.frames[2:14]
    assert all(f"Up/Down scroll - {RECORDS_FOOTER}" in frame for frame in shown)
    assert "more below" in shown[0] and "more above" not in shown[0]
    assert all(any(line in frame for frame in shown) for line in FULL_RECORDS if line)
    assert FULL_RECORDS[-1] in shown[-2] and "more below" not in shown[-2]
    assert shown[-1] == shown[0]
    # and a key that doesn't scroll it goes back
    assert "Statistics" in scr.frames[14]


def test_the_records_of_the_last_of_many_games_fit_80x24(tui, many_games):
    code_skin_on()
    a_full_history()
    last = engine.GAMES[many_games[-1]].name
    scr = tui(["s", curses.KEY_END, ENTER, curses.KEY_RIGHT, "q", "z"], h=24, w=80)
    lines = page_of(scr.frames[3], CODE_GUTTER)
    assert f"{last} - records" in scr.frames[3] and "Terminal too small" not in scr.frames[3]
    left = "to win: Spiderette, Eight Off and 31 more"
    assert f"Every game    4 of {len(many_games)}     {left}" in lines
    assert max(map(len, lines)) <= 68
    # and round to the first game
    assert page_of(scr.frames[4], CODE_GUTTER) == FULL_RECORDS[:-2] + lines[-2:]


def test_the_wheel_scrolls_the_records_where_they_are_too_long(tui):
    a_full_history()
    wheel = [Mouse(9, 30, WHEEL_DOWN), Mouse(9, 30, WHEEL_UP)]
    scr = tui(["s", ENTER, *wheel, "z"], h=16, w=80)
    top, down, up = scr.frames[2:5]
    assert "more above" not in top and "more above" in down
    assert up == top


def test_the_records_read_without_colour_and_in_plain_characters(tui):
    a_full_history()
    for kwargs in ({"color": False}, {"color_capable": False}):
        frame = tui(["s", ENTER, "z"], **kwargs).frames[2]
        assert page_of(frame) == FULL_RECORDS
        assert frame.isascii()


def test_the_statistics_say_enter_opens_the_records(tui):
    code_skin_on()
    frame = tui(["s", "z"], h=24, w=80).frames[1]
    assert "Up/Down move - Enter records - Press any other key to continue." in frame


def test_the_help_screen_lists_the_toggles(tui):
    scr = tui(["?", "z"])
    assert "toggle colour" in scr.frames[1]
    assert "next theme" in scr.frames[1]
    assert "four-colour deck" in scr.frames[1]
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
    ("Game paused", "klondike", None, ["p"]),
    ("Klondike - options", "klondike", None, ["o"]),
    ("count as lost", "klondike", None, ["d", "o", curses.KEY_RIGHT, ENTER]),
    ("YOU WIN", "klondike", near_won, ["a"]),
    ("No moves left", "golf", one_move_left, ["f"]),
    ("Play a deal", "klondike", None, ["g"]),
    ("A number on its own plays", None, None, [Mouse(PLAY_A_DEAL, 8)]),
    ("Daily deals for", None, None, [Mouse(DAILY_DEAL, 8)]),
    ("Fastest win", "klondike", None, [Meanwhile(a_full_history, "s"), ENTER]),
    ("No games of Klondike played here yet", "klondike", None, ["s", ENTER]),
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


@pytest.mark.parametrize("skin", [False, True], ids=["plain", "code-skin"])
@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_every_screen_fits_80x24(tui, screen, start_key, game, keys, skin):
    if skin:
        code_skin_on()
    scr = tui(keys + OUT, start_key=start_key, game=game and game(), h=24, w=80)
    shown = scr.frames[len(keys)]
    assert screen in shown and "Terminal too small" not in shown
    if screen in ("choose a game", "Statistics", "Daily deals for"):
        # every game has its row, with none of them scrolled out of view
        assert all(cls.name in shown for cls in engine.GAMES.values())
        assert "more above" not in shown and "more below" not in shown
    if screen in ("choose a game", "Statistics"):
        # and whatever comes under them fits too
        assert ("Quit" if start_key is None else "Press any other key") in shown


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


# config.json as the player left it by hand while the game was running,
# with a key only a newer version knows
HAND_EDITED = {"sync_aisleriot": False, "symbols": False, "future_key": {"on": True}}


def edit_config_by_hand():
    os.makedirs(store.config_dir(), exist_ok=True)
    with open(store.config_path(), "w", encoding="utf-8") as fh:
        json.dump(HAND_EDITED, fh)


def config_on_disk():
    with open(store.config_path(), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize(
    "keys, saved",
    [
        (["v"], "color"),
        (["t"], "theme"),
        (["4"], "four_color"),
        (["c"], "code_skin"),
        (["x"], "view"),
        (["b", "\t", "z"], "camo_theme"),
        (["o", curses.KEY_RIGHT, ENTER], "options"),
    ],
)
def test_a_setting_saves_its_own_key_and_leaves_a_hand_edit_alone(tui, keys, saved):
    tui([Meanwhile(edit_config_by_hand, keys[0]), *keys[1:], "q"])
    on_disk = config_on_disk()
    assert set(on_disk) == {*HAND_EDITED, saved}
    assert {key: on_disk[key] for key in HAND_EDITED} == HAND_EDITED


def test_a_hand_edit_on_the_menu_survives_the_game_it_starts(tui):
    # the README says to turn sharing off by hand; starting a game used to
    # save the settings as they were at start over it, and turn it back on
    tui([Meanwhile(edit_config_by_hand, ENTER), "q"], start_key=None)
    assert config_on_disk() == {**HAND_EDITED, "last_game": "klondike"}
    assert store.load_config()["sync_aisleriot"] is False


def test_new_options_leave_another_games_options_alone(tui):
    def spider_options_by_hand():
        cfg = store.load_config()
        store.set_game_options(cfg, "spider", {"suits": 2})
        store.save_config(cfg)

    tui([Meanwhile(spider_options_by_hand, "o"), curses.KEY_RIGHT, ENTER, "q"])
    cfg = store.load_config()
    assert store.game_options(cfg, "spider") == {"suits": 2}
    assert store.game_options(cfg, "klondike")["draw"] == 3


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


# The rows the screens that scroll take with three rows of what scrolls,
# the fewest they scroll it in
SCROLLED_MIN = {
    "choose a game": 14,
    "Daily deals for": 9,
    "Statistics": 10,
    "Soliterm - controls": 7,
    "Fastest win": 7,
    "No games of Klondike played here yet": 7,
}
# the screens of lines to read, whose footers say when they scroll
READERS = ("Soliterm - controls", "Fastest win", "No games of Klondike played here yet")


@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_a_screen_too_tall_for_the_terminal_says_so(tui, screen, start_key, game, keys):
    # rather than lose its last lines off the bottom, or scroll its list
    # in fewer rows than that
    scr = tui(keys + [Resize(40, 120), *OUT], start_key=start_key, game=game and game())
    rows = scr.frames[len(keys)].rstrip().split("\n")
    need = SCROLLED_MIN.get(screen, len(rows))
    scr = tui(
        keys + [Resize(need - 1, 120), Resize(need, 120), *OUT],
        start_key=start_key,
        game=game and game(),
    )
    small, roomy = scr.frames[len(keys) + 1 : len(keys) + 3]
    assert "Terminal too small" in small and f"needs 40x{need}" in small
    assert screen not in small
    shown = roomy.rstrip().split("\n")
    # down to the footer, which on the help says now that it scrolls
    footer = rows[-1]
    if screen in READERS:
        footer = f"    Up/Down scroll - {footer.lstrip()}"
    assert len(shown) == need and shown[-1] == footer


def test_keys_the_player_cannot_see_do_nothing_on_a_small_menu(tui):
    # Enter here would start whichever game is highlighted
    scr = tui([ENTER, curses.KEY_DOWN, ENTER, "q"], start_key=None, h=12)
    assert "Terminal too small" in scr.frames[0]
    assert scr.uis == []
    assert scr.rc == 0


# -- lists of games longer than the terminal ------------------------------------------------


WHEEL_UP = curses.BUTTON4_PRESSED
# Python before 3.10 has no BUTTON5 constants, and this is ncurses 6's
WHEEL_DOWN = getattr(curses, "BUTTON5_PRESSED", 0x200000)
MENU_MOVES = [curses.KEY_UP] * 4  # from the first game round to Daily deal

# The screens with a row for every game: the line that says which it is,
# the game to start (None for the menu), the keys to get there, and the
# lines that stay in view however far the list scrolls.
LONG_LISTS = [
    (
        "choose a game",
        None,
        [],
        ["solitaire for your terminal", "Daily deal", "Play a deal", "View statistics", "Quit"]
        + ["Up/Down move - Enter select - mouse click - q quit"],
    ),
    (
        "Daily deals for",
        None,
        [*MENU_MOVES, ENTER],
        [
            "Daily streak: none yet, win a daily to start one",
            "Up/Down move - Enter play - Esc back",
        ],
    ),
    (
        "Statistics",
        "klondike",
        ["s"],
        ["Wins / Total / Percentage", "(shared with GNOME AisleRiot - sol)", "Streak Longest"]
        + ["Enter records - Press any other key"],
    ),
]


def stub_game(n):
    """A game with not much more than a name, for the lists of games."""

    class Stub(GameDef):
        key = f"stub{n:02}"
        name = f"Stub {n:02}"
        blurb = short_blurb = "Stands in for a game to come."

        def deal(self, g):
            g.reset_slots()
            g.make_deck()
            g.shuffle()
            for _ in range(4):
                g.deal_from_deck(g.add_slot("tableau", "down"), 1, face_up=True)

    return Stub


def add_games(monkeypatch, n):
    """n more games after the real ones, everywhere the games are listed.
    Returns the keys of them all, in order."""
    stubs = [stub_game(i) for i in range(1, n + 1)]
    for cls in stubs:
        monkeypatch.setitem(engine.GAMES, cls.key, cls)
    real = engine.GAME_ORDER
    order = [*real, *(cls.key for cls in stubs)]
    # every module that holds the list under its own name
    for name, module in list(sys.modules.items()):
        if name.startswith("soliterm") and getattr(module, "GAME_ORDER", None) is real:
            monkeypatch.setattr(module, "GAME_ORDER", order)
    return order


@pytest.fixture
def many_games(monkeypatch):
    """24 more games after the real ones. Returns the keys of them all."""
    return add_games(monkeypatch, 24)


@pytest.fixture(params=["the-games-at-80x16", "24-more-at-80x24"])
def crowd(request, monkeypatch):
    """The keys of the games, in order, and the rows of a terminal too
    short to list them all at once: the games there are in one a few rows
    short, or 24 more of them in one of the usual size."""
    if request.param == "the-games-at-80x16":
        return engine.GAME_ORDER, 16
    return add_games(monkeypatch, 24), 24


def picked(scr, i):
    """What was drawn in the cursor's colours when key i was read."""
    return " | ".join(scr.cursor_rows[i].values())


def row_of(frame, name):
    """The row of frame that has the game `name` on it."""
    (row,) = [y for y, line in enumerate(frame.split("\n")) if f"{name:<16}" in line]
    return row


@pytest.mark.parametrize("skin", [False, True], ids=["plain", "code-skin"])
@pytest.mark.parametrize(
    "down, up",
    [
        (curses.KEY_DOWN, "k"),
        ("j", curses.KEY_UP),
        (Mouse(12, 30, WHEEL_DOWN), Mouse(12, 30, WHEEL_UP)),
    ],
    ids=["arrows", "letters", "wheel"],
)
@pytest.mark.parametrize("screen, start_key, keys, fixed", LONG_LISTS)
def test_a_long_list_reaches_every_game(
    tui, crowd, keyfile, skin, down, up, screen, start_key, keys, fixed
):
    keyfile("")
    if skin:
        code_skin_on()
    order, h = crowd
    names = [engine.GAMES[key].name for key in order]
    walk = [down] * (len(names) - 1) + [up] * (len(names) - 1)
    scr = tui(keys + walk + OUT, start_key=start_key, h=h, w=80)
    # down to the last game and back up to the first, each in view and
    # picked out in turn, and the rest of the screen staying put
    for i, name in enumerate(names + names[-2::-1]):
        at = len(keys) + i
        frame = scr.frames[at]
        assert screen in frame and "Terminal too small" not in frame
        assert all(line in frame for line in fixed), (at, frame)
        assert name in picked(scr, at), (name, frame)
        rows = frame.split("\n")
        assert len(rows) == h
        if skin:
            # the list is inside the comment with the rest of the screen
            listed = [row for row in rows if "more" in row or any(n in row for n in names)]
            assert listed and all(re.match(r" *\d+  # ", row) for row in listed)


@pytest.mark.parametrize("screen, start_key, keys, fixed", LONG_LISTS)
def test_the_wheel_stops_at_the_ends_of_a_list(tui, crowd, screen, start_key, keys, fixed):
    order, h = crowd
    first, last = engine.GAMES[order[0]].name, engine.GAMES[order[-1]].name
    rows = len(order)
    if screen == "choose a game":
        # the pick goes on past the games to Quit
        last, rows = "Quit", rows + 4
    # a notch more each way than it takes to get to the other end
    down, up = Mouse(9, 30, WHEEL_DOWN), Mouse(9, 30, WHEEL_UP)
    scr = tui(keys + [down] * rows + [up] * rows + OUT, start_key=start_key, h=h, w=80)
    at = len(keys)
    assert first in picked(scr, at)
    assert last in picked(scr, at + rows - 1) and last in picked(scr, at + rows)
    assert first in picked(scr, at + 2 * rows - 1) and first in picked(scr, at + 2 * rows)


@pytest.mark.parametrize("screen, start_key, keys, fixed", LONG_LISTS)
def test_the_page_keys_turn_a_long_list_a_page_at_a_time(
    tui, crowd, screen, start_key, keys, fixed
):
    order, h = crowd
    names = [engine.GAMES[key].name for key in order]
    last = "Quit" if screen == "choose a game" else names[-1]
    pages = [curses.KEY_NPAGE] * 6 + [curses.KEY_PPAGE] * 6
    ends = [curses.KEY_END, curses.KEY_HOME]
    scr = tui(keys + pages + ends + OUT, start_key=start_key, h=h, w=80)
    at = len(keys)

    def in_view(i):
        return [name for name in names if f"{name:<16}" in scr.frames[i]]

    # the pick goes to the first game that was below the ones in view, and
    # the list turns the page with it, as far as it goes
    below = names[names.index(in_view(at)[-1]) + 1]
    assert below in picked(scr, at + 1)
    turned = in_view(at + 1)
    assert turned[0] == below or turned[-1] == names[-1]
    # and so on down to the end, with every game in view on the way, and
    # back up to the start
    assert last in picked(scr, at + 6)
    assert {name for i in range(at, at + 7) for name in in_view(i)} == set(names)
    assert names[0] in picked(scr, at + 12)
    # End and Home go straight to the ends
    assert last in picked(scr, at + 13)
    assert names[0] in picked(scr, at + 14)


@pytest.mark.parametrize("skin", [False, True], ids=["plain", "code-skin"])
@pytest.mark.parametrize("screen, start_key, keys, fixed", LONG_LISTS)
def test_a_click_on_a_scrolled_list_takes_the_row_under_the_pointer(
    tui, crowd, on_the_day, skin, screen, start_key, keys, fixed
):
    if skin:
        code_skin_on()
    order, h = crowd
    first, target, end = (engine.GAMES[key].name for key in (order[0], order[-4], order[-1]))
    # down to the last game, which scrolls the list, then a click on one
    # a few rows above it
    downs = [curses.KEY_DOWN] * (len(order) - 1)
    frame = tui(keys + downs + OUT, start_key=start_key, h=h, w=80).frames[len(keys + downs)]
    assert f"{end:<16}" in frame and f"{first:<16}" not in frame
    click = Mouse(row_of(frame, target), 30)
    scr = tui(keys + downs + [click, *OUT], start_key=start_key, h=h, w=80)
    if screen == "Statistics":
        assert target in picked(scr, len(keys + downs) + 1)
        assert "Statistics" in scr.frames[len(keys + downs) + 1]
    else:
        g = scr.uis[-1].game
        assert g.gamedef.key == order[-4]
        assert (g.daily == "2026-09-24") == (screen == "Daily deals for")


@pytest.mark.parametrize("screen, start_key, keys, fixed", LONG_LISTS)
def test_a_click_on_more_below_turns_the_page(tui, crowd, screen, start_key, keys, fixed):
    _, h = crowd
    frame = tui(keys + OUT, start_key=start_key, h=h, w=80).frames[len(keys)]
    (row,) = [y for y, line in enumerate(frame.split("\n")) if "more below" in line]
    clicked = tui(keys + [Mouse(row, 30), *OUT], start_key=start_key, h=h, w=80)
    paged = tui(keys + [curses.KEY_NPAGE, *OUT], start_key=start_key, h=h, w=80)
    after = len(keys) + 1
    assert clicked.frames[after] == paged.frames[after] != frame
    assert clicked.cursor_rows[after] == paged.cursor_rows[after]
    assert not clicked.uis or screen == "Statistics"


@pytest.mark.parametrize("screen, start_key, keys, fixed", LONG_LISTS)
def test_the_boss_key_comes_back_to_a_scrolled_list(tui, crowd, screen, start_key, keys, fixed):
    order, h = crowd
    downs = [curses.KEY_DOWN] * (len(order) - 4)
    scr = tui(keys + downs + ["b", "z", *OUT], start_key=start_key, h=h, w=80)
    before, hidden, back = scr.frames[len(keys + downs) : len(keys + downs) + 3]
    assert engine.GAMES[order[-4]].name in picked(scr, len(keys + downs))
    assert screen not in hidden
    assert back == before
    assert scr.cursor_rows[len(keys + downs) + 2] == scr.cursor_rows[len(keys + downs)]


@pytest.mark.parametrize("screen, start_key, keys, fixed", LONG_LISTS)
def test_a_resize_keeps_the_game_picked_in_view(tui, screen, start_key, keys, fixed):
    # to the last game, then a terminal too short for them all, then back
    downs = [curses.KEY_DOWN] * (len(engine.GAME_ORDER) - 1)
    resizes = [Resize(16, 80), Resize(24, 80)]
    scr = tui(keys + downs + resizes + OUT, start_key=start_key, h=24, w=80)
    before, short, tall = scr.frames[len(keys + downs) : len(keys + downs) + 3]
    last = engine.GAMES[engine.GAME_ORDER[-1]].name
    for at, frame in enumerate((before, short, tall), len(keys + downs)):
        assert last in picked(scr, at)
        assert "Terminal too small" not in frame
    assert "Klondike" in before and "Klondike" not in short
    assert tall == before


# how to get to the screens EVERY_SCREEN clicks through to on the menu,
# whose rows move down as the games above them grow
BY_KEYS = {
    "A number on its own plays": [*MENU_MOVES[:3], ENTER],
    "Daily deals for": [*MENU_MOVES, ENTER],
}


@pytest.mark.parametrize("skin", [False, True], ids=["plain", "code-skin"])
@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_every_screen_fits_80x24_with_24_more_games(
    tui, many_games, skin, screen, start_key, game, keys
):
    if skin:
        code_skin_on()
    keys = BY_KEYS.get(screen, keys)
    scr = tui(keys + OUT, start_key=start_key, game=game and game(), h=24, w=80)
    shown = scr.frames[len(keys)]
    assert screen in shown and "Terminal too small" not in shown


def test_the_wheel_is_asked_for(tui):
    scr = tui([])
    assert all(m & WHEEL_UP and m & WHEEL_DOWN for m in scr.masks)


# PDCurses' MOUSE_WHEEL_SCROLL, which the curses module doesn't name.
# Without it windows-curses reports a notch of the wheel with no buttons.
PDC_WHEEL = 0x2000000


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_pdcurses_is_asked_for_the_wheel_its_own_way(tui, monkeypatch, platform):
    # and only PDCurses, as ncurses has BUTTON_CTRL there
    monkeypatch.setattr(sys, "platform", platform)
    scr = tui([])
    assert scr.masks and all(bool(m & PDC_WHEEL) == (platform == "win32") for m in scr.masks)


# -- a help longer than the terminal ------------------------------------------------------


HELP_TITLE = "Soliterm - controls"
HELP_SCROLLS = "Up/Down scroll - Press any key to continue."


@pytest.mark.parametrize("skin", [False, True], ids=["plain", "code-skin"])
@pytest.mark.parametrize(
    "down, up",
    [
        (curses.KEY_DOWN, "k"),
        ("j", curses.KEY_UP),
        (Mouse(9, 30, WHEEL_DOWN), Mouse(9, 30, WHEEL_UP)),
        (curses.KEY_NPAGE, curses.KEY_PPAGE),
    ],
    ids=["arrows", "letters", "wheel", "pages"],
)
def test_a_help_with_ten_keys_more_scrolls_to_every_line(tui, monkeypatch, skin, down, up):
    lines = more_keys(monkeypatch, 10)
    if skin:
        code_skin_on()
    walk = [down] * len(lines) + [up] * len(lines)
    scr = tui(["?", *walk, "z"], h=24, w=80)
    shown = scr.frames[1 : 2 + len(walk)]
    # the title and the footer stay put, and every line comes into view on
    # the way down, the last with nothing more below it
    assert all(HELP_TITLE in frame and HELP_SCROLLS in frame for frame in shown)
    assert all(any(line in frame for frame in shown) for line in lines)
    assert "more below" in shown[0] and "more above" not in shown[0]
    assert lines[-1] in shown[len(lines)] and "more below" not in shown[len(lines)]
    # back up at the top, and then any other key closes it
    assert shown[-1] == shown[0]
    assert HELP_TITLE not in scr.frames[2 + len(walk)]


def test_the_help_scrolls_in_a_terminal_too_short_for_it(tui):
    lines = help_lines()
    scr = tui(["?", curses.KEY_END, curses.KEY_HOME, Resize(24, 80), "z"], h=18, w=80)
    top, end, back, tall = scr.frames[1:5]
    assert "Terminal too small" not in top
    assert lines[0] in top and lines[-1] not in top and "more below" in top
    assert lines[-1] in end and lines[0] not in end and "more above" in end
    assert back == top and HELP_SCROLLS in top
    # a terminal tall enough for it all shows it all, and says any key
    # closes it, as z does
    assert all(line in tall for line in lines)
    assert "Press any key to continue." in tall and "Up/Down" not in tall
    assert "Score" in scr.frames[5]


def test_a_click_on_more_below_turns_the_help_a_page(tui):
    frame = tui(["?", "z"], h=18, w=80).frames[1]
    (row,) = [y for y, line in enumerate(frame.split("\n")) if "more below" in line]
    clicked = tui(["?", Mouse(row, 30), "z"], h=18, w=80).frames[2]
    paged = tui(["?", curses.KEY_NPAGE, "z"], h=18, w=80).frames[2]
    assert clicked == paged != frame


@pytest.mark.parametrize(
    "key", [curses.KEY_DOWN, "j", curses.KEY_NPAGE, curses.KEY_END, Mouse(9, 30, WHEEL_DOWN)]
)
def test_the_keys_that_scroll_it_close_a_help_that_fits(tui, key):
    scr = tui(["?", key, "z"], h=24, w=80)
    assert HELP_TITLE in scr.frames[1]
    if isinstance(key, Mouse):
        # but not the mouse, which leaves it up as ever
        assert scr.frames[2] == scr.frames[1]
    else:
        assert "Score" in scr.frames[2]


def test_the_boss_key_comes_back_to_the_help_where_it_was_scrolled(tui):
    scr = tui(["?", curses.KEY_NPAGE, "b", "z", "z"], h=18, w=80)
    before, hidden, back = scr.frames[2:5]
    assert "more above" in before
    assert HELP_TITLE not in hidden
    assert back == before


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
    "freecell": (1, True),
    "spider": (1, True),
    "code-skin": (1, False),
    "triple-peaks": (8, True),
    "contrast": (2, True),
}
# the scenes that play their game out and end on the win banner
SCENES_WON = ("hero", "win")


@pytest.mark.skipif(not os.path.exists(SCREENSHOTS), reason="no tools/ in this tree")
def test_screenshot_scenes_still_reach_their_shots(tui):
    # the keys were worked out by hand for each deal, so they go stale the
    # moment a deal number deals another hand
    shots = screenshot_tool()
    scenes = [s for s in shots.SCENES if s.deal]
    assert sorted(s.name for s in scenes) == sorted([*SCENE_MOVES, *SCENES_WON])
    for scene in scenes:
        keys = [TMUX_KEYS.get(k, k) for step in scene.steps for k in step.keys.split()]
        # b and c would hide the board this test reads
        keys = [k for k in keys if k not in ("b", "c")]
        scr = tui(keys, start=scene_start(scene), h=shots.ROWS, w=shots.COLS)
        frames = scr.frames[: len(keys) + 1]
        assert not any("illegal move" in frame for frame in frames), scene.name
        if scene.name in SCENES_WON:
            if "a" in keys:  # the finish was on offer when a took it
                assert soliterm.tui.app.FINISH_OFFER in frames[keys.index("a")], scene.name
            assert "*** YOU WIN! ***" in frames[-1], scene.name
            assert f"share code {scene.deal}" in frames[-1], scene.name
            continue
        moves, hint = SCENE_MOVES[scene.name]
        assert f"Moves {moves} " in frames[-1], scene.name
        assert ("Hint: Move" in frames[-1]) is hint, scene.name
