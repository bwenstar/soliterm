"""soliterm.themes - the colours the full-screen game draws in.

A theme is a table of curses colour pairs. It lives here, away from curses,
so the command line can know about the themes without importing curses.
"""

from __future__ import annotations

from typing import NamedTuple, Union

# The basic 8 colours, in the ANSI order (red is ESC[31m), which is
# ncurses' order too; -1 is the terminal's own colour, as
# curses.use_default_colors() allows. PDCurses, the curses on Windows,
# numbers the 8 another way, so pair_colours takes curses' own numbers
# for them.
DEFAULT, BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(-1, 8)
BASIC = (BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE)

# the colour pairs, by what they draw
FACE_RED = 1  # a heart or a diamond: red on the white card face
FACE_BLACK = 2  # a spade or a club: black on the white card face
SELECTED = 3  # the run picked up
CHROME = 4  # titles, labels, empty slots, the code skin's line numbers
CURSOR = 5  # the cursor, the selected menu row, the code skin's tab
MESSAGE = 6  # the message line and headings
BACK = 7  # a face-down card
RED_SELECTED = 8  # a red card in the run picked up
HINT = 9  # a hinted card
KEYWORD = 10  # the code skin's source
STRING = 11
NUMBER = 12
COMMENT = 13  # and the notes the code skin writes as comments
DIAMOND_FACE = 14  # a diamond; red unless the four-colour deck is on
CLUB_FACE = 15  # a club; black unless the four-colour deck is on

# the kinds camo.code_tokens() finds, and the pair each is drawn in
SYNTAX = {"keyword": KEYWORD, "string": STRING, "number": NUMBER, "comment": COMMENT}

# the pair drawn instead of one a terminal has no room for (0 is the
# terminal's own colours). With only 8 pairs, as on qnx, a red card picked
# up is drawn like a black one, and a hint in colours no other card has.
# With 7, a card back is drawn like a spade's face, its pattern still
# telling it apart, and not in the hint's colours.
FALLBACK = {
    BACK: FACE_BLACK,
    RED_SELECTED: SELECTED,
    HINT: 0,
    KEYWORD: 0,
    STRING: 0,
    NUMBER: 0,
    COMMENT: CHROME,
    DIAMOND_FACE: FACE_RED,
    CLUB_FACE: FACE_BLACK,
}

# runtime aliases, so no X | Y before Python 3.10
Colour = Union[int, tuple[int, int]]  # one colour, or (on 256 colours, on others)
Pair = tuple[Colour, Colour]  # (text, background)


class Theme(NamedTuple):
    name: str
    pairs: dict[int, Pair]  # on a dark background
    on_light: dict[int, Pair]  # the pairs that change on a light one


# Face-up cards are drawn like real cards: the suit colour on a white card
# face, and true black for spades and clubs, so they read as black and not
# white on any terminal background.
CLASSIC = Theme(
    "classic",
    {
        FACE_RED: (RED, WHITE),
        FACE_BLACK: (BLACK, WHITE),
        SELECTED: (BLACK, GREEN),
        CHROME: (CYAN, DEFAULT),
        CURSOR: (BLACK, YELLOW),
        MESSAGE: (YELLOW, DEFAULT),
        BACK: (WHITE, BLUE),
        RED_SELECTED: (WHITE, GREEN),
        HINT: (BLACK, CYAN),
        KEYWORD: (MAGENTA, DEFAULT),
        STRING: (GREEN, DEFAULT),
        NUMBER: (YELLOW, DEFAULT),
        COMMENT: (CYAN, DEFAULT),
        # the four-colour deck: orange diamonds and green clubs, and blue
        # diamonds in the basic 8, which have no orange
        DIAMOND_FACE: ((166, BLUE), WHITE),
        CLUB_FACE: ((28, GREEN), WHITE),
    },
    # cyan and yellow wash out on white
    {
        CHROME: (BLUE, DEFAULT),
        MESSAGE: (MAGENTA, DEFAULT),
        NUMBER: (RED, DEFAULT),
        COMMENT: (BLUE, DEFAULT),
    },
)

# dark and light are tuned for 256 colours and are classic on any other
# number. They keep to their own background whatever the terminal says, so
# either one puts right a terminal that says the wrong thing, or says
# nothing.
DARK = Theme(
    "dark",
    {
        FACE_RED: ((160, RED), (254, WHITE)),
        FACE_BLACK: ((16, BLACK), (254, WHITE)),
        SELECTED: ((16, BLACK), (28, GREEN)),
        CHROME: ((110, CYAN), DEFAULT),
        CURSOR: ((16, BLACK), (214, YELLOW)),
        MESSAGE: ((179, YELLOW), DEFAULT),
        BACK: ((231, WHITE), (24, BLUE)),
        RED_SELECTED: ((231, WHITE), (28, GREEN)),
        HINT: ((16, BLACK), (37, CYAN)),
        KEYWORD: ((176, MAGENTA), DEFAULT),
        STRING: ((114, GREEN), DEFAULT),
        NUMBER: ((173, YELLOW), DEFAULT),
        COMMENT: ((245, CYAN), DEFAULT),
        DIAMOND_FACE: ((166, BLUE), (254, WHITE)),
        CLUB_FACE: ((28, GREEN), (254, WHITE)),
    },
    {},
)

LIGHT = Theme(
    "light",
    {
        FACE_RED: ((160, RED), (255, WHITE)),
        FACE_BLACK: ((16, BLACK), (255, WHITE)),
        SELECTED: ((16, BLACK), (28, GREEN)),
        CHROME: ((25, BLUE), DEFAULT),
        CURSOR: ((16, BLACK), (220, YELLOW)),
        MESSAGE: ((130, MAGENTA), DEFAULT),
        BACK: ((231, WHITE), (25, BLUE)),
        RED_SELECTED: ((231, WHITE), (28, GREEN)),
        HINT: ((16, BLACK), (80, CYAN)),
        KEYWORD: ((90, MAGENTA), DEFAULT),
        STRING: ((28, GREEN), DEFAULT),
        NUMBER: ((166, RED), DEFAULT),
        COMMENT: ((242, BLUE), DEFAULT),
        DIAMOND_FACE: ((166, BLUE), (255, WHITE)),
        CLUB_FACE: ((28, GREEN), (255, WHITE)),
    },
    {},
)

# the text in the terminal's own colours, and the cards as stark as can be
CONTRAST = Theme(
    "contrast",
    {
        FACE_RED: ((124, RED), (231, WHITE)),
        FACE_BLACK: ((16, BLACK), (231, WHITE)),
        SELECTED: ((231, BLACK), (22, GREEN)),
        CHROME: (DEFAULT, DEFAULT),
        CURSOR: ((16, BLACK), (226, YELLOW)),
        MESSAGE: (DEFAULT, DEFAULT),
        BACK: ((231, WHITE), (18, BLUE)),
        RED_SELECTED: ((231, BLACK), (22, GREEN)),
        HINT: ((16, BLACK), (51, CYAN)),
        KEYWORD: ((213, MAGENTA), DEFAULT),
        STRING: ((120, GREEN), DEFAULT),
        NUMBER: ((228, YELLOW), DEFAULT),
        COMMENT: (DEFAULT, DEFAULT),
        DIAMOND_FACE: ((130, BLUE), (231, WHITE)),
        CLUB_FACE: ((22, GREEN), (231, WHITE)),
    },
    # the code skin's colours, darker for a light background
    {
        KEYWORD: ((90, MAGENTA), DEFAULT),
        STRING: ((22, GREEN), DEFAULT),
        NUMBER: ((124, RED), DEFAULT),
    },
)

THEMES: tuple[Theme, ...] = (CLASSIC, DARK, LIGHT, CONTRAST)
NAMES: tuple[str, ...] = tuple(t.name for t in THEMES)
_BY_NAME = {t.name: t for t in THEMES}


def by_name(name: str | None) -> Theme:
    """The theme called `name`; classic for None, or for a name this
    version doesn't have (a newer version's theme, a hand edit)."""
    return _BY_NAME.get(name or "", CLASSIC)


def next_theme(theme: Theme) -> Theme:
    """The theme t moves on to, round to the first after the last."""
    return THEMES[(NAMES.index(theme.name) + 1) % len(THEMES)]


def pick(colour: Colour, colours: int, basic: tuple[int, ...] = BASIC) -> int:
    """The curses number for `colour` on a terminal with `colours` colours,
    where `basic` is curses' numbers for the basic 8, in BASIC's order.

    The tuned colours are xterm's 256, so a terminal with any other number
    gets the basic 8. That includes a direct-colour one (xterm-direct has
    16777216), which reads most numbers as red, green and blue and would
    draw the 256 as dark blues. The tuned ones are all past the first 16,
    where every curses numbers them as xterm does.
    """
    if isinstance(colour, tuple):
        if colours == 256:
            return colour[0]
        colour = colour[1]
    return colour if colour == DEFAULT else basic[colour]


def pair_colours(
    theme: Theme,
    colours: int = 8,
    light: bool = False,
    default_colours: bool = True,
    four_color: bool = False,
    basic: tuple[int, ...] = BASIC,
) -> list[tuple[int, int, int]]:
    """(pair, text, background) for every pair, as curses.init_pair takes them.

    A light background changes only the pairs in theme.on_light, and only
    when the terminal's own background shows through. Without default
    colours (use_default_colors failed), white text on black stands in
    for -1. Without the four-colour deck, diamonds and clubs are red and
    black like hearts and spades. `basic` is curses' numbers for the basic
    8, as pick takes them.
    """
    table = dict(theme.pairs)
    if light and default_colours:
        table.update(theme.on_light)
    if not four_color:
        table[DIAMOND_FACE] = table[FACE_RED]
        table[CLUB_FACE] = table[FACE_BLACK]
    out = []
    for n in sorted(table):
        fg, bg = (pick(c, colours, basic) for c in table[n])
        if not default_colours:
            fg = basic[WHITE] if fg == DEFAULT else fg
            bg = basic[BLACK] if bg == DEFAULT else bg
        out.append((n, fg, bg))
    return out
