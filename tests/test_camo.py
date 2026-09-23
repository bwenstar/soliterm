"""Boss mode output: fake 'work' that must never give the game away."""

import io

import pytest

from soliterm import camo, cli
from helpers import deal

TELLS = ("♠", "♥", "♦", "♣", "[##]", "score=", "Foundation")


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
    assert cli.run_text(g, True, "klondike", stream=io.StringIO(f"{cmd}\nq\n")) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "bye"
    # everything after the first board's status line is the disguise
    status = max(i for i, line in enumerate(out) if line.startswith("score="))
    boss = out[status + 1:-1]
    assert len(boss) >= 40
    for tell in TELLS:
        assert not any(tell in line for line in boss)
