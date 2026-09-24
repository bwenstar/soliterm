"""docs/keybindings.md is written by tools/keybindings.py from the key
tables in the code, so it can't fall behind them unnoticed."""

import curses
import importlib.util
from pathlib import Path

import pytest

from soliterm.textmode import TEXT_HELP
from soliterm.tui import keys

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "keybindings.py"
DOC = ROOT / "docs" / "keybindings.md"

pytestmark = pytest.mark.skipif(
    not (TOOL.exists() and DOC.exists()), reason="no tools/ or docs/ in this tree"
)


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("keybindings", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_page_is_up_to_date(tool):
    assert DOC.read_text(encoding="utf-8") == tool.render(), (
        "docs/keybindings.md is out of date: run python tools/keybindings.py"
    )


def test_every_play_key_is_on_the_page(tool):
    page = tool.render()
    for b in keys.KEYMAP:
        if not b.label:
            continue
        assert b.text.split("\n")[0] in page, b.label
        for name in tool.keys_of(b):
            assert f"`{name}`" in page, (b.label, name)


def test_the_text_commands_are_copied_in(tool):
    assert TEXT_HELP.strip("\n") in tool.render()


def test_keys_are_named_as_a_player_would(tool):
    enter = keys.bind((curses.KEY_ENTER, 10, 13, " "), "select", "Enter", "")
    assert tool.keys_of(enter) == ["Enter", "Space"]
    (arrows,) = [b for b in keys.KEYMAP if "up" in b.actions.values()]
    assert tool.keys_of(arrows)[:2] == ["Up", "k"]
    mouse = keys.bind((curses.KEY_MOUSE,), "mouse", "Mouse click", "")
    assert tool.keys_of(mouse) == []


def test_check_says_when_the_page_is_stale(tool, tmp_path, monkeypatch, capsys):
    stale = tmp_path / "keybindings.md"
    stale.write_text("# Keys\n", encoding="utf-8")
    assert not tool.is_current(stale)
    assert not tool.is_current(tmp_path / "missing.md")
    monkeypatch.setattr(tool, "DOC", stale)
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    assert tool.main(["--check"]) == 1
    assert "run python tools/keybindings.py" in capsys.readouterr().err
    assert tool.main([]) == 0
    assert tool.is_current(stale)
    assert tool.main(["--check"]) == 0
