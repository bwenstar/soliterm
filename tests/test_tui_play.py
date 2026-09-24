"""Drive the real curses loop, soliterm.tui.run(), with scripted keys and clicks.

The curses calls that need a real terminal are stubbed out, and the window is
a FakeScr that plays back a key script and remembers what was on screen each
time the game asked for a key.
"""

import curses
import os
import re
import sys

import pytest

import soliterm.tui
from soliterm import aisleriot as ar
from soliterm import cli, engine, store
from soliterm.engine import Card
from helpers import FakeScr, clear_board, deal

ENTER = "\n"


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


class ScriptedScr(FakeScr):
    def __init__(self, h, w, keys, uis):
        super().__init__(h, w)
        self.keys = list(keys)
        self.uis = uis
        self.frames = []          # the screen each time a key was read
        self.mouse = None
        self.spare = 0
        self.delay = -1           # how long getch waits for a key, in ms; -1 for ever

    def nodelay(self, flag):
        self.delay = 0 if flag else -1

    def timeout(self, ms):
        self.delay = ms

    def getch(self):
        self.frames.append(self.text())
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
            raise k                   # e.g. KeyboardInterrupt, for Ctrl-C
        if isinstance(k, Click):
            cells = sorted(yx for yx, hit in self.uis[-1].hit.items()
                           if hit == (k.sid, k.idx))
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

    Pass game= to start play on a board built by hand. The returned screen
    has .frames, .rc, .uis (every BoardUI made, each with .selections),
    .pairs (init_pair calls), .masks (mousemask calls) and .intervals
    (mouseinterval calls).
    """
    uis, pairs, masks, intervals = [], [], [], []

    class RecordingBoardUI(soliterm.tui.BoardUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.initial_has_color = self.has_color
            self.selections = []      # the selected slot at every draw
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

    def run(keys, start_key="klondike", game=None, seed=None, color=None,
            color_capable=True, h=40, w=120, **kwargs):
        scr = ScriptedScr(h, w, keys, uis)
        monkeypatch.setattr(curses, "mousemask",
                            lambda mask: masks.append(mask) or (mask, 0))
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
        scr.rc = soliterm.tui.run(scr, start_key, seed, color, **kwargs)
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
    g, a, b = board("spider", [up(9, "H"), up(4, "S"), up(3, "S")], [up(5, "H")], suits=4)
    tui([ENTER, curses.KEY_RIGHT, ENTER], start_key="spider", game=g)
    assert names(g, b) == ["5H", "4S", "3S"]


def test_a_klondike_three_drops_off_the_top_of_a_run(tui):
    g, a, b = board("klondike", [up(9, "C"), up(4, "S"), up(3, "H")], [up(4, "C")])
    tui([ENTER, curses.KEY_RIGHT, ENTER], start_key="klondike", game=g)
    assert names(g, b) == ["4C", "3H"]


def test_the_keyboard_can_lift_part_of_a_run_into_an_empty_column(tui):
    g, a, b = board("spider", [up(9, "H"), up(7, "S"), up(6, "S"), up(5, "S")], [],
                    suits=4)
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
    scr = tui(["n", "d", "N"], seed=5)
    assert scr.uis[0].game.serialize() == second


def test_the_terminal_is_not_asked_to_report_pointer_motion(tui):
    scr = tui([])
    assert scr.masks
    assert not any(m & curses.REPORT_MOUSE_POSITION for m in scr.masks)
    assert all(m & curses.BUTTON1_PRESSED for m in scr.masks)


def test_ncurses_does_not_hold_clicks_back_to_wait_for_a_double_click(tui):
    # the play screen spots double-clicks itself
    assert tui([]).intervals == [0]


ESC = 27


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


def test_alt_and_a_key_does_nothing_on_the_menu_or_the_banner(tui):
    # Alt+j would have moved the menu to Spider, Alt+n dealt a new hand
    scr = tui([ESC, "j", ENTER], start_key=None)
    assert scr.uis[0].game.gamedef.key == "klondike"
    scr = tui(["a", ESC, "n", "m"], game=near_won())
    assert "YOU WIN" in scr.frames[-2]
    assert "choose a game" in scr.frames[-1]


def test_the_escape_delay_is_short_unless_the_player_set_one(monkeypatch):
    seen = []
    monkeypatch.setattr(curses, "wrapper",
                        lambda fn, *args: seen.append(os.environ.get("ESCDELAY")) or 0)
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
    monkeypatch.setattr(soliterm.tui, "main", lambda **kw: seen.update(kw) or 0)
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
    for frame in scr.frames[:2]:                  # both views
        assert not any(ch in frame for ch in "┌│▒░♠♥♦♣")
    assert "+------+" in scr.frames[0]
    assert "#" in scr.frames[1]
    assert store.load_config()["symbols"] is True     # the flag is not saved


def test_the_game_names_cards_the_way_the_board_does(tui):
    # a game that can name its cards either way is told which to use
    scr = tui([], symbols=False)
    assert scr.uis[0].game.symbols is False


def test_a_terminal_that_cannot_show_unicode_gets_plain_cards(tui, monkeypatch):
    # LC_ALL=C: curses refuses every string with a box corner or a suit in it,
    # which left the board blank but for the slot names
    monkeypatch.setattr(FakeScr, "encoding", "ascii")
    scr = tui(["x", "q"])
    for frame in scr.frames[:2]:                  # both views
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
    Window.encoding = "latin-1"               # has no box corners
    assert not can_draw_unicode(Window())


# -- a terminal too small for the board -----------------------------------------------

def test_keys_make_no_hidden_moves_while_the_board_does_not_fit(tui):
    scr = tui(["d", "d", ENTER, curses.KEY_RIGHT, ENTER, "a", "n", "o", "m", "q"],
              h=20, w=38)
    assert scr.rc == 0
    assert all("Terminal too small" in frame for frame in scr.frames)
    assert len(scr.uis) == 1 and scr.uis[0].game.moves == 0
    assert store.get_stat("klondike")["total"] == 0


def test_the_board_comes_back_as_it_was_once_the_terminal_grows(tui):
    scr = tui(["d", Resize(40, 120), "q"], h=20, w=38)
    assert "Terminal too small" in scr.frames[1]
    assert "Moves 0" in scr.frames[2] and "Stock: 24" in scr.frames[2]


@pytest.mark.parametrize("key, h, small", [
    ("c", 17, [False, True, False]),    # the code skin needs more rows
    ("x", 15, [True, False, True]),     # and full cards more than compact ones
])
def test_the_skin_and_view_toggles_still_work_on_a_small_terminal(tui, key, h, small):
    # so the toggle that hid the board can bring it back
    scr = tui([key, key, "q"], h=h, w=80)
    assert ["Terminal too small" in frame for frame in scr.frames[:3]] == small


def test_the_boss_key_still_works_on_a_small_terminal(tui):
    scr = tui(["b", "z"], h=20, w=38)
    assert "Terminal too small" not in scr.frames[1]
    assert "Terminal too small" in scr.frames[2]


# -- the clock ---------------------------------------------------------------------

def test_the_clock_runs_from_the_first_move_and_stops_behind_other_screens(tui, game_clock):
    # half a minute looking before the first move, ten seconds of play,
    # then a minute each in the help, the statistics and boss mode
    scr = tui([Later(30, "d"), Later(10, "?"), Later(60, "z"), "s", Later(60, "z"),
               "b", Later(60, "z")])
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


def test_quitting_mid_game_records_a_loss(tui):
    tui(["d", "q"])
    assert store.get_stat("klondike") == {"wins": 0, "total": 1, "best": 0, "worst": 0}


def test_undoing_every_move_still_counts_the_game(tui):
    # AisleRiot counts a game from its first move, however many are taken back
    scr = tui(["d", "d", "d", "u", "u", "u", "q"])
    assert "Moves 0" in scr.frames[-1]
    assert store.get_stat("klondike")["total"] == 1


def test_restarting_the_deal_does_not_count_it(tui):
    # nor does AisleRiot's Restart, which deals the same hand again
    tui(["d", "N", "q"])
    assert store.get_stat("klondike")["total"] == 0


def near_won():
    """Klondike with A-Q home in every suit and the four kings on the tableau."""
    g = deal("klondike", 1)
    fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    for i, suit in enumerate("SHDC"):
        g.slots[fids[i]].cards = [up(r, suit) for r in range(1, 13)]
        g.slots[tids[i]].cards = [up(13, suit)]
    return g


@pytest.mark.parametrize("keys", [["d"], ["d", "b"], ["d", "?"]])
def test_ctrl_c_mid_game_quits_quietly_and_counts_the_loss(tui, keys):
    scr = tui(keys + [KeyboardInterrupt])
    assert scr.rc == 130
    assert store.get_stat("klondike")["total"] == 1


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


def test_playing_again_from_the_menu_does_not_double_aisleriot_stats(tui, keyfile):
    # every return to the menu and every toggle saves the config the TUI
    # loaded at start, which must not undo the one-time merge
    keyfile("[klondike.scm]\nStatistic=10;40;120;900;\n")
    tui(["d", "m", ENTER, "v", "d", "q"])
    assert ar.read_stat("klondike.scm") == {"wins": 10, "total": 42,
                                            "best": 120, "worst": 900}


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
    assert store.get_stat("golf")["total"] == 1       # counted once, on m


def test_the_no_moves_banner_counts_the_game_it_ends(tui):
    # the loss is only recorded on leaving the banner, but the numbers on it
    # should already be what the statistics will say
    scr = tui(["f", "m"], start_key="golf", game=one_move_left())
    assert "Wins/Total  : 0/1  (0%)" in scr.frames[1]
    assert store.get_stat("golf")["total"] == 1


@pytest.mark.parametrize("k", ["s", "n", "m", KeyboardInterrupt])
def test_a_game_with_no_moves_left_counts_once_the_player_gives_it_up(tui, k):
    tui(["f", k], start_key="golf", game=one_move_left())
    assert store.get_stat("golf") == {"wins": 0, "total": 1, "best": 0, "worst": 0}


def test_a_win_after_taking_back_the_dead_end_counts_as_a_win(tui):
    # 4D first leaves the 6C and 5S stuck; 6C, 5S, 4D clears the board
    g = deal("golf", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[g.ids_of("waste")[0]].cards = [up(5, "H")]
    g.slots[t[0]].cards = [up(4, "D")]
    g.slots[t[1]].cards = [up(5, "S"), up(6, "C")]
    scr = tui(["f", "u", curses.KEY_RIGHT, "f", "f", curses.KEY_LEFT, "f", "m", "q"],
              start_key="golf", game=g)
    assert "No moves left" in scr.frames[1]
    assert "YOU WIN" in scr.frames[7]
    assert store.get_stat("golf")["wins"] == 1
    assert store.get_stat("golf")["total"] == 1


# the banner's choices sit on rows 12-14 from column 6, marker included
BANNER_ROW = {"same": 12, "new": 13, "menu": 14}


def test_the_banner_ignores_the_pointer_the_wheel_and_other_buttons(tui):
    new = BANNER_ROW["new"]
    scr = tui(["a",
               Mouse(new, 8, curses.REPORT_MOUSE_POSITION),
               Mouse(BANNER_ROW["same"], 8, curses.BUTTON4_PRESSED),
               Mouse(BANNER_ROW["menu"], 8, curses.BUTTON3_PRESSED),
               Mouse(new, 8, curses.BUTTON1_RELEASED),
               Mouse(new, 40, curses.BUTTON1_CLICKED),     # right of the label
               "m"], game=near_won())
    assert all("YOU WIN" in frame for frame in scr.frames[1:7])
    assert "choose a game" in scr.frames[7]
    assert len(scr.uis) == 1


@pytest.mark.parametrize("bstate", [curses.BUTTON1_CLICKED, curses.BUTTON1_PRESSED])
def test_a_left_click_on_a_banner_choice_takes_it(tui, bstate):
    scr = tui(["a", Mouse(BANNER_ROW["new"], 8, bstate)], game=near_won())
    assert "YOU WIN" in scr.frames[1]
    assert "new deal" in scr.frames[2]


# -- options -------------------------------------------------------------------------

KING_TO_EMPTY = [ENTER] + [curses.KEY_RIGHT] * 4 + [ENTER]    # a first move on near_won()


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
    assert store.get_stat("klondike")["total"] == 1       # from the q


def test_new_options_mid_game_ask_before_dealing_again(tui):
    scr = tui(["d", "o", curses.KEY_RIGHT, ENTER, "n",
               "o", curses.KEY_RIGHT, ENTER, "y"])
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
    assert store.get_stat("klondike")["total"] == 1       # from the q


def test_new_options_before_a_move_just_deal_again(tui):
    scr = tui(["o", curses.KEY_RIGHT, ENTER])
    assert not any("count as lost" in frame for frame in scr.frames)
    assert len(scr.uis) == 2 and scr.uis[1].game.options["draw"] == 3
    assert store.get_stat("klondike")["total"] == 0


def test_a_game_without_options_says_so_and_plays_on(tui):
    scr = tui(["d", "o"], start_key="golf")
    assert "Golf has no options" in scr.frames[-1]
    assert len(scr.uis) == 1 and "Moves 1" in scr.frames[-1]


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
    klondike = 4        # the first game on the menu
    scr = tui([Mouse(klondike, 8, curses.BUTTON1_PRESSED),
               Mouse(klondike, 8, curses.BUTTON1_RELEASED), "q"], start_key=None)
    assert scr.uis[0].hit_test(klondike, 8) is not None
    assert "Moves 0" in scr.frames[2]
    assert scr.uis[0].selections[-1] is None
    assert store.get_stat("klondike")["total"] == 0


def test_the_release_of_the_click_on_the_banner_does_nothing_on_the_new_deal(tui):
    new = BANNER_ROW["new"]
    scr = tui(["a", Mouse(new, 12, curses.BUTTON1_PRESSED),
               Mouse(new, 12, curses.BUTTON1_RELEASED)], game=near_won())
    ui = scr.uis[0]
    assert ui.hit_test(new, 12) is not None
    assert "new deal" in scr.frames[3]
    assert ui.selections[-1] is None


def test_the_menu_starts_the_chosen_game_and_remembers_it(tui):
    scr = tui([curses.KEY_DOWN, ENTER, "m", "q"], start_key=None)
    assert scr.rc == 0
    assert [ui.game.gamedef.key for ui in scr.uis] == ["spider"]
    assert store.load_config()["last_game"] == "spider"


# -- colour --------------------------------------------------------------------------------

@pytest.mark.parametrize("saved, flag, no_color, shown", [
    (True, False, False, False),     # --no-color beats the saved choice
    (True, None, True, False),       # and so does NO_COLOR
    (False, True, True, True),       # --color beats both
    (False, None, False, False),     # with neither, the saved choice holds
    (None, None, False, True),       # and with nothing saved, the terminal's
])
def test_colour_goes_by_the_flag_then_no_color_then_the_saved_choice(
        tui, monkeypatch, saved, flag, no_color, shown):
    if saved is not None:
        cfg = store.load_config()
        cfg["color"] = saved
        store.save_config(cfg)
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    scr = tui([], color=flag)
    assert scr.uis[0].initial_has_color is shown
    assert store.load_config().get("color") == saved     # only v saves it


def test_the_tui_hears_whether_a_colour_flag_was_given(monkeypatch):
    seen = {}
    monkeypatch.setattr(soliterm.tui, "main", lambda **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_terminal_problem", lambda: None)
    for argv, color in ([], None), (["--color"], True), (["--no-color"], False):
        cli.main(["--game", "klondike"] + argv)
        assert seen["color"] is color


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
    assert bg != -1 and fg != bg


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


@pytest.mark.parametrize("key, title", [("?", "Soliterm - controls"),
                                        ("s", "Statistics")])
def test_help_and_stats_stay_up_until_a_key_is_pressed(tui, key, title):
    scr = tui([key,
               Mouse(9, 9, curses.REPORT_MOUSE_POSITION),
               Mouse(9, 9, curses.BUTTON1_RELEASED),
               Mouse(9, 9, curses.BUTTON4_PRESSED),
               Resize(30, 100),
               "z"])
    assert all(title in frame for frame in scr.frames[1:6])
    assert "Score" in scr.frames[6]
    # drawn again after the resize
    assert len(scr.frames[5].split("\n")) == 30


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
]


@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_the_boss_key_works_on_every_screen_and_comes_back_to_it(
        tui, screen, start_key, game, keys):
    scr = tui(keys + ["b", "z"], start_key=start_key, game=game and game())
    shown, hidden, back = scr.frames[len(keys):len(keys) + 3]
    assert screen in shown
    assert hidden.strip() and screen not in hidden and "Score" not in hidden
    assert screen in back


def test_only_a_key_ends_boss_mode_not_the_mouse_or_a_resize(tui):
    scr = tui(["b",
               Mouse(9, 40, curses.REPORT_MOUSE_POSITION),
               Mouse(9, 40, curses.BUTTON4_PRESSED),
               Mouse(9, 40, curses.BUTTON1_PRESSED),     # clicking to focus the window
               Resize(30, 100),
               "z"])
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
    tui(["c"])      # the saved skin comes back on, and c turns it off
    assert store.load_config()["code_skin"] is False


def code_skin_on():
    cfg = store.load_config()
    cfg["code_skin"] = True
    store.save_config(cfg)


@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_the_code_skin_keeps_every_screen_inside_the_code_file(
        tui, screen, start_key, game, keys):
    code_skin_on()
    scr = tui(keys, start_key=start_key, game=game and game())
    rows = scr.frames[len(keys)].split("\n")
    assert "solver.py" in rows[0]
    # a line number down every row, and the screen written as a comment
    assert all(re.match(r" *\d+\b", row) for row in rows[1:-1])
    shown = [row for row in rows if screen in row]
    assert shown and all(re.match(r" *\d+  # ", row) for row in shown)


def test_the_code_skin_keeps_the_too_small_notice_inside_the_code_file(tui):
    code_skin_on()
    scr = tui([], h=17, w=80)
    rows = scr.frames[0].split("\n")
    assert "solver.py" in rows[0]
    shown = [row for row in rows if "Terminal too small" in row or "needs" in row]
    assert len(shown) == 2 and all(re.match(r" *\d+  # ", row) for row in shown)


@pytest.mark.parametrize("screen, start_key, game, keys", EVERY_SCREEN)
def test_a_screen_too_tall_for_the_terminal_says_so(tui, screen, start_key, game, keys):
    # rather than lose its last lines off the bottom
    scr = tui(keys + [Resize(40, 120)], start_key=start_key, game=game and game())
    rows = scr.frames[len(keys)].rstrip().split("\n")
    need = len(rows)
    scr = tui(keys + [Resize(need - 1, 120), Resize(need, 120)],
              start_key=start_key, game=game and game())
    small, roomy = scr.frames[len(keys) + 1:len(keys) + 3]
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
