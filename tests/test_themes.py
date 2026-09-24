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


# -- every theme ---------------------------------------------------------------------

PALE = {curses.COLOR_YELLOW, curses.COLOR_CYAN, curses.COLOR_WHITE}
DIM = {curses.COLOR_BLACK, curses.COLOR_BLUE}


def luma(n):
    """How light xterm's colour n is, from 0 for black to 1 for white.

    Only for the 6x6x6 cube and the grey ramp; the first 16 are whatever
    the terminal's palette says."""
    if n >= 232:
        return (8 + 10 * (n - 232)) / 255
    levels = (0, 95, 135, 175, 215, 255)
    r, g, b = (levels[d] for d in ((n - 16) // 36, (n - 16) // 6 % 6, (n - 16) % 6))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def pale(n):
    """Too light to read on white."""
    return n in PALE if n < 16 else luma(n) >= 0.55


def dim(n):
    """Too dark to read on black."""
    return n in DIM if n < 16 else luma(n) <= 0.45


def text_on_the_terminal(theme, colours, light):
    """The colours of the text drawn on the terminal's own background."""
    rows = themes.pair_colours(theme, colours, light)
    return {(n, fg) for n, fg, bg in rows if bg == -1 and fg != -1}


def test_every_theme_sets_every_pair():
    assert themes.NAMES == ("classic", "dark", "light", "contrast")
    for theme in themes.THEMES:
        assert theme.pairs.keys() == themes.CLASSIC.pairs.keys(), theme.name
        assert theme.on_light.keys() <= theme.pairs.keys(), theme.name
        for colours in (8, 256):
            for light in (False, True):
                for n, fg, bg in themes.pair_colours(theme, colours, light):
                    assert -1 <= fg < colours and -1 <= bg < colours, (theme.name, n)


def test_256_colour_terminals_get_the_tuned_colours():
    assert (themes.CHROME, 110, -1) in themes.pair_colours(themes.DARK, 256)
    assert (themes.CHROME, curses.COLOR_CYAN, -1) in themes.pair_colours(themes.DARK, 8)


@pytest.mark.parametrize("light", [False, True])
def test_on_8_colours_dark_and_light_are_classic_pinned(light):
    classic_on_dark = themes.pair_colours(themes.CLASSIC, 8, light=False)
    classic_on_light = themes.pair_colours(themes.CLASSIC, 8, light=True)
    assert themes.pair_colours(themes.DARK, 8, light) == classic_on_dark
    assert themes.pair_colours(themes.LIGHT, 8, light) == classic_on_light


@pytest.mark.parametrize("colours", [8, 256])
@pytest.mark.parametrize("theme", themes.THEMES, ids=themes.NAMES)
def test_cards_have_a_background_of_their_own_in_every_theme(theme, colours):
    cards = {
        themes.FACE_RED,
        themes.FACE_BLACK,
        themes.SELECTED,
        themes.CURSOR,
        themes.BACK,
        themes.RED_SELECTED,
        themes.HINT,
    }
    for light in (False, True):
        for n, fg, bg in themes.pair_colours(theme, colours, light):
            if n in cards:
                assert bg not in (-1, fg), n


@pytest.mark.parametrize("colours", [8, 256])
@pytest.mark.parametrize(
    "theme, light",
    [
        (themes.LIGHT, False),
        (themes.LIGHT, True),
        (themes.CLASSIC, True),
        (themes.CONTRAST, True),
    ],
)
def test_light_backgrounds_get_dark_enough_text(theme, light, colours):
    for n, fg in text_on_the_terminal(theme, colours, light):
        assert not pale(fg), n


@pytest.mark.parametrize("colours", [8, 256])
@pytest.mark.parametrize(
    "theme, light",
    [
        (themes.DARK, False),
        (themes.DARK, True),
        (themes.CLASSIC, False),
        (themes.CONTRAST, False),
    ],
)
def test_dark_backgrounds_get_light_enough_text(theme, light, colours):
    for n, fg in text_on_the_terminal(theme, colours, light):
        assert not dim(fg), n


@pytest.mark.parametrize("theme", themes.THEMES, ids=themes.NAMES)
def test_without_default_colours_nothing_is_left_to_the_terminal(theme):
    for colours in (8, 256):
        for light in (False, True):
            rows = themes.pair_colours(theme, colours, light, default_colours=False)
            assert all(fg != -1 and bg != -1 for _, fg, bg in rows)


def test_next_theme_goes_round():
    names = []
    theme = themes.CLASSIC
    for _ in themes.THEMES:
        theme = themes.next_theme(theme)
        names.append(theme.name)
    assert names == ["dark", "light", "contrast", "classic"]


# -- the four-colour deck ---------------------------------------------------------------


def colours_of(theme, colours=8, light=False, **kwargs):
    """pair -> (text, background), as pair_colours sets them up."""
    rows = themes.pair_colours(theme, colours, light, **kwargs)
    return {n: (fg, bg) for n, fg, bg in rows}


def test_the_four_colour_deck_has_orange_diamonds_and_green_clubs():
    decks = {}
    for theme in themes.THEMES:
        pairs = colours_of(theme, 256, four_color=True)
        face = pairs[themes.FACE_RED][1]
        assert pairs[themes.DIAMOND_FACE][1] == pairs[themes.CLUB_FACE][1] == face
        decks[theme.name] = (pairs[themes.DIAMOND_FACE][0], pairs[themes.CLUB_FACE][0])
    # contrast's are darker, as its red is
    assert decks == {
        "classic": (166, 28),
        "dark": (166, 28),
        "light": (166, 28),
        "contrast": (130, 22),
    }


@pytest.mark.parametrize("theme", themes.THEMES, ids=themes.NAMES)
def test_on_8_colours_the_diamonds_are_blue(theme):
    pairs = colours_of(theme, 8, four_color=True)
    assert pairs[themes.DIAMOND_FACE] == (curses.COLOR_BLUE, curses.COLOR_WHITE)
    assert pairs[themes.CLUB_FACE] == (curses.COLOR_GREEN, curses.COLOR_WHITE)


@pytest.mark.parametrize("theme", themes.THEMES, ids=themes.NAMES)
def test_diamonds_and_clubs_match_red_and_black_with_the_deck_off(theme):
    for colours in (8, 256):
        for light in (False, True):
            pairs = colours_of(theme, colours, light)
            assert pairs[themes.DIAMOND_FACE] == pairs[themes.FACE_RED]
            assert pairs[themes.CLUB_FACE] == pairs[themes.FACE_BLACK]


# -- the code skin ---------------------------------------------------------------------


@pytest.mark.parametrize("theme", themes.THEMES, ids=themes.NAMES)
def test_the_code_skin_pairs_sit_on_the_terminal_background(theme):
    assert set(themes.SYNTAX) == {"keyword", "string", "number", "comment"}
    for colours in (8, 256):
        for light in (False, True):
            pairs = colours_of(theme, colours, light)
            for n in themes.SYNTAX.values():
                assert pairs[n][1] == -1, (n, colours, light)


@pytest.mark.parametrize("light", [False, True])
def test_classic_comments_look_like_its_labels(light):
    # so the code skin's notes look as they always have
    for colours in (8, 256):
        pairs = colours_of(themes.CLASSIC, colours, light)
        assert pairs[themes.COMMENT] == pairs[themes.CHROME]
