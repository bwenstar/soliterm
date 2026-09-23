"""The command line: --list, --stats, --reset-stats and a scripted text session."""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

import soliterm
from soliterm import aisleriot as ar
from soliterm import store
from soliterm.cli import main, render_text
from soliterm.engine import GAME_ORDER, GAMES
from helpers import deal


@pytest.fixture
def cli(monkeypatch, capsys):
    """Returns run(*args, stdin="") -> (exit code, stdout lines)."""
    def run(*args, stdin=""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        rc = main(list(args))
        return rc, capsys.readouterr().out.splitlines()
    return run


def stats_row(lines, key):
    """The numbers on a game's --stats line, after its name."""
    name = GAMES[key].name
    row = [line for line in lines if line.startswith(name + " ")]
    assert len(row) == 1, f"no single stats line for {name}"
    return row[0][len(name):].split()


# -- --version and --help ---------------------------------------------------------------

def test_version_prints_the_command_and_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"soliterm {soliterm.__version__}\n"


def test_help_uses_the_soliterm_name(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert out.startswith("usage: soliterm ")
    assert "Soliterm" in out and "AisleRiot CLI" not in out


# -- --list ----------------------------------------------------------------------------

def test_list_names_every_game_in_menu_order(cli):
    rc, lines = cli("--list")
    assert rc == 0
    rows = [line.split(None, 1) for line in lines if line.startswith("  ")]
    assert [key for key, _ in rows] == GAME_ORDER
    for key, rest in rows:
        assert rest.startswith(GAMES[key].name)


def test_list_writes_nothing(cli):
    cli("--list")
    assert not store.load_stats()
    assert store.load_config() == store.DEFAULT_CONFIG


# -- --stats ---------------------------------------------------------------------------

def test_stats_on_a_fresh_home_are_all_empty(cli):
    rc, lines = cli("--stats")
    assert rc == 0
    assert lines[0].split() == ["Game", "Wins", "Total", "Win%", "Best", "Worst"]
    for key in GAME_ORDER:
        assert stats_row(lines, key) == ["0", "0", "N/A", "N/A", "N/A"]


def test_stats_show_recorded_games(cli):
    store.record_result("klondike", True, 65)
    store.record_result("klondike", True, 200)
    store.record_result("klondike", False, 30)
    store.record_result("eightoff", False, 10)
    rc, lines = cli("--stats")
    assert stats_row(lines, "klondike") == ["2", "3", "67%", "1:05", "3:20"]
    assert stats_row(lines, "eightoff") == ["0", "1", "0%", "N/A", "N/A"]
    assert stats_row(lines, "spider") == ["0", "0", "N/A", "N/A", "N/A"]


def test_stats_read_through_to_aisleriot(cli, keyfile):
    keyfile(f"[{ar.GAME_TO_SECTION['freecell']}]\nStatistic=3;4;75;300;\n")
    rc, lines = cli("--stats")
    assert stats_row(lines, "freecell") == ["3", "4", "75%", "1:15", "5:00"]


# -- --reset-stats ---------------------------------------------------------------------

# "y" on stdin in case clearing ever asks first.

def test_reset_stats_clears_local_statistics(cli):
    store.record_result("golf", True, 50)
    store.record_result("yukon", False, 50)
    rc, lines = cli("--reset-stats", stdin="y\n")
    assert rc == 0
    assert any("cleared" in line.lower() for line in lines)
    for key in GAME_ORDER:
        assert store.get_stat(key)["total"] == 0
    rc, lines = cli("--stats")
    assert stats_row(lines, "golf") == ["0", "0", "N/A", "N/A", "N/A"]


def test_reset_stats_clears_the_shared_aisleriot_record(cli, keyfile):
    path = keyfile("[Aisleriot Config]\nTheme=tigullio.svgz\n\n"
                   f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n")
    rc, lines = cli("--reset-stats", stdin="y\n")
    assert rc == 0
    assert any("cleared" in line.lower() for line in lines)
    assert store.get_stat("canfield")["total"] == 0
    assert ar.read_stat(ar.GAME_TO_SECTION["canfield"])["total"] == 0
    assert "Theme=tigullio.svgz" in path.read_text()


# -- text mode -------------------------------------------------------------------------

def without_status(board):
    """A rendered board minus its last line (score, moves and status)."""
    body, _, status = board.rpartition("\n")
    assert status.startswith("score=")
    return body


def test_a_scripted_text_session(cli):
    # replay the session on the same hand to know what each board should be
    g = deal("klondike", 1)
    src, dst, n = g.best_move()
    boards = [render_text(g, symbols=False)]
    assert g.attempt_move(src, dst, n)
    boards.append(render_text(g, symbols=False))
    assert g.undo()
    boards.append(render_text(g, symbols=False))

    rc, lines = cli("--text", "--ascii", "--no-color", "--seed", "1",
                    stdin=f"hint\n{src} {dst} {n}\nu\nq\n")
    assert rc == 0
    out = "\n".join(lines)
    assert lines[0] == "Soliterm - Klondike (text mode). Type h for help."
    assert lines[-1] == "bye"
    assert "\033[" not in out                         # --no-color
    assert not any(s in out for s in ("♠", "♥", "♦", "♣"))   # --ascii

    # the start board, the hint and the board again, the move, the undo
    expect = [without_status(boards[0]), "Hint: ", without_status(boards[0]),
              without_status(boards[1]), without_status(boards[2]), "bye"]
    pos = 0
    for chunk in expect:
        found = out.find(chunk, pos)
        assert found >= 0, f"missing, or out of order:\n{chunk}"
        pos = found + len(chunk)

    status = [line.split(" | ")[0] for line in lines if line.startswith("score=")]
    assert status == ["score=0 moves=0", "score=0 moves=0",
                      "score=0 moves=1", "score=0 moves=0"]
    assert sum(line.startswith("Hint: ") for line in lines) == 1


# -- entry points ----------------------------------------------------------------------

def test_python_m_soliterm_runs_the_command_line():
    # a child process, so point it at the checkout's src/ (the isolated
    # HOME from conftest is already in the environment it inherits)
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        p for p in (src, os.environ.get("PYTHONPATH")) if p))
    r = subprocess.run([sys.executable, "-m", "soliterm", "--list"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert [line.split()[0] for line in r.stdout.splitlines()[1:]] == GAME_ORDER
