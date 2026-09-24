"""The lists of games written out by hand outside the code, checked against
GAME_ORDER so a new game can't be left off one, and the number of games
where the docs and the package's descriptions give it."""

import re
from pathlib import Path

import pytest

from soliterm.engine import GAME_ORDER, GAMES

ROOT = Path(__file__).resolve().parents[1]
BUG_REPORT = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
GAMES_INDEX = ROOT / "docs" / "games" / "README.md"
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE = ROOT / "src" / "soliterm" / "__init__.py"
MAN_PAGE = ROOT / "man" / "soliterm.6"
# README.md links with full URLs, as PyPI shows it too
PAGES_URL = "https://github.com/bwenstar/soliterm/blob/main/docs/games/"

NAMES = [GAMES[key].name for key in GAME_ORDER]
# a row of a games table: | [Name](key.md) | `key` | ..., with the link's
# path before key.md in the README
ROW = re.compile(r"^\| \[(.+?)\]\((\w+)\.md\) \| `(\w+)` \|", re.MULTILINE)
README_ROW = re.compile(
    rf"^\| \[(.+?)\]\({re.escape(PAGES_URL)}(\w+)\.md\) \| `(\w+)` \|", re.MULTILINE
)

NUMBERS = (  # noqa: SIM905 (easier to read than a list of 21 strings)
    "zero one two three four five six seven eight nine ten eleven twelve"
    " thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split()
# "twelve games" or "Twelve solitaire games", but not "the last ten games
# you played"
HOW_MANY = re.compile(
    r"(?<!last )\b(" + "|".join(NUMBERS) + r") (?:solitaire )?(?:card )?games\b", re.IGNORECASE
)


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


def test_the_readme_links_every_game_in_menu_order():
    rows = README_ROW.findall(README.read_text(encoding="utf-8"))
    assert rows == [(GAMES[key].name, key, key) for key in GAME_ORDER]


def test_the_readme_describes_every_game_as_the_games_index_does():
    if not GAMES_INDEX.exists():
        pytest.skip("no docs/ in this tree")
    about = re.compile(r"^\| \[.+?\]\(\S+\) \| `(\w+)` \| (.+) \|$", re.MULTILINE)
    index = about.findall(GAMES_INDEX.read_text(encoding="utf-8"))
    assert about.findall(README.read_text(encoding="utf-8")) == index


@pytest.mark.parametrize("path", [README, PYPROJECT, PACKAGE, MAN_PAGE], ids=lambda p: p.name)
def test_the_number_of_games_is_right_wherever_it_is_given(path):
    if not path.exists():
        pytest.skip(f"no {path.name} in this tree")
    # one space between words, as a line can break inside the phrase
    text = " ".join(path.read_text(encoding="utf-8").split())
    said = {word.lower() for word in HOW_MANY.findall(text)}
    assert said == {NUMBERS[len(GAME_ORDER)]}, f"{path.name} says {sorted(said)} games"


def test_the_readme_counts_the_games_it_leaves_unnamed():
    text = " ".join(README.read_text(encoding="utf-8").split())
    found = re.search(r"\*\*\w+ games:\*\* (.+?) and (\w+) more\b", text)
    assert found, "the README no longer names a few games and counts the rest"
    named = found.group(1).split(", ")
    assert set(named) <= set(NAMES)
    assert found.group(2) == NUMBERS[len(GAME_ORDER) - len(named)]
