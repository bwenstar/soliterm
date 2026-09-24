"""Boss mode output: fake 'work' that must never give the game away."""

import io
import os
import platform
import re
import sys

import pytest

from soliterm import camo, store, textmode
from soliterm.cli import main

from helpers import deal

TELLS = ("♠", "♥", "♦", "♣", "[###]", "score=", "Foundation")


@pytest.mark.parametrize("theme", camo.THEMES)
def test_every_theme_streams_without_running_out(theme):
    gen = camo.stream(theme, seed=5)
    lines = [next(gen) for _ in range(1000)]
    assert all(isinstance(line, str) for line in lines)


@pytest.mark.parametrize("n", [1, 10, 40, 120])
@pytest.mark.parametrize("theme", camo.THEMES)
def test_screenful_returns_exactly_n_lines(theme, n):
    assert len(camo.screenful(theme, n, seed=2)) == n


def test_an_unknown_theme_falls_back_to_a_default():
    assert isinstance(next(camo.stream("nonsense-theme", seed=1)), str)


def test_the_output_reads_as_work_not_cards():
    sample = "\n".join(camo.screenful("mixed", 200, seed=3))
    for tell in TELLS:
        assert tell not in sample
    assert any(k in sample for k in ("gcc", "pytest", "docker", "git", "INFO"))


@pytest.mark.parametrize("cmd", ["b", "boss"])
def test_the_text_mode_boss_command_prints_work_instead_of_the_board(cmd, capsys):
    g = deal("klondike", 1)
    assert textmode.run_text(g, True, "klondike", stream=io.StringIO(f"{cmd}\nq\n")) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "bye"
    # everything after the first board's status line is the disguise
    status = max(i for i, line in enumerate(out) if line.startswith("score="))
    boss = out[status + 1:-1]
    assert len(boss) >= 40
    for tell in TELLS:
        assert not any(tell in line for line in boss)


def boss_lines(out):
    """What a text session printed between its last board and "bye"."""
    lines = out.splitlines()
    assert lines[-1] == "bye"
    status = max(i for i, line in enumerate(lines) if line.startswith("score="))
    return lines[status + 1:-1]


LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d (INFO|DEBUG|WARN)")


def test_the_text_mode_boss_uses_the_chosen_theme(monkeypatch, capsys):
    cfg = store.load_config()
    cfg["camo_theme"] = "logs"
    store.save_config(cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO("b\nq\n"))
    assert main(["--text", "--game", "golf", "--seed", "7", "--ascii"]) == 0
    boss = boss_lines(capsys.readouterr().out)
    assert boss and all(LOG_LINE.match(line) for line in boss)


def test_an_unknown_theme_in_text_mode_gets_the_default(capsys):
    g = deal("golf", 7)
    textmode.run_text(g, False, "golf", stream=io.StringIO("b\nq\n"),
                      camo_theme="nonsense-theme")
    boss = boss_lines(capsys.readouterr().out)
    assert boss[0].startswith("$ make -j")


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_on_a_terminal_the_boss_clears_the_board_and_fills_the_screen(monkeypatch):
    out = Terminal()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(textmode.shutil, "get_terminal_size",
                        lambda fallback=(80, 24): os.terminal_size((100, 57)))
    g = deal("golf", 7)
    textmode.run_text(g, False, "golf", stream=io.StringIO("b\nq\n"))
    board, clear, boss = out.getvalue().partition("\x1b[H\x1b[2J\x1b[3J")
    assert clear and "score=" in board
    assert len(boss.splitlines()) == 57 + 1           # a screenful, then "bye"
    for tell in TELLS:
        assert tell not in boss


def build_dirs(n=80):
    """The directories make says it enters and leaves in the build theme."""
    text = "\n".join(camo.screenful("build", n, seed=1))
    return re.findall(r"directory '([^']*)'", text)


@pytest.mark.parametrize("plat,home", [
    ("linux", "/home/tester/"), ("darwin", "/Users/tester/"),
    ("win32", "C:/Users/tester/"),
])
def test_the_build_output_has_this_platforms_home(plat, home, monkeypatch):
    monkeypatch.setattr(sys, "platform", plat)
    dirs = build_dirs()
    assert dirs and all(d.startswith(home + "work/") for d in dirs)


def test_without_user_set_the_paths_name_nobody(monkeypatch):
    monkeypatch.delenv("USER")
    monkeypatch.setenv("LOGNAME", "someone")
    dirs = build_dirs()
    assert dirs and all(d.startswith("~/work/") for d in dirs)


def test_the_test_run_banner_is_for_this_python(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    banner = [line for line in camo.screenful("test", 5, seed=1)
              if line.startswith("platform ")]
    assert banner and banner[0].startswith(
        f"platform darwin -- Python {platform.python_version()}, ")
