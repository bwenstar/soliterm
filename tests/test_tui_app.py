"""Drive soliterm.tui.app.App directly: no curses setup, just a fake window.

App keeps the play screen's state in plain attributes and handles every key
or click in a method of its own, so a test can set up a game, press keys one
at a time and look at the board, the selection and the message in between.
"""

import curses

import soliterm.tui.app
from soliterm import store
from soliterm.engine import Card, Solitaire
from soliterm.tui.app import MENU, QUIT, App
from helpers import FakeScr

ENTER = 10


class KeyScr(FakeScr):
    """A FakeScr that plays back a list of keys, then reads -1 (no key)."""

    def __init__(self, keys=(), h=40, w=120):
        super().__init__(h, w)
        self.keys = list(keys)
        self.frames = []          # the screen each time a key was read

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


def klondike_app(first, second, keys=(), scr=None):
    """An App playing Klondike with only the first two columns dealt."""
    app = App(scr or KeyScr(keys))
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


def test_an_app_needs_no_terminal_to_start_a_game():
    app = App(FakeScr())
    app.start_game("spider")
    assert app.game.gamedef.key == "spider"
    assert app.cursor == app.game.ids_of("tableau")[0]
    assert not app.has_color
    app.draw()
    assert "Soliterm  -  Spider" in app.stdscr.text()
    assert store.load_config()["last_game"] == "spider"


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
    assert app.stdscr.keys == []          # the help took the "z"

    assert press(app, "q") == QUIT
    assert store.get_stat("klondike")["total"] == 1


def test_esc_drops_the_selection_and_the_hint():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
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
    marked = {idx for yx, (sid, idx) in app.ui.hit.items()
              if sid == a and app.stdscr.attrs[yx] & curses.A_UNDERLINE}
    assert marked == {1, 2}
    assert app.stdscr.attrs[cell_of(app, a, 3)] & curses.A_BOLD


def test_a_hint_with_nothing_to_suggest_says_what_the_game_says(monkeypatch):
    # the game knows whether dealing or undoing could still help
    monkeypatch.setattr(Solitaire, "no_hint_reason", lambda self: "nothing helps")
    app, a, b = klondike_app([up(13, "S")], [up(13, "H")])
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
    app, a, b = klondike_app([up(5, "H")], [up(4, "H")])
    before = app.game.serialize()
    press(app, ENTER, curses.KEY_RIGHT, ENTER)
    assert app.message == "illegal move"
    assert app.game.serialize() == before


def test_keys_the_play_screen_does_not_use_do_nothing():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
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
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
    app.draw()
    assert app.ui.hit_test(0, 0) is None
    app.mouse_at(0, 0, curses.BUTTON1_CLICKED)
    assert app.cursor == a and app.selected is None


def test_double_clicking_an_ace_sends_it_home():
    app, a, b = klondike_app([up(1, "S")], [up(4, "S")])
    app.draw()
    y, x = cell_of(app, a, 0)
    app.mouse_at(y, x, curses.BUTTON1_DOUBLE_CLICKED)
    assert names(app, a) == []
    assert any(names(app, f) == ["AS"] for f in app.game.ids_of("foundation"))


def test_play_goes_back_to_the_menu_or_quits():
    app = App(KeyScr(["d", "m"]))
    assert app.play("klondike") is False
    assert store.get_stat("klondike")["total"] == 1
    app = App(KeyScr(["q"]))
    assert app.play("golf") is True
    assert store.get_stat("golf")["total"] == 0


def test_menu_and_quit_hand_back_what_to_do_next():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
    assert press(app, "m") == MENU
    assert press(app, "Q") == QUIT


def test_moving_the_mouse_or_the_wheel_leaves_the_cursor_and_hint_alone():
    app, a, b = klondike_app([up(5, "H")], [up(4, "S")])
    press(app, "h")
    cursor, hint = app.cursor, app.hint
    assert hint is not None and cursor == b
    y, x = cell_of(app, a, 0)
    for bstate in (curses.REPORT_MOUSE_POSITION, curses.BUTTON4_PRESSED,
                   curses.BUTTON3_PRESSED):
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
    app, a, b = klondike_app([up(1, "S")], [up(4, "S")])
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
    app, a, b = klondike_app([up(9, "C"), up(8, "H"), up(7, "S")], [up(4, "S")])
    press(app, "-")
    assert app.selected is None and "pick up" in app.message
    press(app, ENTER)
    assert (app.selected, app.selected_n) == (a, 3)
    press(app, "-")
    assert app.selected_n == 2 and app.message == "holding 2 cards"
    press(app, "-", "-")
    assert app.selected_n == 1 and "fewer" in app.message
    press(app, "+", "+")
    assert app.selected_n == 3
    press(app, "+")
    assert app.selected_n == 3 and "more" in app.message
    assert app.selected_exact
