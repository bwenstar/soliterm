"""tools/screenshots.py reads tmux captures into cells before drawing them.

None of this needs tmux. The parser is plain Python, so only the drawing
test needs Pillow and skips without it.
"""

import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from soliterm import deals
from soliterm.cli import build_parser
from soliterm.engine import GAME_ORDER

TOOL = Path(__file__).resolve().parents[1] / "tools" / "screenshots.py"
README = TOOL.parents[1] / "README.md"

pytestmark = pytest.mark.skipif(not TOOL.exists(), reason="no tools/ in this tree")


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("screenshots", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text_of(row):
    return "".join(cell.char for cell in row)


def test_plain_text(tool):
    rows = tool.parse("ab\ncd \n")
    assert [text_of(row) for row in rows] == ["ab", "cd "]
    assert rows[0][0] == tool.Cell("a")


def test_basic_and_bright_colours(tool):
    (row,) = tool.parse("\x1b[31;42ma\x1b[91;102mb\x1b[39;49mc\x1b[37;40md")
    assert [(c.fg, c.bg) for c in row] == [(1, 2), (9, 10), (None, None), (7, 0)]


def test_256_and_truecolour(tool):
    (row,) = tool.parse("\x1b[38;5;196;48;2;1;2;300ma\x1b[38:2::10:20:30;48:5:17mb")
    assert (row[0].fg, row[0].bg) == (196, (1, 2, 255))
    assert (row[1].fg, row[1].bg) == ((10, 20, 30), 17)


def test_a_short_extended_colour_changes_nothing(tool):
    (row,) = tool.parse("\x1b[31m\x1b[38;5ma")
    assert row[0].fg == 1


def test_attributes_turn_on_and_off(tool):
    (row,) = tool.parse("\x1b[1;7ma\x1b[22mb\x1b[27mc\x1b[2md\x1b[4me\x1b[0mf\x1b[mg")
    flags = [(c.bold, c.dim, c.reverse, c.underline) for c in row]
    assert flags == [
        (True, False, True, False),
        (False, False, True, False),
        (False, False, False, False),
        (False, True, False, False),
        (False, True, False, True),
        (False, False, False, False),
        (False, False, False, False),
    ]


def test_style_carries_across_lines(tool):
    rows = tool.parse("\x1b[33mab\ncd\x1b[0m\ne")
    assert [c.fg for row in rows for c in row] == [3, 3, 3, 3, None]


def test_other_escapes_are_dropped(tool):
    link = "\x1b]8;;https://example.com\x1b\\"
    (row,) = tool.parse(f"{link}li\x1b]8;;\x07nk\x1b[2J\x1b(B\x1b[?25l!\r")
    assert text_of(row) == "link!"


def test_wide_characters_fill_two_cells(tool):
    (row,) = tool.parse("界a")
    assert [c.char for c in row] == ["界", "", "a"]


def test_colours_follow_reverse_and_dim(tool):
    red, background = tool._hex(tool.PALETTE[1]), tool._hex(tool.BACKGROUND)
    assert tool.colours(tool.Cell(fg=1)) == (red, background)
    assert tool.colours(tool.Cell(fg=1, reverse=True)) == (background, red)
    fg, _ = tool.colours(tool.Cell(fg=(200, 100, 0), bg=(0, 0, 0), dim=True))
    assert fg == (100, 50, 0)


def test_xterm_colours(tool):
    assert tool.xterm_colour(16) == (0, 0, 0)
    assert tool.xterm_colour(196) == (255, 0, 0)
    assert tool.xterm_colour(231) == (255, 255, 255)
    assert tool.xterm_colour(232) == (8, 8, 8)
    assert tool.xterm_colour(255) == (238, 238, 238)


def test_background_runs_join_up(tool):
    (row,) = tool.parse("\x1b[41mab\x1b[42mc\x1b[0m d\x1b[7m e")
    red, green = tool._hex(tool.PALETTE[1]), tool._hex(tool.PALETTE[2])
    foreground = tool._hex(tool.FOREGROUND)
    assert tool.background_runs(row) == [
        (0, 2, red),
        (2, 3, green),
        (5, 7, foreground),
    ]


def scene(tool, name):
    (found,) = [s for s in tool.SCENES if s.name == name]
    return found


def test_scenes_are_valid(tool):
    names = [scene.name for scene in tool.SCENES]
    assert len(names) == len(set(names))
    for scene in tool.SCENES:
        assert scene.deal is None or deals.parse(scene.deal).key in GAME_ORDER, scene.name
        assert scene.steps, scene.name
        build_parser().parse_args(tool.scene_args(scene))  # exits on an unknown option
    shots = [sum(step.shot for step in s.steps) for s in tool.SCENES if s.animate]
    assert shots and min(shots) > 1


def test_a_scene_plays_its_deal(tool):
    freecell = scene(tool, "freecell")
    assert tool.scene_args(freecell) == ["--deal", "freecell:617"]
    assert tool.title_of(freecell) == "soliterm --deal freecell:617"
    menu = tool.Scene("menu", "the game menu", None, [tool.shot()])
    assert tool.scene_args(menu) == []
    assert tool.title_of(menu) == "soliterm"


def test_only_a_scene_that_moves_is_a_gif(tool):
    assert tool.file_name(scene(tool, "hero")) == "hero.gif"
    assert tool.file_name(scene(tool, "freecell")) == "freecell.png"


def test_the_readme_shows_every_picture_the_scenes_draw(tool):
    # one it doesn't show would only sit in docs/img and go stale
    shown = set(re.findall(r"docs/img/([^)\s]+)", README.read_text(encoding="utf-8")))
    assert shown == {tool.file_name(s) for s in tool.SCENES}


def test_a_scene_passes_its_options_after_the_deal(tool):
    contrast = scene(tool, "contrast")
    assert tool.scene_args(contrast) == ["--deal", "yukon:5", "--theme", "contrast"]
    assert tool.title_of(contrast) == "soliterm --deal yukon:5 --theme contrast"


def test_golf_walks_the_cursor_to_each_column(tool):
    assert tool.golf("1 3 d 2 2") == "f Right Right f d Left f f"


def test_frames_last_as_long_as_asked(tool):
    steps = tool.frames(1.5, every=100)
    assert len(steps) == 15
    assert all(step.shot and step.hold == 100 and step.wait < 0.1 for step in steps)


def test_draws_a_window(tool):
    pytest.importorskip("PIL")
    try:
        painter = tool.Painter()
    except tool.ShotError as exc:
        pytest.skip(str(exc))
    grid = tool.parse("\x1b[41m  \x1b[0m\x1b[1;32mok  go\x1b[0m\n")
    img = painter.image(grid, "title")
    assert img.size == painter.size
    middle = (tool.PAD + painter.cw, painter.top + painter.ch // 2)
    assert img.getpixel(middle)[:3] == tool._hex(tool.PALETTE[1])
    assert img.getpixel((0, 0))[3] == 0  # outside the rounded corner
    svg = painter.svg(grid, "title")
    ET.fromstring(svg)
    assert ">ok  go</tspan>" in svg
