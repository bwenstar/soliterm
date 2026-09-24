#!/usr/bin/env python3
"""Draw the screenshots and the animated GIF in docs/img/.

  python3 tools/screenshots.py                    # every scene into docs/img/
  python3 tools/screenshots.py --scene freecell   # only the scenes named
  python3 tools/screenshots.py --list             # the scenes there are
  python3 tools/screenshots.py --svg --out /tmp/shots

Each scene runs the game in a private tmux server with a throwaway home
directory, types keys at it and grabs the screen with `tmux capture-pane -e`.
The colour codes in that capture are turned back into a grid of cells and
drawn with Pillow in DejaVu Sans Mono. Your own config and statistics are
never read or written, and every game shown is a numbered deal, so the
pictures come out the same each time apart from the clock and the boss
screen's random text. It needs tmux 3.0 or newer, Pillow and the font.

This is a development tool. Pillow is only needed here; the game itself
never imports it.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import NamedTuple, Union

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # --list and the parser work without it
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUT = ROOT / "docs" / "img"


# --------------------------------------------------------------------------- #
# Scenes
#
# A scene starts the game (at the menu when deal is None) and then runs its
# steps in order. A step sends its keys one at a time, waits, and can take a
# shot of the screen. Keys are tmux key names separated by spaces: letters
# stand for themselves, and there are Up, Down, Left, Right, Enter, Space,
# Escape, Tab, F2 and so on. A still scene is saved as <name>.png from its
# last shot. An animated one becomes <name>.gif, one frame per shot, each
# shown for its hold time in milliseconds.
#
# The keys follow the TUI's bindings in src/soliterm/tui/keys.py: the arrows
# move the cursor, Enter or Space picks a card up and puts it down, h shows
# a hint (and moves the cursor to the card it suggests), f sends the card at
# the cursor up (in Golf and Triple Peaks, to the waste), d deals, a
# finishes once every card can go up, u undoes, o opens the game's options,
# c toggles the code skin, b is the boss key and q quits.
# The moves were worked out for these deals. If a deal ever changes, play it
# with --deal and write down the new keys. tests/test_tui_play.py presses
# every scene's keys on a board the size of the scenes' terminal and checks
# each still gets to its last shot, so it fails when they stop working.
# --------------------------------------------------------------------------- #

COLS, ROWS = 100, 32  # terminal size for every scene
KEY_GAP = 0.15  # seconds between two keys
PAUSE = 0.4  # seconds to let the screen settle after a step


class Step(NamedTuple):
    keys: str = ""
    wait: float = PAUSE
    shot: bool = False
    hold: int = 1200


class Scene(NamedTuple):
    name: str
    about: str
    deal: str | None  # a share code, passed as --deal
    steps: Sequence[Step]
    animate: bool = False
    args: Sequence[str] = ()  # any other options, such as --theme dark


def shot(keys: str = "", hold: int = 1200, wait: float = PAUSE) -> Step:
    return Step(keys, wait, True, hold)


def golf(plays: str) -> str:
    """The keys for a game of Golf written as the columns to play from, 1 to
    7 from the left, and d for a deal. The cursor starts on column 1, and f
    plays the card under it to the waste."""
    keys, at = [], 1
    for play in plays.split():
        if play == "d":
            keys.append("d")
            continue
        column = int(play)
        keys += ["Right"] * (column - at) + ["Left"] * (at - column) + ["f"]
        at = column
    return " ".join(keys)


def frames(seconds: float, every: int = 100) -> list[Step]:
    """Shots every `every` milliseconds for `seconds`, for something that
    moves on its own. Taking a shot costs about 10 milliseconds, so each
    one waits that much less."""
    return [shot(hold=every, wait=(every - 10) / 1000) for _ in range(int(seconds * 1000 / every))]


# Klondike, deal 946: the first three hints are 6D onto 7C (column 7 to 4),
# 5S onto 6D (2 to 4) and 8C onto 9D (6 to 2). h puts the cursor on the
# card it suggests.
SIX_ON_SEVEN = "h Enter Left Left Left Enter"
FIVE_ON_SIX = "h Enter Right Right Enter"

# Then on to where every card can go up, 98 moves later, by following the
# hints: d when the hint is to deal, h f when it sends a card up, and
# otherwise h Enter, the arrows to the column it names, and Enter.
TO_THE_FINISH = """
    h f h Enter Right Enter h Enter Left Left Left Left Left Left Enter
    h Enter Right Right Enter d d h Enter Right Right Right Right Down Enter d d d d d d
    d d h Enter Left Down Enter d h f h f h f h Enter Left Down Enter d h f h f h f h f
    h f h Enter Left Left Left Enter h Enter Left Left Left Left Left Enter
    h Enter Left Left Left Left Left Left Enter h Enter Left Enter d d h f h f d h f d
    h f d d d h Enter Down Enter d d h f h f d h Enter Right Down Enter
    h Enter Right Down Enter h Enter Left Enter h Enter Right Right Down Enter
    h Enter Left Left Enter h Enter Left Enter h Enter Left Left Left Enter
    h Enter Right Right Right Enter d h Enter Right Right Right Right Down Enter d h f d
    d h Enter Right Right Down Enter d d h f d h Enter Right Down Enter d
    h Enter Right Right Right Right Right Enter h Enter Right Right Right Enter
    h Enter Right Right Right Enter d h Enter Right Down Enter h Enter Right Down Enter
    d d d h Enter Left Left Left Left Enter h f h f h f h f h f h f h f h f h f h f h f
    h f h f h f h f h f h f h f h f
"""

# Golf, deal 216, played out to a win.
GOLF_WIN = golf(
    "d d 1 1 7 1 4 1 3 6 2 2 3 d 6 7 6 d d 4 4 2 d 7 d d 5 2 5 4"
    " 7 6 3 d 5 4 d 2 6 7 d 3 3 5 d 1 d 5"
)

SCENES: list[Scene] = [
    Scene("menu", "the game menu", None, [shot()]),
    Scene(
        "klondike-in-play",
        "Klondike a few moves in, with a hint showing",
        "klondike:946",
        [Step(SIX_ON_SEVEN), Step(FIVE_ON_SIX), Step("d d d"), shot("h")],
    ),
    Scene(
        "freecell",
        "FreeCell after one move, with the next hint showing",
        "freecell:617",
        [Step("h Enter Right Right Right Enter"), shot("h")],
    ),
    Scene(
        "spider",
        "two-suit Spider after one move, with the next hint showing",
        "spider:s2:7",
        [Step("h Enter Right Right Right Right Enter"), shot("h")],
    ),
    Scene(
        "code-skin",
        "Klondike played inside the code skin",
        "klondike:946",
        [Step(SIX_ON_SEVEN), shot("c")],
    ),
    Scene(
        "boss-mode",
        "the boss key's fake build output",
        "klondike:946",
        # the output scrolls by itself, so give it time to fill the screen
        [shot("b", wait=3.0)],
    ),
    Scene(
        "hero",
        "animated: a few Klondike moves, then the finish and the win",
        "klondike:946",
        [
            shot(hold=1600),
            shot("h", hold=1800),
            shot("Enter", hold=800),
            shot("Left", hold=300),
            shot("Left", hold=300),
            shot("Left", hold=600),
            shot("Enter", hold=1400),
            shot("h", hold=1800),
            shot("Enter", hold=800),
            shot("Right", hold=300),
            shot("Right", hold=600),
            shot("Enter", hold=1400),
            shot("h", hold=1800),
            shot("Enter", hold=800),
            shot("Left", hold=300),
            shot("Left", hold=300),
            shot("Left", hold=300),
            shot("Left", hold=600),
            shot("Enter", hold=1400),
            # a cut to the end of the game, the cards going up and the
            # win: the finish takes about a second and a half and the
            # cascade after it six at most, then the banner comes up
            Step(TO_THE_FINISH),
            shot(hold=2600),
            shot("a", hold=100, wait=0.09),
            *frames(8.5),
            shot(hold=5000),
        ],
        animate=True,
    ),
    Scene(
        "triple-peaks",
        "Triple Peaks eight cards into a run, with the next hint showing",
        "triplepeaks:108",
        [Step(" ".join(["h f"] * 8)), shot("h")],
    ),
    Scene(
        "contrast",
        "Yukon in the contrast theme, with a hint showing",
        "yukon:5",
        [Step("h f h Enter Right Enter"), shot("h")],
        args=["--theme", "contrast"],
    ),
    Scene(
        "win",
        "the banner after winning a game of Golf, with its share code",
        "golf:216",
        # the cascade runs for up to six seconds before the banner
        [Step(GOLF_WIN), shot(wait=7.5)],
    ),
]


# --------------------------------------------------------------------------- #
# Look
# --------------------------------------------------------------------------- #

FONT_SIZE = 18
FONT_FILE = "DejaVuSansMono.ttf"
BOLD_FILE = "DejaVuSansMono-Bold.ttf"
# Where Debian and Ubuntu, Fedora, Arch, Homebrew and a per-user install put
# DejaVu. --font overrides the search.
FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu-sans-mono-fonts",
    "/usr/share/fonts/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/local/share/fonts",
    "/opt/homebrew/share/fonts",
    "~/.local/share/fonts",
    "~/Library/Fonts",
    "/Library/Fonts",
]

BACKGROUND = "#1a1d23"
FOREGROUND = "#d7dae0"
# The 16 ANSI colours. The TUI draws face-up cards as red or black text on a
# white background, so red is a strong dark red and white a soft off-white
# that both read well on the card faces. Green is the selection, yellow the
# cursor and hints, blue the card backs and cyan the labels.
PALETTE = [
    "#16181d",  # black
    "#c62828",  # red
    "#3b8f41",  # green
    "#e5b62c",  # yellow
    "#2d5ca8",  # blue
    "#a664c9",  # magenta
    "#56b6c2",  # cyan
    "#eeeeee",  # white
    "#5c6370",  # bright black
    "#ef5350",  # bright red
    "#66bb6a",  # bright green
    "#ffd54f",  # bright yellow
    "#64b5f6",  # bright blue
    "#ce93d8",  # bright magenta
    "#80deea",  # bright cyan
    "#ffffff",  # bright white
]

PAD = 16  # space around the grid, in pixels
BAR = 34  # height of the title bar
RADIUS = 10  # corner radius of the window
BAR_COLOUR = "#2b2f37"
TITLE_COLOUR = "#9aa1ad"
DOTS = ["#ff5f57", "#febc2e", "#28c840"]
GIF_COLOURS = 64


# --------------------------------------------------------------------------- #
# Reading tmux captures
# --------------------------------------------------------------------------- #

RGB = tuple[int, int, int]
# None is the terminal's default, an int is a palette index (0-255) and a
# tuple is a 24-bit colour.
Colour = Union[int, RGB, None]


class Cell(NamedTuple):
    char: str = " "  # "" for the right half of a wide character
    fg: Colour = None
    bg: Colour = None
    bold: bool = False
    dim: bool = False
    underline: bool = False
    reverse: bool = False


# CSI sequences (SGR is the one that ends in m), OSC strings such as
# hyperlinks, and any other escape, like the ESC ( B that picks a charset.
ESCAPE = re.compile(
    r"\x1b\[([0-?]*)[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[ -/]*[0-~]"
)


def parse(text: str) -> list[list[Cell]]:
    """Turn `tmux capture-pane -p -e` output into rows of cells.

    The style carries on across line breaks, the way a terminal would read
    it, and escape sequences other than SGR are dropped.
    """
    rows: list[list[Cell]] = [[]]
    style = Cell()
    pos = 0
    for m in [*ESCAPE.finditer(text), None]:
        end = m.start() if m else len(text)
        for ch in text[pos:end]:
            if ch == "\n":
                rows.append([])
            elif ch >= " ":
                rows[-1].append(style._replace(char=ch))
                if unicodedata.east_asian_width(ch) in ("W", "F"):
                    rows[-1].append(style._replace(char=""))
        if m is None:
            break
        pos = m.end()
        if m.group(2) == "m":
            style = sgr(style, m.group(1))
    if len(rows) > 1 and not rows[-1]:
        rows.pop()  # the newline that ends the last line
    return rows


def sgr(style: Cell, params: str) -> Cell:
    """Apply one SGR sequence's parameters (the part between [ and m)."""
    codes = params.split(";") if params else ["0"]
    i = 0
    while i < len(codes):
        part = codes[i]
        i += 1
        if ":" in part:
            # the colon form: 38:5:n, or 38:2:r:g:b with an optional colour
            # space id before the r
            head, *rest = part.split(":")
            if rest[:1] == ["2"]:
                rest = ["2", *rest[-3:]]
            code, (colour, used) = _int(head), _extended(rest)
        else:
            code = _int(part)
            colour, used = _extended(codes[i:]) if code in (38, 48) else (None, 0)
            i += used
        if code in (38, 48):
            if used and code == 38:
                style = style._replace(fg=colour)
            elif used:
                style = style._replace(bg=colour)
        elif code == 0:
            style = Cell()
        elif code == 1:
            style = style._replace(bold=True)
        elif code == 2:
            style = style._replace(dim=True)
        elif code == 4:
            style = style._replace(underline=True)
        elif code == 7:
            style = style._replace(reverse=True)
        elif code == 22:
            style = style._replace(bold=False, dim=False)
        elif code == 24:
            style = style._replace(underline=False)
        elif code == 27:
            style = style._replace(reverse=False)
        elif 30 <= code <= 37:
            style = style._replace(fg=code - 30)
        elif code == 39:
            style = style._replace(fg=None)
        elif 40 <= code <= 47:
            style = style._replace(bg=code - 40)
        elif code == 49:
            style = style._replace(bg=None)
        elif 90 <= code <= 97:
            style = style._replace(fg=code - 90 + 8)
        elif 100 <= code <= 107:
            style = style._replace(bg=code - 100 + 8)
    return style


def _int(text: str) -> int:
    return int(text) if text.isdigit() else 0


def _extended(rest: list[str]) -> tuple[Colour, int]:
    """The colour after a 38 or 48, and how many parameters it took.

    5 is followed by a palette index and 2 by red, green and blue. Anything
    else takes nothing, and the colour is left as it was.
    """
    nums = [min(255, _int(x)) for x in rest[:4]]
    if nums[:1] == [5] and len(nums) >= 2:
        return nums[1], 2
    if nums[:1] == [2] and len(nums) >= 4:
        return (nums[1], nums[2], nums[3]), 4
    return None, 0


def _hex(value: str) -> RGB:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def xterm_colour(n: int) -> RGB:
    """RGB for an xterm 256-colour index, with PALETTE for the first 16."""
    if n < 16:
        return _hex(PALETTE[n])
    if n < 232:
        n -= 16
        steps = [0, 95, 135, 175, 215, 255]
        return (steps[n // 36], steps[n // 6 % 6], steps[n % 6])
    grey = 8 + (n - 232) * 10
    return (grey, grey, grey)


def colours(cell: Cell) -> tuple[RGB, RGB]:
    """The foreground and background a cell is drawn in."""

    def rgb(colour: Colour, default: str) -> RGB:
        if colour is None:
            return _hex(default)
        if isinstance(colour, tuple):
            return colour
        return xterm_colour(colour)

    fg, bg = rgb(cell.fg, FOREGROUND), rgb(cell.bg, BACKGROUND)
    if cell.reverse:
        fg, bg = bg, fg
    if cell.dim:
        fg = (
            (fg[0] + bg[0]) // 2,
            (fg[1] + bg[1]) // 2,
            (fg[2] + bg[2]) // 2,
        )
    return fg, bg


def background_runs(row: list[Cell]) -> list[tuple[int, int, RGB]]:
    """(start, end, colour) for each stretch of non-default background."""
    runs: list[tuple[int, int, RGB]] = []
    default = _hex(BACKGROUND)
    for x, cell in enumerate(row[:COLS]):
        bg = colours(cell)[1]
        if bg == default:
            continue
        if runs and runs[-1][1] == x and runs[-1][2] == bg:
            runs[-1] = (runs[-1][0], x + 1, bg)
        else:
            runs.append((x, x + 1, bg))
    return runs


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #


class ShotError(Exception):
    pass


def find_fonts(requested: str | None) -> tuple[Path, Path | None]:
    """The regular and, if there is one next to it, the bold font file."""
    if requested:
        regular = Path(requested).expanduser()
        if not regular.is_file():
            raise ShotError(f"no font file at {regular}")
        stem = regular.stem.removesuffix("-Regular")
        bold = regular.with_name(f"{stem}-Bold{regular.suffix}")
        return regular, bold if bold.is_file() else None
    for folder in FONT_DIRS:
        regular = Path(folder).expanduser() / FONT_FILE
        if regular.is_file():
            bold = regular.with_name(BOLD_FILE)
            return regular, bold if bold.is_file() else None
    raise ShotError(
        f"can't find {FONT_FILE}. Install DejaVu Sans Mono (fonts-dejavu-core "
        "on Debian and Ubuntu) or point --font at a monospace .ttf file"
    )


def load_font(path: Path, size: int):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as exc:
        raise ShotError(f"can't load the font {path}: {exc}") from None


class Painter:
    """Draws a grid of cells as a terminal window, in PNG, GIF or SVG."""

    def __init__(self, font: str | None = None, chrome: bool = True):
        regular, bold = find_fonts(font)
        self.font = load_font(regular, FONT_SIZE)
        self.bold = load_font(bold, FONT_SIZE) if bold else self.font
        self.title_font = load_font(regular, FONT_SIZE - 4)
        # Box-drawing lines only join up if a row is exactly the font's
        # ascent plus descent tall.
        self.cw = round(self.font.getlength("M"))
        self.ascent, descent = self.font.getmetrics()
        self.ch = self.ascent + descent
        self.bar = BAR if chrome else 0
        self.top = self.bar + PAD
        self.size = (COLS * self.cw + 2 * PAD, self.top + ROWS * self.ch + PAD)

    def image(self, grid: list[list[Cell]], title: str = ""):
        img = Image.new("RGB", self.size, BACKGROUND)
        draw = ImageDraw.Draw(img)
        for y, row in enumerate(grid[:ROWS]):
            top = self.top + y * self.ch
            bottom = top + self.ch - 1
            for start, end, bg in background_runs(row):
                left, right = PAD + start * self.cw, PAD + end * self.cw - 1
                draw.rectangle((left, top, right, bottom), fill=bg)
            for x, cell in enumerate(row[:COLS]):
                left = PAD + x * self.cw
                fg = colours(cell)[0]
                if cell.char.strip():
                    font = self.bold if cell.bold else self.font
                    draw.text((left, top), cell.char, font=font, fill=fg)
                if cell.underline:
                    line = top + self.ascent + 1
                    draw.line((left, line, left + self.cw - 1, line), fill=fg)
        if self.bar:
            img = self._window(img, title)
        return img

    def _window(self, img, title: str):
        """Add the title bar and round the corners."""
        width, height = img.size
        scale = 4  # draw the round shapes large and shrink them, to smooth them
        lanczos = getattr(Image, "Resampling", Image).LANCZOS
        bar = Image.new("RGB", (width * scale, self.bar * scale), BAR_COLOUR)
        draw = ImageDraw.Draw(bar)
        middle = self.bar * scale // 2
        for i, colour in enumerate(DOTS):
            x = (PAD + 6 + i * 20) * scale
            r = 6 * scale
            draw.ellipse((x - r, middle - r, x + r, middle + r), fill=colour)
        img.paste(bar.resize((width, self.bar), lanczos), (0, 0))
        if title:
            draw = ImageDraw.Draw(img)
            left = (width - draw.textlength(title, font=self.title_font)) / 2
            draw.text(
                (left, self.bar / 2),
                title,
                font=self.title_font,
                fill=TITLE_COLOUR,
                anchor="lm",
            )
        mask = Image.new("L", (width * scale, height * scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, width * scale - 1, height * scale - 1), RADIUS * scale, fill=255
        )
        img = img.convert("RGBA")
        img.putalpha(mask.resize((width, height), lanczos))
        return img

    def svg(self, grid: list[list[Cell]], title: str = "") -> str:
        width, height = self.size
        size = f'width="{width}" height="{height}"'
        box = f'viewBox="0 0 {width} {height}"'
        font = "'DejaVu Sans Mono',Menlo,Consolas,monospace"
        # Keep runs of spaces, which SVG would otherwise squash to one.
        style = f"font-family:{font};font-size:{FONT_SIZE}px;white-space:pre"
        keep = 'xml:space="preserve"'
        radius = RADIUS if self.bar else 0
        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" {keep} {size} {box}>',
            f"<style>text{{{style}}}</style>",
            f'<clipPath id="w"><rect {size} rx="{radius}"/></clipPath>',
            '<g clip-path="url(#w)">',
            f'<rect {size} fill="{BACKGROUND}"/>',
        ]
        if self.bar:
            middle = self.bar / 2
            out.append(f'<rect width="{width}" height="{self.bar}" fill="{BAR_COLOUR}"/>')
            for i, colour in enumerate(DOTS):
                x = PAD + 6 + i * 20
                out.append(f'<circle cx="{x}" cy="{middle}" r="6" fill="{colour}"/>')
            if title:
                out.append(
                    f'<text x="{width / 2}" y="{middle}" fill="{TITLE_COLOUR}" '
                    f'font-size="{FONT_SIZE - 4}px" text-anchor="middle" '
                    f'dominant-baseline="central">{html.escape(title)}</text>'
                )
        for y, row in enumerate(grid[:ROWS]):
            top = self.top + y * self.ch
            for start, end, bg in background_runs(row):
                out.append(
                    f'<rect x="{PAD + start * self.cw}" y="{top}" '
                    f'width="{(end - start) * self.cw}" height="{self.ch}" '
                    f'fill="#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}"/>'
                )
            spans = [self._tspan(*run) for run in _text_runs(row[:COLS])]
            if spans:
                out.append(f'<text y="{top + self.ascent}">{"".join(spans)}</text>')
        out.append("</g></svg>")
        return "\n".join(out) + "\n"

    def _tspan(self, x: int, text: str, fg: RGB, bold: bool, underline: bool) -> str:
        attrs = [
            f'x="{PAD + x * self.cw}"',
            f'fill="#{fg[0]:02x}{fg[1]:02x}{fg[2]:02x}"',
        ]
        if bold:
            attrs.append('font-weight="bold"')
        if underline:
            attrs.append('text-decoration="underline"')
        if len(text) > 1:
            # holds the run to the grid even if the viewer's font is wider
            attrs.append(f'textLength="{len(text) * self.cw}"')
            attrs.append('lengthAdjust="spacingAndGlyphs"')
        return f"<tspan {' '.join(attrs)}>{html.escape(text, quote=False)}</tspan>"


def _text_runs(row: list[Cell]) -> list[tuple[int, str, RGB, bool, bool]]:
    """Stretches of a row drawn in one style, as (start, text, fg, bold, underline).

    Spaces go along with whatever run they sit in, so a line of text in one
    colour comes out as a single run.
    """
    runs: list[tuple[int, str, RGB, bool, bool]] = []
    start, chars, key = 0, [], None
    for x, cell in enumerate(row + [Cell(char="")]):
        blank = cell.char == " " and not cell.underline
        this = None if cell.char == "" else (colours(cell)[0], cell.bold, cell.underline)
        if key is not None and (blank or this == key):
            chars.append(cell.char)
            continue
        if key is not None:
            runs.append((start, "".join(chars).rstrip(" "), *key))
            key = None
        if this is not None and not blank:
            start, chars, key = x, [cell.char], this
    return runs


def save_gif(path: Path, images: list, holds: list[int]) -> None:
    """Write an animated GIF with one small palette and see-through corners."""
    nearest = getattr(Image, "Resampling", Image).NEAREST
    no_dither = getattr(Image, "Dither", Image).NONE
    clear = GIF_COLOURS - 1  # the palette slot kept for the corners
    # GIF has no partial transparency, so the soft edge of the corners is
    # flattened onto the background and only the outside is cleared.
    solids = []
    for img in images:
        solid = Image.new("RGB", img.size, BACKGROUND)
        solid.paste(img, mask=img if img.mode == "RGBA" else None)
        solids.append(solid)
    # One palette for every frame, so colours do not flicker as it plays.
    # The theme colours go in exactly and the rest of the slots are picked
    # from half-size samples of all the frames, mostly for glyph edges.
    theme = [BACKGROUND, FOREGROUND, BAR_COLOUR, TITLE_COLOUR, *DOTS, *PALETTE]
    fixed = list(dict.fromkeys(_hex(c) for c in theme))
    width, height = (n // 2 for n in solids[0].size)
    sheet = Image.new("RGB", (width, height * len(solids)))
    for i, solid in enumerate(solids):
        sheet.paste(solid.resize((width, height), nearest), (0, height * i))
    spare = clear - len(fixed)
    flat = (sheet.quantize(colors=spare).getpalette() or [])[: 3 * spare]
    # Pillow maps pixels through a coarse colour cache, so a picked colour
    # close to a theme colour could steal its pixels. Those are left out.
    picked = [
        rgb
        for rgb in zip(flat[0::3], flat[1::3], flat[2::3])
        if all(max(abs(a - b) for a, b in zip(rgb, f)) >= 12 for f in fixed)
    ]
    colours = [c for rgb in fixed + picked for c in rgb]
    palette = Image.new("P", (1, 1))
    palette.putpalette(colours)
    colours += [0, 0, 0] * (GIF_COLOURS - len(colours) // 3)
    frames = []
    for img, solid in zip(images, solids):
        frame = solid.quantize(palette=palette, dither=no_dither)
        frame.putpalette(colours)
        if img.mode == "RGBA":
            outside = img.getchannel("A").point(lambda a: 255 if a < 128 else 0)
            frame.paste(clear, mask=outside)
            frame.info["transparency"] = clear
        frames.append(frame)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=holds, loop=0)


# --------------------------------------------------------------------------- #
# Driving the game
# --------------------------------------------------------------------------- #

# The user's own tmux.conf never gets loaded. remain-on-exit keeps the pane
# around if the game dies, so the error can be shown.
TMUX_CONF = "set -g status off\nset -g remain-on-exit on\n"


class Frame(NamedTuple):
    text: str
    hold: int


class Stage:
    """A private tmux server and a scratch home, both removed by close()."""

    def __init__(self) -> None:
        self.socket = f"soliterm-shots-{os.getpid()}"
        self.tmp = Path(tempfile.mkdtemp(prefix="soliterm-shots-"))
        self.conf = self.tmp / "tmux.conf"
        self.conf.write_text(TMUX_CONF, encoding="utf-8")
        self.socket_path: Path | None = None

    def close(self) -> None:
        self.tmux("kill-server", check=False)
        # tmux leaves its socket file behind when the server exits.
        if self.socket_path is not None:
            self.socket_path.unlink(missing_ok=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tmux(self, *args: str, check: bool = True) -> str:
        cmd = ["tmux", "-L", self.socket, "-f", str(self.conf), *args]
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if check and done.returncode != 0:
            raise ShotError(f"tmux {args[0]} failed: {done.stderr.strip()}")
        return done.stdout

    def run(self, scene: Scene) -> list[Frame]:
        """Play a scene and return the screens it shot."""
        home = self.tmp / scene.name
        home.mkdir()
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "c"),
            "XDG_DATA_HOME": str(home / "d"),
            "USER": "dev",
            "LOGNAME": "dev",
            "TERM": "xterm-256color",
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(SRC),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        game = [sys.executable, "-m", "soliterm", *scene_args(scene)]
        command = ["env", "-i", *(f"{k}={v}" for k, v in env.items()), *game]
        size = ["-x", str(COLS), "-y", str(ROWS)]
        self.tmux("new-session", "-d", "-s", scene.name, *size, *command)
        try:
            if self.socket_path is None:
                path = self.tmux("display-message", "-p", "#{socket_path}").strip()
                self.socket_path = Path(path) if path else None
            self._settle(scene.name)
            frames = []
            for step in scene.steps:
                for key in step.keys.split():
                    self.tmux("send-keys", "-t", scene.name, key)
                    time.sleep(KEY_GAP)
                time.sleep(step.wait)
                self._check_alive(scene.name)
                if step.shot:
                    frames.append(Frame(self.capture(scene.name), step.hold))
            if not frames:
                frames.append(Frame(self.capture(scene.name), 0))
            return frames
        finally:
            self.tmux("kill-session", "-t", scene.name, check=False)

    def capture(self, target: str, codes: bool = True) -> str:
        return self.tmux("capture-pane", "-p", *(["-e"] if codes else []), "-t", target)

    def _settle(self, target: str, timeout: float = 15.0) -> None:
        """Wait until the game has drawn its first screen."""
        before = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_alive(target)
            now = self.capture(target)
            if now.strip() and now == before:
                return
            before = now
            time.sleep(0.25)
        raise ShotError(f"{target}: the game drew nothing in {timeout:.0f}s")

    def _check_alive(self, target: str) -> None:
        dead = self.tmux("display-message", "-p", "-t", target, "#{pane_dead}")
        if dead.strip() == "1":
            lines = self.capture(target, codes=False).splitlines()
            screen = "\n".join(line.rstrip() for line in lines if line.strip())
            raise ShotError(f"{target}: the game exited early:\n{screen}")


def scene_args(scene: Scene) -> list[str]:
    return (["--deal", scene.deal] if scene.deal else []) + list(scene.args)


def title_of(scene: Scene) -> str:
    return " ".join(["soliterm", *scene_args(scene)])


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #


def pick(names: list[str] | None) -> list[Scene]:
    if not names:
        return list(SCENES)
    known: dict[str, Scene] = {s.name: s for s in SCENES}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ShotError(f"no scene called {', '.join(unknown)} (try: {', '.join(known)})")
    return [known[n] for n in dict.fromkeys(names)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="screenshots.py",
        description="Draw the screenshots and the animated GIF in docs/img/.",
    )
    p.add_argument(
        "--scene",
        nargs="+",
        action="extend",
        metavar="NAME",
        help="only these scenes (default: all of them)",
    )
    p.add_argument("--out", type=Path, default=OUT, help="where to write (docs/img)")
    p.add_argument("--svg", action="store_true", help="also write each scene's last frame as SVG")
    p.add_argument("--font", help=f"a monospace .ttf to use instead of {FONT_FILE}")
    p.add_argument("--no-chrome", action="store_true", help="leave off the title bar")
    p.add_argument("--list", action="store_true", help="list the scenes and exit")
    args = p.parse_args(argv)

    if args.list:
        for s in SCENES:
            kind = "gif" if s.animate else "png"
            print(f"  {s.name:<18} {kind}  {s.about}")
        return 0
    try:
        scenes = pick(args.scene)
        if Image is None:
            raise ShotError("Pillow is needed to draw: python -m pip install pillow")
        if shutil.which("tmux") is None:
            raise ShotError("tmux is needed to run the game; install it first")
        painter = Painter(args.font, chrome=not args.no_chrome)
        args.out.mkdir(parents=True, exist_ok=True)
        with closing(Stage()) as stage:
            for scene in scenes:
                frames = stage.run(scene)
                title = title_of(scene)
                images = [painter.image(parse(f.text), title) for f in frames]
                written = [args.out / f"{scene.name}.{'gif' if scene.animate else 'png'}"]
                if scene.animate:
                    save_gif(written[0], images, [f.hold for f in frames])
                else:
                    images[-1].save(written[0], optimize=True)
                if args.svg:
                    written.append(args.out / f"{scene.name}.svg")
                    svg = painter.svg(parse(frames[-1].text), title)
                    written[-1].write_text(svg, encoding="utf-8")
                for path in written:
                    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KiB)")
    except ShotError as exc:
        print(f"screenshots.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
