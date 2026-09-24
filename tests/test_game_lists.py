"""The lists of games written out by hand outside the code, checked against
GAME_ORDER so a new game can't be left off one."""

import re
from pathlib import Path

import pytest

from soliterm.engine import GAME_ORDER, GAMES

ROOT = Path(__file__).resolve().parents[1]
BUG_REPORT = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
GAMES_INDEX = ROOT / "docs" / "games" / "README.md"

NAMES = [GAMES[key].name for key in GAME_ORDER]
# a row of a games table: | [Name](key.md) | `key` | ...
ROW = re.compile(r"^\| \[(.+?)\]\((\w+)\.md\) \| `(\w+)` \|", re.MULTILINE)


@pytest.mark.skipif(not BUG_REPORT.exists(), reason="no .github/ in this tree")
def test_the_bug_report_offers_every_game_in_menu_order():
    lines = BUG_REPORT.read_text(encoding="utf-8").splitlines()
    start = lines.index("    id: game")
    end = next(i for i in range(start, len(lines)) if "validations:" in lines[i])
    offered = [line.split("- ", 1)[1] for line in lines[start:end] if line.strip().startswith("- ")]
    assert offered == ["Not game specific", *NAMES]


@pytest.mark.skipif(not GAMES_INDEX.exists(), reason="no docs/ in this tree")
def test_the_games_index_links_every_game_in_menu_order():
    rows = ROW.findall(GAMES_INDEX.read_text(encoding="utf-8"))
    assert rows == [(GAMES[key].name, key, key) for key in GAME_ORDER]
    for key in GAME_ORDER:
        assert (GAMES_INDEX.parent / f"{key}.md").exists(), key
