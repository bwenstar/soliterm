"""man/soliterm.6 is written by hand, so these check it still names every
game and every option the code has, and the version."""

import argparse
import re
from pathlib import Path

import pytest

from soliterm import __version__
from soliterm.cli import build_parser
from soliterm.engine import GAME_ORDER

PAGE = Path(__file__).resolve().parents[1] / "man" / "soliterm.6"

pytestmark = pytest.mark.skipif(not PAGE.exists(), reason="no man/ in this tree")


def section(name: str) -> list[str]:
    """The lines of one .SH section of the page."""
    lines = PAGE.read_text(encoding="utf-8").splitlines()
    start = lines.index(f".SH {name}") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith(".SH ")), len(lines))
    return lines[start:end]


def test_the_games_section_lists_every_game_in_menu_order():
    lines = section("GAMES")
    keys = [lines[i + 1].split()[1] for i, line in enumerate(lines) if line == ".TP"]
    assert keys == GAME_ORDER


def test_every_option_in_the_help_is_described():
    shown = {
        flag
        for action in build_parser()._actions
        if action.help != argparse.SUPPRESS
        for flag in action.option_strings
    }
    described = set()
    for line in section("OPTIONS"):
        if line.startswith((".TP", ".B", ".BR", ".BI")):
            described.update(re.findall(r"(?<![\w-])-{1,2}[a-z][a-z-]*", line.replace("\\-", "-")))
    assert shown <= described, sorted(shown - described)


def test_the_title_line_names_this_version():
    lines = PAGE.read_text(encoding="utf-8").splitlines()
    title = next(line for line in lines if line.startswith(".TH "))
    assert f'"Soliterm {__version__}"' in title, title
