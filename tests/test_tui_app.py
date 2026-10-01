"""Drive soliterm.tui.app.App directly: no curses setup, just a fake window.

App keeps the play screen's state in plain attributes and handles every key
or click in a method of its own, so a test can set up a game, press keys one
at a time and look at the board, the selection and the message in between.
"""

import curses
import json
from pathlib import Path

import pytest

import soliterm.tui.app
from soliterm import history, saves, store
from soliterm.deals import Deal
from soliterm.engine import Card, Solitaire
from soliterm.tui import cascade
from soliterm.tui.app import MENU, QUIT, START_MESSAGE, App
from soliterm.tui.screens import WHEEL_DOWN

from helpers import FakeScr, clear_board, deal, steps

ENTER = 10


class KeyScr(FakeScr):
    """A FakeScr that plays back a list of keys, then reads -1 (no key)."""

    def __init__(self, keys=(), h=40, w=120):
        super().__init__(h, w)
        self.keys = list(keys)
        self.frames = []  # the screen each time a key was read

    def nodelay(self, flag):
        pass

    def getch(self):
        self.frames.append(self.text())
        if not self.keys:
            return -1
        k = self.keys.pop(0)
        return ord(k) if isinstance(k, str) else k


def up(rank, suit):
    return Card(rank, suit, True)


def klondike_app(first, second, keys=(), scr=None, **settings):
    """An App playing Klondike with only the first two columns dealt."""
    app = App(scr or KeyScr(keys), **settings)
    app.start_game("klondike")
    t = app.game.ids_of("tableau")
    for sid in t:
        app.game.slots[sid].cards = []
    app.game.slots[t[0]].cards = first
    app.game.slots[t[1]].cards = second
    return app, t[0], t[1]


def press(app, *keys):
    """Press keys on the play screen, drawing a frame before each like play() does."""
    outcome = None
    for k in keys:
        app.game.update_status()
        app.draw()
        outcome = app.handle_key(ord(k) if isinstance(k, str) else k)
    return outcome


def names(app, sid):
    return [str(c) for c in app.game.cards(sid)]


def cell_of(app, sid, idx):
    cells = sorted(yx for yx, hit in app.ui.hit.items() if hit == (sid, idx))
    assert cells, f"card {idx} of slot {sid} is not on screen"
    return cells[0]


def test_the_offer_never_shows_after_a_win():
    app, _a, _b = klondike_app([up(13, "S")], [up(13, "H")])
    fids = app.game.ids_of("foundation")
    for f, suit in zip(fids, "SHDC"):
        app.game.slots[f].cards = [up(r, suit) for r in range(1, 14 if suit in "DC" else 13)]
    app.game.slots[0].cards = app.game.slots[1].cards = []  # the stock and the waste
    press(app, "u")  # every card can go up, but only a move brings the offer
    assert app.message == "nothing to undo"
    press(app, ENTER, curses.KEY_RIGHT, curses.KEY_RIGHT, ENTER)
    assert app.message == soliterm.tui.app.FINISH_OFFER
    press(app, "a")
    assert app.game.is_won()
    assert app.message == "autoplayed 2"


def test_animation_off_in_config_or_by_flag(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    assert App(FakeScr()).animation is True
    assert App(FakeScr(), animation=False).animation is False
    store.save_config({**store.load_config(), "animation": False})
    assert App(FakeScr()).animation is False
    assert App(FakeScr(), animation=True).animation is True  # the caller's word goes
    # a dumb terminal can't move a card without drawing the screen again
    monkeypatch.setenv("TERM", "dumb")
    assert App(FakeScr(), animation=True).animation is False


def cascade_app(monkeypatch, scr, number=None):
    """An App that has just won Klondike, deal `number` if given, with the
    cards free to fly."""
    monkeypatch.setenv("TERM", "xterm")
    app = App(scr, animation=True)
    app.start_game("klondike", Deal("klondike", number))
    clear_board(app.game)
    for f, suit in zip(app.game.ids_of("foundation"), "SHDC"):
        app.game.slots[f].cards = [up(r, suit) for r in range(1, 14)]
    app.draw()
    return app


def test_the_cascade_draws_the_cards_down_the_board(monkeypatch):
    scr = KeyScr()
    app = cascade_app(monkeypatch, scr)
    before = scr.text().split("\n")
    app.win_cascade()
    after = scr.text().split("\n")
    # below the empty columns, where nothing was, the trails build up
    assert not any(row.strip() for row in before[14:36])
    trails = [row for row in after[14:36] if row.strip()]
    assert len(trails) > 10 and any(set(row) & set("♠♥♦♣") for row in trails)
    assert 1 < len(scr.frames) <= cascade.MAX_FRAMES


def test_the_cascade_follows_the_deal_number(monkeypatch):
    screens = []
    for number in (5, 5, 6):
        app = cascade_app(monkeypatch, KeyScr(), number)
        app.win_cascade()
        screens.append(app.stdscr.text())
    assert screens[0] == screens[1] != screens[2]


def test_no_cascade_when_the_board_does_not_fit(monkeypatch):
    scr = KeyScr()
    app = cascade_app(monkeypatch, scr)
    monkeypatch.setattr(app.ui, "fits", lambda: False)
    app.win_cascade()
    assert scr.frames == []


def test_an_app_needs_no_terminal_to_start_a_game():
    app = App(FakeScr())
    app.start_game("spider")
    assert app.game.gamedef.key == "spider"
    assert app.cursor == app.game.ids_of("tableau")[0]
    assert not app.has_color
    app.draw()
    assert "Soliterm  -  Spider" in app.stdscr.text()
    assert store.load_config()["last_game"] == "spider"


def steps_app():
    """An App playing Steps: a face-down card over two face-up ones."""
    app = App(KeyScr(w=80))
    app.game = steps()
    app.ui = app.new_board()
    app.cursor = app.first_cursor()
    return app, app.game.ids_of("tableau")


def test_the_cursor_starts_on_a_face_up_card():
    app, (_top, left, _right) = steps_app()
    assert app.cursor == left
    app.start_game("klondike")
    assert app.cursor == app.game.ids_of("tableau")[0]


def test_the_cursor_skips_an_empty_placed_slot():
    app, (top, left, right) = steps_app()
    app.game.slots[left].cards = []
    app.cursor = right
    press(app, curses.KEY_LEFT)
    assert app.cursor == top
    press(app, curses.KEY_DOWN)
    assert app.cursor == right


def test_the_cursor_leaves_a_slot_that_empties():
    app, (top, left, right) = steps_app()
    app.cursor = left
    app.draw()
    app.game.slots[left].cards = []  # as a card played from it would
    app.draw()
    # the face-down card is nearer, but the face-up one can be picked up
    assert app.cursor == right
    app.game.slots[left].cards = [up(5, "H")]
    app.draw()
    assert app.cursor == right
    app.game.slots[right].cards = []
    app.game.slots[left].cards = []
    app.draw()
    assert app.cursor == top  # the only card left


def board_on(key, w=80, tall=False):
    """An App on deal 5 of `key` at 24 rows, drawn; with `tall`, a first
    column long enough that the title gives its row up to the cards."""
    app = App(KeyScr(h=24, w=w))
    app.start_game(key, Deal(key, 5))
    if tall:
        column = [Card(1, "C", False)] * 5 + [up(r, "SH"[r % 2]) for r in range(13, 0, -1)]
        app.game.slots[app.game.ids_of("tableau")[0]].cards = column + [up(13, "C")]
    app.draw()
    return app, "".join(app.stdscr.grid[24 - 3])


# Spider's status leaves room for the deal at 80 columns; Klondike's needs 81
@pytest.mark.parametrize("key, w", [("spider", 80), ("klondike", 81)])
def test_the_status_row_names_the_deal_when_the_title_gives_way(key, w):
    app, status = board_on(key, w, tall=True)
    assert app.ui._top <= 1
    assert "Soliterm" not in app.stdscr.text()
    assert status.endswith("   Deal 5  ")
    assert status.startswith("  Score 0 ")


def test_the_status_row_leaves_the_deal_out_while_the_title_shows_it():
    app, status = board_on("spider")
    assert "Soliterm  -  Spider  -  Deal 5" in app.stdscr.text()
    assert "Deal" not in status


@pytest.mark.parametrize("key", ["klondike", "canfield"])
def test_the_status_row_leaves_the_deal_out_when_it_would_not_fit(key):
    app, status = board_on(key, tall=True)
    assert app.ui._top <= 1
    assert "Deal" not in status
    # the game's own status is what matters
    assert app.game.status in status


def test_the_code_skin_status_names_the_deal():
    cfg = store.load_config()
    cfg["code_skin"] = True
    store.save_config(cfg)
    _app, status = board_on("klondike")
    assert "  # score=0 moves=0 t=0:00 deal=5  Stock: 24" in status


def test_main_hands_curses_wrapper_its_settings_by_name(monkeypatch):
    monkeypatch.setenv("ESCDELAY", "25")  # main sets it if it isn't there
    calls = []

    def wrapper(fn, *args, **kwargs):
        calls.append((fn, args, kwargs))
        return 0

    monkeypatch.setattr(curses, "wrapper", wrapper)
    assert soliterm.tui.app.main(Deal("klondike", 3), color=False, symbols=True) == 0
    [(fn, args, kwargs)] = calls
    assert fn is soliterm.tui.app.run
    assert args == (Deal("klondike", 3),)
    assert kwargs == {"color": False, "symbols": True}


def test_a_game_key_to_start_on_becomes_a_deal():
    assert App(FakeScr(), "golf").start == Deal("golf")
    assert App(FakeScr(), Deal("golf", 5)).start == Deal("golf", 5)
    assert App(FakeScr()).start is None


def test_a_short_session_moves_undoes_hints_and_quits():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")], keys=["z"])
    assert app.cursor == a

    press(app, curses.KEY_RIGHT)
    assert app.cursor == b
    press(app, ENTER)
    assert (app.selected, app.selected_n) == (b, 1)
    press(app, curses.KEY_LEFT, ENTER)
    assert names(app, a) == ["5H", "4S"] and names(app, b) == []
    assert app.selected is None and app.message == ""

    press(app, "u")
    assert names(app, a) == ["5H"] and names(app, b) == ["4S"]
    press(app, "u")
    assert app.message == "nothing to undo"
    press(app, "r")
    assert names(app, a) == ["5H", "4S"]

    src, _dst, desc = app.game.hint()
    press(app, "h")
    assert app.message == f"Hint: {desc}"
    assert app.cursor == src and app.hint is not None
    press(app, curses.KEY_DOWN)
    assert app.hint is None

    assert press(app, "?") is None
    assert "Soliterm - controls" in app.stdscr.frames[-1]
    assert app.stdscr.keys == []  # the help took the "z"

    assert press(app, "q") == QUIT
    assert store.get_stat("klondike")["total"] == 0
    assert "klondike" in saves.waiting()


def test_esc_drops_the_selection_and_the_hint():
    app, _a, _b = klondike_app([up(5, "H")], [up(4, "S")])
    press(app, ENTER, "h", 27)
    assert app.selected is None and app.hint is None and app.message == ""


class AttrScr(KeyScr):
    """A KeyScr that also keeps the attribute every cell was drawn with."""

    def erase(self):
        super().erase()
        self.attrs = {}

    def addnstr(self, y, x, text, n, attr=0):
        super().addnstr(y, x, text, n, attr)
        for i in range(min(len(text), n)):
            self.attrs[(y, x + i)] = attr


def test_a_hint_marks_every_card_it_would_move():
    # the cursor jumps to the top one, so marking just that showed nothing
    run = [up(8, "H"), up(7, "S"), up(6, "H")]
    app, a, b = klondike_app([Card(2, "C", False)] + run, [up(9, "C")], scr=AttrScr())
    press(app, "h")
    app.draw()
    assert app.hint[:2] == (a, b)
    marked = {
        idx
        for yx, (sid, idx) in app.ui.hit.items()
        if sid == a and app.stdscr.attrs[yx] & curses.A_UNDERLINE
    }
    assert marked == {1, 2}
    assert app.stdscr.attrs[cell_of(app, a, 3)] & curses.A_BOLD


def yukon_app(*columns):
    """An App playing Yukon with only the first few columns dealt."""
    app = App(KeyScr())
    app.start_game("yukon")
    clear_board(app.game)
    t = app.game.ids_of("tableau")
    for sid, cards in zip(t, columns):
        app.game.slots[sid].cards = list(cards)
    return app, t


# Yukon lifts any face-up cards, and the 8S alone or 8C to 8S both go on
# the 9H: the hint moves the one card, and Enter lifts all four
EIGHTS = [up(8, "C"), up(7, "H"), up(6, "C"), up(8, "S")]


def test_following_a_hint_with_the_keys_makes_the_move_it_names():
    app, (a, b, *_) = yukon_app(EIGHTS, [up(9, "H")])
    assert app.game.hint_move() == (a, b, 1)
    press(app, "h", ENTER)
    assert (app.selected, app.selected_n) == (a, 4)
    press(app, curses.KEY_RIGHT, ENTER)
    assert names(app, a) == ["8C", "7H", "6C"]
    assert names(app, b) == ["9H", "8S"]


def test_the_lift_keys_still_say_how_many_cards_follow_a_hint():
    app, (a, b, *_) = yukon_app(EIGHTS, [up(9, "H")])
    press(app, "h", ENTER, "-", "+", curses.KEY_RIGHT, ENTER)
    assert names(app, a) == []
    assert names(app, b) == ["9H", "8C", "7H", "6C", "8S"]


def test_a_drop_the_hint_did_not_name_lifts_the_longest_run():
    app, (a, b, c, *_) = yukon_app(EIGHTS, [up(9, "H")], [up(9, "D")])
    assert app.game.hint_move() == (a, b, 1)
    press(app, "h", ENTER, curses.KEY_RIGHT, curses.KEY_RIGHT, ENTER)
    assert names(app, c) == ["9D", "8C", "7H", "6C", "8S"]


def test_a_hint_is_followed_once_and_not_again_after_an_undo():
    app, (a, b, *_) = yukon_app(EIGHTS, [up(9, "H")])
    press(app, "h", ENTER, curses.KEY_RIGHT, ENTER, "u")
    assert names(app, a) == [str(c) for c in EIGHTS]
    press(app, curses.KEY_LEFT, ENTER, curses.KEY_RIGHT, ENTER)
    assert names(app, b) == ["9H", "8C", "7H", "6C", "8S"]


def test_a_hint_with_nothing_to_suggest_says_what_the_game_says(monkeypatch):
    # the game knows whether dealing or undoing could still help
    monkeypatch.setattr(Solitaire, "no_hint_reason", lambda self: "nothing helps")
    app, _a, _b = klondike_app([up(13, "S")], [up(13, "H")])
    for sid in app.game.ids_of("stock") + app.game.ids_of("waste"):
        app.game.slots[sid].cards = []
    assert app.game.hint() is None
    press(app, "h")
    assert app.message == "nothing helps"


def test_the_dialogs_take_a_click_off_the_queue(monkeypatch):
    # left there, ncurses hands it to the next getmouse on the board
    taken = []
    monkeypatch.setattr(curses, "getmouse", lambda: taken.append(1) or (0, 1, 1, 0, 0))
    app = App(KeyScr([curses.KEY_MOUSE, "n", curses.KEY_MOUSE, ENTER]))
    assert app.confirm("Give up this game?") is False
    assert app.options_screen("klondike", {}) is not None
    assert len(taken) == 2


def test_an_illegal_drop_says_so_and_changes_nothing():
    app, _a, _b = klondike_app([up(5, "H")], [up(4, "H")])
    before = app.game.serialize()
    press(app, ENTER, curses.KEY_RIGHT, ENTER)
    assert app.message == "illegal move: 5♥ doesn't go on 4♥, which takes a black 3"
    assert app.game.serialize() == before


def test_the_full_screen_game_says_why_about_the_selection():
    app, _a, _b = klondike_app([up(8, "S"), up(7, "H")], [up(5, "D")])
    press(app, ENTER, curses.KEY_RIGHT, ENTER)
    assert app.message == "illegal move: 8♠ doesn't go on 5♦, which takes a black 4"
    press(app, curses.KEY_LEFT, ENTER, "-", curses.KEY_RIGHT, ENTER)
    assert app.message == "illegal move: 7♥ doesn't go on 5♦, which takes a black 4"


def test_the_reason_names_cards_in_letters_with_ascii():
    app, _a, _b = klondike_app([up(8, "S")], [up(5, "D")], symbols=False)
    press(app, ENTER, curses.KEY_RIGHT, ENTER)
    assert app.message == "illegal move: 8S doesn't go on 5D, which takes a black 4"


def test_keys_the_play_screen_does_not_use_do_nothing():
    app, a, _b = klondike_app([up(5, "H")], [up(4, "S")])
    before = app.game.serialize()
    for k in (-1, ord("z"), ord("Z"), curses.KEY_RESIZE):
        assert press(app, k) is None
    assert app.game.serialize() == before
    assert app.cursor == a and app.selected is None


def test_clicks_pick_up_and_drop():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
    app.draw()
    y, x = cell_of(app, b, 0)
    app.mouse_at(y, x, curses.BUTTON1_CLICKED)
    assert app.cursor == b and app.selected == b
    y, x = cell_of(app, a, 0)
    app.mouse_at(y, x, curses.BUTTON1_CLICKED)
    assert names(app, a) == ["5H", "4S"]
    assert app.selected is None


def test_a_click_off_the_cards_is_ignored():
    app, a, _b = klondike_app([up(5, "H")], [up(4, "S")])
    app.draw()
    assert app.ui.hit_test(0, 0) is None
    app.mouse_at(0, 0, curses.BUTTON1_CLICKED)
    assert app.cursor == a and app.selected is None


def test_double_clicking_an_ace_sends_it_home():
    app, a, _b = klondike_app([up(1, "S")], [up(4, "S")])
    app.draw()
    y, x = cell_of(app, a, 0)
    app.mouse_at(y, x, curses.BUTTON1_DOUBLE_CLICKED)
    assert names(app, a) == []
    assert any(names(app, f) == ["AS"] for f in app.game.ids_of("foundation"))


def test_play_goes_back_to_the_menu_or_quits():
    app = App(KeyScr(["d", "m"]))
    assert app.play("klondike") is False
    assert store.get_stat("klondike")["total"] == 0
    assert "klondike" in saves.waiting()
    app = App(KeyScr(["q"]))
    assert app.play("golf") is True
    assert store.get_stat("golf")["total"] == 0


def test_count_records_the_game_once_and_returns_its_stats_and_line():
    app = App(KeyScr())
    app.start_game("golf")
    press(app, "d")  # the game is under way
    stat, line = app.count(True, 42)
    assert stat == {"wins": 1, "total": 1, "best": 42, "worst": 42}
    assert history.games() == [line]
    assert app.recorded
    app.give_up()  # already counted, so nothing more
    assert store.get_stat("golf") == stat
    assert history.games() == [line]


def test_menu_and_quit_hand_back_what_to_do_next():
    app, _a, _b = klondike_app([up(5, "H")], [up(4, "S")])
    assert press(app, "m") == MENU
    assert press(app, "Q") == QUIT


def test_moving_the_mouse_or_the_wheel_leaves_the_cursor_and_hint_alone():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
    press(app, "h")
    cursor, hint = app.cursor, app.hint
    assert hint is not None and cursor == b
    y, x = cell_of(app, a, 0)
    for bstate in (curses.REPORT_MOUSE_POSITION, curses.BUTTON4_PRESSED, curses.BUTTON3_PRESSED):
        app.mouse_at(y, x, bstate)
    assert (app.cursor, app.hint, app.selected) == (cursor, hint, None)


def slow_click(app, sid, idx):
    """Press and, a while later, release the left button over one card."""
    y, x = cell_of(app, sid, idx)
    app.mouse_at(y, x, curses.BUTTON1_PRESSED)
    app.draw()
    app.mouse_at(y, x, curses.BUTTON1_RELEASED)
    app.draw()


def test_a_slow_click_picks_a_card_up_and_keeps_it():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
    app.draw()
    slow_click(app, b, 0)
    assert app.selected == b
    slow_click(app, a, 0)
    assert names(app, a) == ["5H", "4S"]
    assert app.selected is None


def test_a_slow_click_on_the_stock_deals_once():
    app = App(KeyScr())
    app.start_game("klondike")
    app.draw()
    stock = app.game.ids_of("stock")[0]
    slow_click(app, stock, len(app.game.cards(stock)) - 1)
    assert app.game.moves == 1


def test_dragging_a_card_onto_a_target_moves_it():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
    app.draw()
    y, x = cell_of(app, b, 0)
    app.mouse_at(y, x, curses.BUTTON1_PRESSED)
    y, x = cell_of(app, a, 0)
    app.mouse_at(y, x, curses.BUTTON1_RELEASED)
    assert names(app, a) == ["5H", "4S"]
    assert app.selected is None and app.cursor == a


def double_click_board(monkeypatch):
    """An ace to send home, and a clock the test moves on by hand."""
    app, a, _b = klondike_app([up(1, "S")], [up(4, "S")])
    now = [100.0]
    monkeypatch.setattr(soliterm.tui.app, "clock", lambda: now[0])
    app.draw()
    return app, a, now


def test_two_clicks_in_quick_succession_are_a_double_click(monkeypatch):
    app, a, now = double_click_board(monkeypatch)
    slow_click(app, a, 0)
    assert app.selected == a
    now[0] += 0.3
    slow_click(app, a, 0)
    assert names(app, a) == []
    assert any(names(app, f) == ["AS"] for f in app.game.ids_of("foundation"))
    assert app.selected is None


def test_two_clicks_far_apart_pick_up_and_put_down(monkeypatch):
    app, a, now = double_click_board(monkeypatch)
    slow_click(app, a, 0)
    now[0] += 0.6
    slow_click(app, a, 0)
    assert names(app, a) == ["AS"]
    assert app.selected is None


def test_a_click_just_after_a_drag_is_not_a_double_click(monkeypatch):
    # the press that began the drag was not the first half of one
    app, a, b = klondike_app([up(1, "H"), up(4, "S")], [up(5, "H")])
    now = [100.0]
    monkeypatch.setattr(soliterm.tui.app, "clock", lambda: now[0])
    app.draw()
    app.mouse_at(*cell_of(app, a, 1), curses.BUTTON1_PRESSED)
    app.mouse_at(*cell_of(app, b, 0), curses.BUTTON1_RELEASED)
    assert names(app, b) == ["5H", "4S"]
    app.draw()
    now[0] += 0.3
    slow_click(app, a, 0)
    assert names(app, a) == ["AH"] and app.selected == a


def test_plus_and_minus_change_how_many_cards_are_held():
    app, a, _b = klondike_app([up(9, "C"), up(8, "H"), up(7, "S")], [up(4, "S")])
    press(app, "-")
    assert app.selected is None and "pick up" in app.message
    press(app, ENTER)
    assert (app.selected, app.selected_n) == (a, 3)
    press(app, "-")
    assert app.selected_n == 2 and app.message == "holding 2 cards from 8♥"
    press(app, "-")
    assert app.selected_n == 1 and app.message == "holding 7♠"
    press(app, "-")
    assert app.selected_n == 1 and "fewer" in app.message
    press(app, "+", "+")
    assert app.selected_n == 3
    press(app, "+")
    assert app.selected_n == 3 and "more" in app.message
    assert app.selected_exact


@pytest.mark.parametrize("code_skin", [False, True])
def test_the_first_game_starts_with_the_note_it_was_handed(code_skin):
    # as the command line hands it the terminal type it plays as
    note = "TERM=xterm-kitty isn't known here, so playing as xterm-256color"
    store.save_config(dict(store.load_config(), code_skin=code_skin))
    app = App(FakeScr(24, 80), note=note)
    app.start_game("klondike")
    assert app.message == note
    app.draw()
    assert note in app.stdscr.text()
    app.start_game("golf")  # once is enough
    assert app.message == START_MESSAGE


# -- all a first game has to say -------------------------------------------------------

TERM_NOTE = "TERM=xterm-kitty isn't known here, so playing as xterm-256color"
UNREADABLE = "Your saved game couldn't be read, so this is a new deal."


def with_everything_to_say(monkeypatch, code_skin=False):
    """An App about to start its first game with all there can be to say:
    AisleRiot open, a damaged config set aside as the command line read it,
    a saved Klondike game the menu offered that turns out unreadable, and a
    terminal type played as another."""
    told = [store.AISLERIOT_OPEN]
    monkeypatch.setattr(store, "aisleriot_open_note", lambda: told.pop() if told else None)
    config = Path(store.config_path())
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("{not json")
    store.save_config(dict(store.load_config(), code_skin=code_skin))
    g = deal("klondike", 4)
    g.deal()
    assert saves.keep(g, 42)
    path = Path(saves.save_path("klondike"))
    save = json.loads(path.read_text())
    # a card too many in the waste, which only taking it up finds
    save["position"] = save["position"].replace("\ns1|waste|none|0|", "\ns1|waste|none|0|1SU,")
    path.write_text(json.dumps(save))
    app = App(FakeScr(24, 80), note=TERM_NOTE)
    app.waiting = saves.waiting()
    return app


def message_lines(app, key=curses.KEY_RIGHT):
    """What the message line says as the game starts, then after each key
    until it stops changing, each checked to be on the screen in full."""
    said = [app.message]
    for _ in range(20):
        app.draw()
        assert said[-1] in app.stdscr.text()
        press(app, key)
        if app.message == said[-1]:
            return said
        said.append(app.message)
    raise AssertionError(f"the message line never settles: {said}")


def unspaced(notes):
    """Notes without their spaces, to hold up against what the message line
    said, where a word too long for a line is split without one."""
    return [note.replace(" ", "") for note in notes]


def put_together(said):
    """The notes the message line said, with the ones too long for a line
    in one piece again, unspaced."""
    notes = [said[0]]
    for line in said[1:]:
        if notes[-1].endswith(" ..."):
            notes[-1] = notes[-1][: -len(" ...")] + line
        else:
            notes.append(line)
    return unspaced(notes)


@pytest.mark.parametrize("code_skin", [False, True])
def test_the_first_game_says_all_it_has_to_a_key_at_a_time(monkeypatch, code_skin):
    app = with_everything_to_say(monkeypatch, code_skin)
    app.start_game("klondike")
    config_notice, save_notice = store.notices()
    assert "config.json was damaged" in config_notice
    assert "klondike.json was damaged" in save_notice
    said = message_lines(app)
    # each fits the message line at 80 columns, code skin and all
    assert all(len(line) <= 72 for line in said)
    # AisleRiot, which can still lose games, first, then this game, then
    # what went wrong with the files, and last how the terminal plays
    assert put_together(said) == unspaced(
        [store.AISLERIOT_OPEN, UNREADABLE, config_notice, save_notice, TERM_NOTE]
    )
    app.start_game("golf")  # the next game has only its own to say
    assert message_lines(app) == [START_MESSAGE]


def test_a_key_with_something_to_say_holds_the_next_note_back(monkeypatch):
    app = with_everything_to_say(monkeypatch)
    app.start_game("klondike")
    first = app.message
    press(app, "u")
    assert app.message == "nothing to undo"
    said = message_lines(app)
    assert said[0] == "nothing to undo"
    notes = put_together([first, *said[1:]])
    assert notes == unspaced([store.AISLERIOT_OPEN, UNREADABLE, *store.notices(), TERM_NOTE])
    assert said[-1] == TERM_NOTE


def test_notes_not_seen_before_the_menu_come_with_the_next_game(monkeypatch):
    app = with_everything_to_say(monkeypatch)
    app.start_game("klondike")
    assert app.message == store.AISLERIOT_OPEN
    assert press(app, "m") == MENU
    app.start_game("golf")
    said = message_lines(app)
    assert said[0] == START_MESSAGE
    assert put_together(said[1:]) == unspaced([UNREADABLE, *store.notices(), TERM_NOTE])


def test_a_resize_leaves_the_note_on_the_line(monkeypatch):
    # the terminal changing size is none of the player's doing, and that
    # AisleRiot is open is said only once a run
    app = with_everything_to_say(monkeypatch)
    app.start_game("klondike")
    press(app, curses.KEY_RESIZE, curses.KEY_RESIZE, curses.KEY_RESIZE)
    assert app.message == store.AISLERIOT_OPEN


def mouse(app, monkeypatch, *events):
    """Have the mouse do each (y, x, bstate) of events in turn, with a
    frame drawn before each."""
    events = list(events)

    def getmouse():
        y, x, bstate = events.pop(0)
        return 0, x, y, 0, bstate

    monkeypatch.setattr(curses, "getmouse", getmouse)
    press(app, *[curses.KEY_MOUSE] * len(events))


def test_only_a_left_click_moves_the_notes_on_and_once_a_click(monkeypatch):
    app = with_everything_to_say(monkeypatch)
    app.start_game("klondike")
    app.draw()
    y, x = cell_of(app, app.game.ids_of("tableau")[0], 0)
    others = [
        curses.REPORT_MOUSE_POSITION,
        curses.BUTTON4_PRESSED,
        WHEEL_DOWN,
        curses.BUTTON3_PRESSED,
        curses.BUTTON3_RELEASED,
    ]
    mouse(app, monkeypatch, *[(y, x, bstate) for bstate in others])
    assert app.message == store.AISLERIOT_OPEN
    # waiting for no clicks, ncurses gives one as a press and a release
    mouse(app, monkeypatch, (y, x, curses.BUTTON1_PRESSED), (y, x, curses.BUTTON1_RELEASED))
    assert app.message == UNREADABLE


def test_a_click_with_nothing_to_say_moves_the_notes_on_once(monkeypatch):
    app = with_everything_to_say(monkeypatch)
    app.start_game("klondike")
    notes = [app.message, *app.notes]
    app.draw()
    assert app.ui.hit_test(0, 0) is None  # no card there to pick up
    # a press and its release, then the clicks ncurses and PDCurses can
    # give as one event
    mouse(app, monkeypatch, (0, 0, curses.BUTTON1_PRESSED), (0, 0, curses.BUTTON1_RELEASED))
    assert app.message == notes[1]
    mouse(app, monkeypatch, (0, 0, curses.BUTTON1_CLICKED))
    assert app.message == notes[2]
    mouse(app, monkeypatch, (0, 0, curses.BUTTON1_DOUBLE_CLICKED))
    assert app.message == notes[3]

    # and one curses couldn't read is no click, whatever came before it
    def unreadable():
        raise curses.error("getmouse() returned ERR")

    monkeypatch.setattr(curses, "getmouse", unreadable)
    press(app, curses.KEY_MOUSE)
    assert app.message == notes[3]


def test_a_drag_that_moves_cards_moves_the_notes_on_as_keys_would(monkeypatch):
    app = with_everything_to_say(monkeypatch)
    app.start_game("klondike")
    t = app.game.ids_of("tableau")
    app.game.slots[t[0]].cards = [up(5, "H")]
    app.game.slots[t[1]].cards = [up(6, "S")]
    app.draw()
    mouse(
        app,
        monkeypatch,
        (*cell_of(app, t[0], 0), curses.BUTTON1_PRESSED),
        (*cell_of(app, t[1], 0), curses.BUTTON1_RELEASED),
    )
    assert names(app, t[1]) == ["6S", "5H"]
    # the press picked the card up and letting go put it down, as two
    # presses of Enter would, with no word on either
    assert app.message == soliterm.tui.app.note_pages(store.notices()[0])[0]


def test_a_click_on_a_terminal_too_small_for_the_board_leaves_the_note(monkeypatch):
    # with no room for the board there's no message line either, so the
    # note on it hasn't been read yet
    app = with_everything_to_say(monkeypatch)
    app.stdscr.h, app.stdscr.w = 10, 30
    app.start_game("klondike")
    app.draw()
    assert "Terminal too small" in app.stdscr.text()
    mouse(app, monkeypatch, (3, 3, curses.BUTTON1_PRESSED), (3, 3, curses.BUTTON1_RELEASED))
    app.stdscr.h, app.stdscr.w = 24, 80
    app.stdscr.erase()
    press(app, curses.KEY_RESIZE)
    app.draw()
    assert app.message == store.AISLERIOT_OPEN
    assert store.AISLERIOT_OPEN in app.stdscr.text()


def test_a_note_too_long_for_a_line_goes_over_more_than_one():
    note = "can't read " + "/very/long" * 12 + "/stats.json (Permission denied), so it is left"
    pages = soliterm.tui.app.note_pages(note)
    assert len(pages) > 1
    assert all(len(page) <= 72 for page in pages)
    assert all(page.endswith(" ...") for page in pages[:-1])
    assert not pages[-1].endswith(" ...")
    assert put_together(pages) == unspaced([note])
    assert soliterm.tui.app.note_pages(store.AISLERIOT_OPEN) == [store.AISLERIOT_OPEN]


# three lines' worth, for the hint to say when it has nothing to suggest
LONG = "no move clearly helps from here, " * 5 + "so undo"


@pytest.fixture
def long_no_hint(monkeypatch):
    monkeypatch.setattr(Solitaire, "hint", lambda self: None)
    monkeypatch.setattr(Solitaire, "no_hint_reason", lambda self: LONG)
    pages = soliterm.tui.app.note_pages(LONG)
    assert len(pages) == 3
    return pages


def test_a_message_too_long_for_the_line_goes_a_piece_a_key_ahead_of_the_notes(
    monkeypatch, long_no_hint
):
    app = with_everything_to_say(monkeypatch)
    app.start_game("klondike")
    first = app.message
    press(app, "h")
    app.draw()
    said = message_lines(app)
    assert said[:3] == long_no_hint
    # the notes the hint came in front of follow it
    assert put_together([first, *said[3:]]) == unspaced(
        [store.AISLERIOT_OPEN, UNREADABLE, *store.notices(), TERM_NOTE]
    )


def test_the_rest_of_a_long_message_goes_once_a_key_says_something_else(long_no_hint):
    app = App(FakeScr(24, 80))
    app.start_game("klondike")
    press(app, "h")
    app.draw()
    assert app.message == long_no_hint[0]
    press(app, "u", curses.KEY_RIGHT)
    assert app.message == "nothing to undo"
    # and h again says it from the start
    press(app, "h")
    app.draw()
    assert app.message == long_no_hint[0]
    press(app, curses.KEY_RIGHT)
    assert app.message == long_no_hint[1]
