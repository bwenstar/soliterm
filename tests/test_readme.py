"""README.md is written by hand, so this checks its table of options still
has every option the code has."""

import argparse
import re
from pathlib import Path

from soliterm.cli import build_parser

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
