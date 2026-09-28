"""KEYMAP is the one list of play-screen keys: the dispatch and the help
screen both come from it, so these checks keep the two honest."""

import curses
import inspect
import re
from types import SimpleNamespace

import pytest

from soliterm.tui import keys
from soliterm.tui.app import App
from soliterm.tui.board import CODE_GUTTER

from helpers import PDCURSES_NUMPAD, FakeScr

# how a label names the keys that are not a plain character
NAMES = {
    curses.KEY_UP: "Arrow",
    curses.KEY_DOWN: "Arrow",
    curses.KEY_LEFT: "Arrow",
    curses.KEY_RIGHT: "Arrow",
    curses.KEY_ENTER: "Enter",
    10: "Enter",
    13: "Enter",
    ord(" "): "Space",
    27: "Esc",
    ord("\t"): "Tab",
    curses.KEY_F2: "F2",
    curses.KEY_MOUSE: "Mouse",
}


def help_screen(code_skin=False):
    scr = FakeScr(24, 80)
    scr.getch = lambda: ord(" ")  # the key that closes it
    app = App(scr)
    app.cfg["code_skin"] = code_skin
    app.help_screen()
    return scr.text()


@pytest.mark.parametrize("mode", ["play", "boss"])
def test_no_key_is_bound_twice_on_a_screen(mode):
    seen = {}
    for b in keys.KEYMAP:
        if b.mode != mode:
            continue
        for k in b.actions:
            assert k not in seen, f"key {k} is in both {seen[k]!r} and {b.label!r}"
            seen[k] = b.label


def test_every_play_action_has_a_handler_and_every_handler_a_key():
    handlers = {
        name[3:]
        for name, _ in inspect.getmembers(App, inspect.isfunction)
        if name.startswith("do_")
    }
    assert set(keys.PLAY_ACTIONS.values()) == handlers


def test_every_listed_key_is_named_in_its_label():
    for b in keys.KEYMAP:
        if not b.label:
            continue
        words = re.split(r"[\s,/()]+", b.label)
        for k in b.actions:
            name = NAMES.get(k) or chr(k)
            assert name in words or name.lower() in words, (b.label, name)


def test_every_key_a_label_names_is_bound():
    # the other way round, so a label can't name a key that does nothing
    for b in keys.KEYMAP:
        if not b.actions:
            continue  # the double-click, a gesture with no key of its own
        bound = {NAMES.get(k) or chr(k) for k in b.actions}
        for word in re.split(r"[\s,/()]+", b.label):
            if len(word) == 1 or word in NAMES.values():
                assert word in bound, (b.label, word)


def test_no_help_text_ends_in_a_full_stop():
    # they're notes rather than sentences, and read as a list when they
    # all end the same way, here and in docs/keybindings.md
    for b in keys.KEYMAP:
        assert not b.text.endswith("."), b.label


def test_only_a_resize_goes_unlisted():
    hidden = [b for b in keys.KEYMAP if not b.label]
    assert [list(b.actions) for b in hidden] == [[curses.KEY_RESIZE]]


@pytest.mark.parametrize("code_skin", [False, True])
def test_the_help_screen_shows_every_binding(code_skin):
    text = help_screen(code_skin)
    indent = " " * (2 + keys.HELP_KEY_W)
    for b in keys.KEYMAP:
        if not b.label:
            continue
        if b.compact:
            assert f"{b.label}  {b.text}" in text
            continue
        # every long entry's text starts in the same column
        assert len(b.label) < keys.HELP_KEY_W
        first, *more = b.text.split("\n")
        assert f"  {b.label:<{keys.HELP_KEY_W}}{first}" in text
        for line in more:
            assert f"{indent}{line}" in text


@pytest.mark.parametrize(
    "label", ["Arrow keys, k j l", "Esc", "x", "b / F2", "Tab (boss mode)", "Enter / Space"]
)
def test_the_help_screen_names_the_easily_missed_keys(label):
    assert f"  {label} " in help_screen()


def test_the_help_screen_fits_an_80x24_terminal():
    # it is all on screen: a help too big for it says so instead
    assert "Press any key to continue." in help_screen()
    # drawn from column 2, and curses leaves the last column alone
    assert all(2 + len(line) < 79 for line in keys.help_lines())


def test_every_help_line_fits_inside_the_code_skin():
    # the code skin moves the help right by its gutter
    assert all(len(line) <= 80 - 1 - 2 - CODE_GUTTER for line in keys.help_lines())


def test_the_help_screen_names_no_game_rules():
    # the foundations don't build up by suit in Spider or Golf
    assert "Foundations" not in help_screen()


def test_the_help_says_shift_u_and_shift_r_go_all_the_way():
    assert "U and R go all the way" in help_screen()


def test_t_and_shift_t_switch_the_theme():
    assert keys.PLAY_ACTIONS[ord("t")] == keys.PLAY_ACTIONS[ord("T")] == "theme"


def test_4_is_the_four_colour_key():
    assert keys.PLAY_ACTIONS[ord("4")] == "four_color"


def test_tab_is_the_boss_mode_key():
    assert keys.BOSS_ACTIONS == {ord("\t"): "next_disguise"}  # noqa: SIM300 (it is the one under test)
    assert ord("\t") not in keys.PLAY_ACTIONS


ARROWS = {name: getattr(curses, name) for name in ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT")}


def test_the_numpad_keys_windows_gives_codes_of_their_own_are_read_as_the_main_keys():
    # * and the corners and middle with NumLock off do nothing, so stay as
    # they are
    corners = {"KEY_A1": 449, "KEY_A3": 451, "KEY_B2": 453, "KEY_C1": 455, "KEY_C3": 457}
    pdcurses = SimpleNamespace(**ARROWS, **PDCURSES_NUMPAD, **corners)
    assert keys.numpad_keys(pdcurses) == {
        459: 10,
        465: ord("+"),
        464: ord("-"),
        458: ord("/"),
        450: curses.KEY_UP,
        456: curses.KEY_DOWN,
        452: curses.KEY_LEFT,
        454: curses.KEY_RIGHT,
    }


def test_no_key_is_read_as_another_under_ncurses():
    # it sends the main keys' codes for the numpad, and has none of those
    # names; the keypad corners and middle it does name are left alone
    ncurses = SimpleNamespace(**ARROWS, KEY_A1=348, KEY_A3=349, KEY_B2=350, KEY_C1=351, KEY_C3=352)
    assert keys.numpad_keys(ncurses) == {}
