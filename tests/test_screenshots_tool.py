"""tools/screenshots.py reads tmux captures into cells before drawing them.

None of this needs tmux. The parser is plain Python, so only the drawing
test needs Pillow and skips without it.
"""

import importlib.util
import json
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
    images = r"!\[[^\]]*\]\([^)]*docs/img/([^)\s]+)\)"
    shown = set(re.findall(images, README.read_text(encoding="utf-8")))
    assert shown == {tool.file_name(s) for s in tool.SCENES}


def test_the_readme_gives_the_size_of_the_terminal_in_the_pictures(tool):
    text = README.read_text(encoding="utf-8")
    assert f"{tool.COLS} columns by {tool.ROWS} rows" in text


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


def test_frames_can_play_faster_than_they_ran(tool):
    steps = tool.frames(2, every=200, speed=2)
    assert len(steps) == 10
    assert all(step.hold == 100 and 0.1 < step.wait < 0.2 for step in steps)


def test_the_hero_is_short_enough_to_watch_through(tool):
    seconds = sum(step.hold for step in scene(tool, "hero").steps if step.shot) / 1000
    assert 12 <= seconds <= 15


def test_a_caption_is_its_text_alone_in_the_middle_of_the_screen(tool):
    rows = tool.parse(tool.caption_screen("a little later..."))
    assert len(rows) == tool.ROWS
    lines = [text_of(row).strip() for row in rows]
    assert lines[tool.ROWS // 2] == "a little later..."
    assert sum(map(bool, lines)) == 1
    middle = text_of(rows[tool.ROWS // 2])
    left, right = len(middle) - len(middle.lstrip()), tool.COLS - len(middle.rstrip())
    assert abs(left - right) <= 1


def test_the_hero_says_so_where_it_skips_ahead(tool):
    steps = list(scene(tool, "hero").steps)
    jump = next(i for i, step in enumerate(steps) if step.keys == tool.TO_THE_FINISH)
    before = steps[jump - 1]
    assert before.shot and not before.keys
    assert before.caption == "a little later..."
    assert sum(bool(step.caption) for step in steps) == 1


def test_a_cast_starts_with_its_header(tool, monkeypatch):
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    cast = tool.Cast()
    cast.take(b"hi", 5.0)
    header, event = cast.text("soliterm --deal klondike:946").splitlines()
    assert json.loads(header) == {
        "version": 2,
        "width": tool.COLS,
        "height": tool.ROWS,
        "idle_time_limit": tool.CAST_IDLE,
        "title": "soliterm --deal klondike:946",
        "env": {"TERM": "xterm-256color"},
    }
    assert json.loads(event) == [0, "o", "hi"]
    # a timestamp only when the build asks for one, so a redraw can match
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1790000000")
    header = cast.text("t").splitlines()[0]
    assert json.loads(header)["timestamp"] == 1790000000


def test_a_cast_has_a_line_for_each_read_timed_from_the_first(tool):
    cast = tool.Cast()
    cast.take(b"\x1b[?1049h\x1b[1mSoliterm", 10.0)
    cast.take("\x1b[m ♠".encode(), 10.2504)
    lines = cast.text("t").splitlines()[1:]
    assert [json.loads(line) for line in lines] == [
        [0, "o", "\x1b[?1049h\x1b[1mSoliterm"],
        [0.25, "o", "\x1b[m ♠"],
    ]
    assert "♠" in lines[1]  # as it is, not as \u2660


def test_a_character_cut_by_a_read_waits_for_the_rest(tool):
    cast = tool.Cast()
    spade = "♠".encode()
    cast.take(b"x" + spade[:2], 1.0)
    cast.take(spade[2:], 1.5)
    assert cast.events == [(0, "x"), (0.5, "♠")]


def test_the_end_of_a_cast_puts_the_modes_back_and_keeps_the_screen(tool):
    game = (
        "\x1b[?1049h\x1b[22;0;0t\x1b[1;32r\x1b[?1h\x1b="
        "\x1b[?25l\x1b[?1000h\x1b[?1006;1002h\x1b[?1002l"
    )
    end = tool.put_back(game)
    assert end.startswith("\x1b[m")
    # the whole screen scrolls again, which matters on a terminal bigger
    # than the game's, and then the cursor goes to the bottom left
    assert end.index("\x1b[r") < end.index(f"\x1b[{tool.ROWS};1H")
    for mode in ("\x1b[?1l", "\x1b>", "\x1b[?25h", "\x1b[?1000l", "\x1b[?1006l"):
        assert mode in end
    assert "1049" not in end and "1002" not in end
    assert tool.put_back("") == f"\x1b[m\x1b[{tool.ROWS};1H"


def test_every_key_a_scene_presses_goes_as_a_terminal_sends_it(tool):
    keys = {key for s in tool.SCENES for step in s.steps for key in step.keys.split()}
    assert {tool.key_bytes(key) for key in keys}
    # in keypad mode, which curses turns on, as xterm-256color's kcuu1 and so on
    assert tool.key_bytes("Up") == b"\x1bOA"
    assert tool.key_bytes("Left") == b"\x1bOD"
    assert tool.key_bytes("Enter") == b"\r"
    assert tool.key_bytes("h") == b"h"
    with pytest.raises(tool.ShotError):
        tool.key_bytes("Hyper")


def test_the_hero_plays_to_the_finish_fast_in_a_cast(tool):
    (fast,) = [step for step in scene(tool, "hero").steps if step.keys == tool.TO_THE_FINISH]
    assert fast.gap < tool.KEY_GAP


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
