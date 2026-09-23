"""KEYMAP is the one list of play-screen keys: the dispatch and the help
screen both come from it, so these checks keep the two honest."""

import curses
import inspect
import re

import pytest

from soliterm.tui import keys
from soliterm.tui.app import App
from helpers import FakeScr

# how a label names the keys that are not a plain character
NAMES = {curses.KEY_UP: "Arrow", curses.KEY_DOWN: "Arrow",
         curses.KEY_LEFT: "Arrow", curses.KEY_RIGHT: "Arrow",
         curses.KEY_ENTER: "Enter", 10: "Enter", 13: "Enter", ord(" "): "Space",
         27: "Esc", ord("\t"): "Tab", curses.KEY_F2: "F2",
         curses.KEY_MOUSE: "Mouse"}


def help_screen():
    scr = FakeScr(24, 80)
    scr.getch = lambda: ord(" ")      # the key that closes it
    App(scr).help_screen()
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
    handlers = {name[3:] for name, _ in inspect.getmembers(App, inspect.isfunction)
                if name.startswith("do_")}
    assert set(keys.PLAY_ACTIONS.values()) == handlers


def test_every_listed_key_is_named_in_its_label():
    for b in keys.KEYMAP:
        if not b.label:
            continue
        words = re.split(r"[\s,/()]+", b.label)
        for k in b.actions:
            name = NAMES.get(k) or chr(k)
            assert name in words or name.lower() in words, (b.label, name)


def test_only_a_resize_goes_unlisted():
    hidden = [b for b in keys.KEYMAP if not b.label]
    assert [list(b.actions) for b in hidden] == [[curses.KEY_RESIZE]]


def test_the_help_screen_shows_every_binding():
    text = help_screen()
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


@pytest.mark.parametrize("label", ["Arrow keys, k j l", "Esc", "x", "b / F2",
                                   "Tab (boss mode)", "Enter / Space"])
def test_the_help_screen_names_the_easily_missed_keys(label):
    assert f"  {label} " in help_screen()


def test_the_help_screen_fits_an_80x24_terminal():
    rows = help_screen().split("\n")
    assert "Press any key to continue." in rows[-1]
    # drawn from column 2, and curses leaves the last column alone
    assert all(2 + len(line) < 79 for line in keys.help_lines())


def test_tab_is_the_boss_mode_key():
    assert keys.BOSS_ACTIONS == {ord("\t"): "next_disguise"}
    assert ord("\t") not in keys.PLAY_ACTIONS
