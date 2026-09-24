"""soliterm.themes - the colours the full-screen game draws in.

A theme is a table of curses colour pairs. It lives here, away from curses,
so the command line can know about the themes without importing curses.
"""

from __future__ import annotations

from typing import NamedTuple, Union

# curses' colour numbers (curses.COLOR_BLACK and so on); -1 is the
# terminal's own colour, as curses.use_default_colors() allows
DEFAULT, BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(-1, 8)

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

# runtime aliases, so no X | Y before Python 3.10
Colour = Union[int, tuple[int, int]]  # one colour, or (on 256 colours, on fewer)
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
    },
    # cyan and yellow wash out on white
    {
        CHROME: (BLUE, DEFAULT),
        MESSAGE: (MAGENTA, DEFAULT),
    },
)

THEMES: tuple[Theme, ...] = (CLASSIC,)
_BY_NAME = {t.name: t for t in THEMES}


def by_name(name: str | None) -> Theme:
    """The theme called `name`; classic for None, or for a name this
    version doesn't have (a newer version's theme, a hand edit)."""
    return _BY_NAME.get(name or "", CLASSIC)


def pick(colour: Colour, colours: int) -> int:
    """The curses number for `colour` on a terminal with `colours` colours."""
    if isinstance(colour, tuple):
        return colour[0] if colours >= 256 else colour[1]
    return colour


def pair_colours(
    theme: Theme, colours: int = 8, light: bool = False, default_colours: bool = True
) -> list[tuple[int, int, int]]:
    """(pair, text, background) for every pair, as curses.init_pair takes them.

    A light background changes only the pairs in theme.on_light, and only
    when the terminal's own background shows through. Without default
    colours (use_default_colors failed), white text on black stands in
    for -1.
    """
    table = dict(theme.pairs)
    if light and default_colours:
        table.update(theme.on_light)
    out = []
    for n in sorted(table):
        fg, bg = (pick(c, colours) for c in table[n])
        if not default_colours:
            fg = WHITE if fg == DEFAULT else fg
            bg = BLACK if bg == DEFAULT else bg
        out.append((n, fg, bg))
    return out
