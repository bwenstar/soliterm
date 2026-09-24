"""The colour themes: the tables of colour pairs the full-screen game draws in."""

import curses

import pytest

from soliterm import themes


def test_the_colour_numbers_are_curses_own():
    assert themes.DEFAULT == -1
    assert [
        themes.BLACK,
        themes.RED,
        themes.GREEN,
        themes.YELLOW,
        themes.BLUE,
        themes.MAGENTA,
        themes.CYAN,
        themes.WHITE,
    ] == [
        curses.COLOR_BLACK,
        curses.COLOR_RED,
        curses.COLOR_GREEN,
        curses.COLOR_YELLOW,
        curses.COLOR_BLUE,
        curses.COLOR_MAGENTA,
        curses.COLOR_CYAN,
        curses.COLOR_WHITE,
    ]


@pytest.mark.parametrize(
    "light, default_colours, chrome, note, bg",
    [
        pytest.param(False, True, curses.COLOR_CYAN, curses.COLOR_YELLOW, -1, id="dark"),
        pytest.param(True, True, curses.COLOR_BLUE, curses.COLOR_MAGENTA, -1, id="light"),
        # black stands in for the terminal's background, so it isn't light
        pytest.param(
            True,
            False,
            curses.COLOR_CYAN,
            curses.COLOR_YELLOW,
            curses.COLOR_BLACK,
            id="no default colours",
        ),
    ],
)
def test_classic_is_the_colours_soliterm_always_had(light, default_colours, chrome, note, bg):
    rows = themes.pair_colours(themes.CLASSIC, 8, light, default_colours)
    assert rows[:9] == [
        (1, curses.COLOR_RED, curses.COLOR_WHITE),
        (2, curses.COLOR_BLACK, curses.COLOR_WHITE),
        (3, curses.COLOR_BLACK, curses.COLOR_GREEN),
        (4, chrome, bg),
        (5, curses.COLOR_BLACK, curses.COLOR_YELLOW),
        (6, note, bg),
        (7, curses.COLOR_WHITE, curses.COLOR_BLUE),
        (8, curses.COLOR_WHITE, curses.COLOR_GREEN),
        (9, curses.COLOR_BLACK, curses.COLOR_CYAN),
    ]


def test_a_name_this_version_does_not_know_is_classic():
    assert themes.by_name("classic") is themes.CLASSIC
    assert themes.by_name("solarized") is themes.CLASSIC
    assert themes.by_name(None) is themes.CLASSIC
