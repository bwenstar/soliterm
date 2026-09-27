"""README.md is written by hand, so this checks its table of options still
has every option the code has, and that what it shows holds together."""

import argparse
import re
from pathlib import Path

from soliterm import textmode
from soliterm.cli import build_parser

from helpers import deal

README = Path(__file__).resolve().parents[1] / "README.md"


def section(title: str) -> str:
    """The text of one ## section of the README."""
    text = README.read_text(encoding="utf-8")
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_every_option_in_the_help_is_in_the_options_table():
    shown = {
        flag
        for action in build_parser()._actions
        if action.help != argparse.SUPPRESS
        for flag in action.option_strings
    }
    rows = [line for line in section("Options").splitlines() if line.startswith("| `")]
    described = {
        flag for row in rows for flag in re.findall(r"`(-{1,2}[a-z][a-z-]*)", row.split(" | ")[0])
    }
    assert shown <= described, sorted(shown - described)


def test_the_readme_links_to_no_heading_of_its_own():
    # PyPI shows the README too, and a heading there has no anchor to go to
    assert "](#" not in README.read_text(encoding="utf-8")


def test_the_text_mode_example_plays_on_its_board():
    text = section("Text mode")
    name, number = re.search(r"Soliterm - (\w+) - Deal (\d+)", text).groups()
    g = deal(name.lower(), int(number))
    said = text[text.index("A slot is named") : text.index("`hint`")]
    commands = re.findall(r"`(d|\d+ \d+)`", said)
    assert commands and re.fullmatch(r"\d+ \d+", commands[-1])
    for command in commands:
        assert textmode.apply_text_command(g, command)[0], command
