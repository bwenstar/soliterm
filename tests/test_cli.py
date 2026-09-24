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
from soliterm.cli import main
from soliterm.engine import GAME_ORDER, GAMES
from soliterm.textmode import render_text

from helpers import deal


class TtyInput(io.StringIO):
    """Typed input: stdin that says it is a terminal."""

    def isatty(self):
        return True


@pytest.fixture
def cli(monkeypatch, capsys):
    """Returns run(*args, stdin="", tty=False) -> (exit code, stdout lines).

    What went to stderr is left in run.err.
    """

    def run(*args, stdin="", tty=False):
        monkeypatch.setattr(sys, "stdin", (TtyInput if tty else io.StringIO)(stdin))
        rc = main(list(args))
        out, run.err = capsys.readouterr()
        return rc, out.splitlines()

    run.err = ""
    return run


def stats_row(lines, key):
    """The numbers on a game's --stats line, after its name."""
    name = GAMES[key].name
    row = [line for line in lines if line.startswith(name + " ")]
    assert len(row) == 1, f"no single stats line for {name}"
    return row[0][len(name) :].split()


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


@pytest.mark.parametrize("args", [["--seed", "-5"], ["--seed=-1"]])
def test_a_negative_seed_is_an_argument_error(capsys, args):
    with pytest.raises(SystemExit) as exc:
        main(["--text", *args])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--seed" in err and "0 or more" in err


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
    _rc, lines = cli("--stats")
    assert stats_row(lines, "klondike") == ["2", "3", "67%", "1:05", "3:20"]
    assert stats_row(lines, "eightoff") == ["0", "1", "0%", "N/A", "N/A"]
    assert stats_row(lines, "spider") == ["0", "0", "N/A", "N/A", "N/A"]


def test_stats_read_through_to_aisleriot(cli, keyfile):
    keyfile(f"[{ar.GAME_TO_SECTION['freecell']}]\nStatistic=3;4;75;300;\n")
    _rc, lines = cli("--stats")
    assert stats_row(lines, "freecell") == ["3", "4", "75%", "1:15", "5:00"]


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX file modes, not root"
)
def test_stats_with_an_unreadable_keyfile_say_so(keyfile, capsys):
    path = keyfile(f"[{ar.GAME_TO_SECTION['golf']}]\nStatistic=3;4;75;300;\n")
    os.chmod(path, 0)
    try:
        assert main(["--stats"]) == 0
    finally:
        os.chmod(path, 0o644)
    err = capsys.readouterr().err
    assert "can't read" in err and ar.keyfile_path() in err


# -- --reset-stats ---------------------------------------------------------------------


def test_reset_stats_clears_local_statistics(cli):
    store.record_result("golf", True, 50)
    store.record_result("yukon", False, 50)
    rc, lines = cli("--reset-stats", "--yes")
    assert rc == 0
    assert any("cleared" in line.lower() for line in lines)
    for key in GAME_ORDER:
        assert store.get_stat(key)["total"] == 0
    rc, lines = cli("--stats")
    assert stats_row(lines, "golf") == ["0", "0", "N/A", "N/A", "N/A"]


def test_reset_stats_clears_the_shared_aisleriot_record(cli, keyfile):
    path = keyfile(
        "[Aisleriot Config]\nTheme=tigullio.svgz\n\n"
        f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n"
    )
    rc, lines = cli("--reset-stats", "--yes")
    assert rc == 0
    assert any("cleared" in line.lower() for line in lines)
    assert store.get_stat("canfield")["total"] == 0
    assert ar.read_stat(ar.GAME_TO_SECTION["canfield"])["total"] == 0
    assert "Theme=tigullio.svgz" in path.read_text()


@pytest.mark.parametrize("flag", ["--r", "--reset", "--reset-stat"])
def test_reset_stats_takes_no_abbreviation(cli, flag):
    store.record_result("golf", True, 50)
    with pytest.raises(SystemExit) as exc:
        cli(flag)
    assert exc.value.code == 2
    assert store.get_stat("golf")["total"] == 1


def test_reset_stats_and_stats_together_is_an_error(cli):
    store.record_result("golf", True, 50)
    with pytest.raises(SystemExit) as exc:
        cli("--stats", "--reset-stats")
    assert exc.value.code == 2
    assert store.get_stat("golf")["total"] == 1


def test_reset_stats_without_a_terminal_wants_yes(cli, keyfile):
    path = keyfile(f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n")
    store.record_result("golf", True, 50)
    before = path.read_text()
    rc, _lines = cli("--reset-stats", stdin="yes\n")
    assert rc == 2
    assert "--yes" in cli.err
    assert path.read_text() == before
    assert store.get_stat("golf")["total"] == 1
    assert not os.path.exists(store.stats_path() + ".bak")


def test_reset_stats_on_a_terminal_asks_for_yes(cli, keyfile):
    keyfile(f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n")
    rc, _lines = cli("--reset-stats", stdin="yes\n", tty=True)
    assert rc == 0
    assert "yes" in cli.err and ar.keyfile_path() in cli.err
    assert ar.read_stat(ar.GAME_TO_SECTION["canfield"])["total"] == 0


@pytest.mark.parametrize("answer", ["y\n", "no\n", "\n", ""])
def test_reset_stats_on_a_terminal_clears_nothing_without_yes(cli, keyfile, answer):
    path = keyfile(f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n")
    before = path.read_text()
    rc, lines = cli("--reset-stats", stdin=answer, tty=True)
    assert rc == 1
    assert any("nothing" in line.lower() for line in lines)
    assert path.read_text() == before
    assert not os.path.exists(str(path) + ".soliterm-bak")


def test_reset_stats_backs_up_both_files_first(cli, keyfile):
    text = (
        "[Aisleriot Config]\nTheme=tigullio.svgz\n\n"
        f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n"
    )
    path = keyfile(text)
    store.record_result("golf", True, 50)
    shared, local = path.read_text(), Path(store.stats_path()).read_text()
    rc, lines = cli("--reset-stats", "--yes")
    assert rc == 0
    kept = Path(str(path) + ".soliterm-bak")
    assert kept.name == "aisleriot.soliterm-bak"
    assert kept.read_text() == shared
    assert Path(store.stats_path() + ".bak").read_text() == local
    out = "\n".join(lines)
    assert str(kept) in out and store.stats_path() + ".bak" in out


def test_reset_stats_clears_nothing_when_the_backup_fails(cli, keyfile, monkeypatch):
    path = keyfile(f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n")
    before = path.read_text()

    def no_room(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(store, "_copy_file", no_room)
    rc, _lines = cli("--reset-stats", "--yes")
    assert rc == 1
    assert "nothing was cleared" in cli.err
    assert path.read_text() == before


def test_reset_stats_twice_keeps_the_first_backup(cli, keyfile):
    path = keyfile(f"[{ar.GAME_TO_SECTION['canfield']}]\nStatistic=2;9;100;400;\n")
    shared = path.read_text()
    cli("--reset-stats", "--yes")
    rc, lines = cli("--reset-stats", "--yes")
    assert rc == 0
    assert any("no statistics" in line.lower() for line in lines)
    assert Path(str(path) + ".soliterm-bak").read_text() == shared


# -- --no-sync -------------------------------------------------------------------------


def test_no_sync_shows_and_clears_only_the_local_stats(cli, keyfile):
    path = keyfile(f"[{ar.GAME_TO_SECTION['freecell']}]\nStatistic=3;4;75;300;\n")
    before = path.read_text()
    rc, lines = cli("--no-sync", "--stats")
    assert stats_row(lines, "freecell") == ["0", "0", "N/A", "N/A", "N/A"]
    store.record_result("golf", True, 50)
    rc, lines = cli("--no-sync", "--reset-stats", "--yes")
    assert rc == 0
    assert path.read_text() == before
    assert not os.path.exists(str(path) + ".soliterm-bak")
    assert store.load_stats().get("golf") is None


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

    rc, lines = cli(
        "--text", "--ascii", "--no-color", "--seed", "1", stdin=f"hint\n{src} {dst} {n}\nu\nq\n"
    )
    assert rc == 0
    out = "\n".join(lines)
    assert lines[0] == "Soliterm - Klondike (text mode). Type h for help."
    assert lines[-1] == "bye"
    assert "\033[" not in out  # --no-color
    assert not any(s in out for s in ("♠", "♥", "♦", "♣"))  # --ascii

    # the start board, the hint and the board again, the move, the undo
    expect = [
        without_status(boards[0]),
        "Hint: ",
        without_status(boards[0]),
        without_status(boards[1]),
        without_status(boards[2]),
        "bye",
    ]
    pos = 0
    for chunk in expect:
        found = out.find(chunk, pos)
        assert found >= 0, f"missing, or out of order:\n{chunk}"
        pos = found + len(chunk)

    status = [line.split(" | ")[0] for line in lines if line.startswith("score=")]
    assert status == ["score=0 moves=0", "score=0 moves=0", "score=0 moves=1", "score=0 moves=0"]
    assert sum(line.startswith("Hint: ") for line in lines) == 1


def test_the_text_hint_names_cards_with_the_boards_suit_symbols(cli):
    _rc, lines = cli("--text", "--no-color", "--seed", "1", stdin="hint\nq\n")
    hint = next(line for line in lines if line.startswith("Hint: "))
    assert any(s in hint for s in ("♠", "♥", "♦", "♣"))


def test_n_in_text_mode_deals_a_new_hand_under_seed(cli):
    first = without_status(render_text(deal("klondike", 5), symbols=False))
    _rc, lines = cli(
        "--text", "--ascii", "--no-color", "--game", "klondike", "--seed", "5", stdin="n\nq\n"
    )
    out = "\n".join(lines)
    assert out.count(first) == 1
    assert "new deal" in lines


def test_text_mode_survives_a_bad_option_in_the_config(cli):
    cfg = store.load_config()
    store.set_game_options(cfg, "spider", {"suits": 3})
    store.save_config(cfg)
    rc, lines = cli("--text", "--game", "spider", stdin="q\n")
    assert rc == 0
    assert lines[-1] == "bye"


@pytest.mark.parametrize("suits", [1, 2])
def test_a_saved_spider_suits_choice_beats_the_default(cli, suits):
    cfg = store.load_config()
    store.set_game_options(cfg, "spider", {"suits": suits})
    store.save_config(cfg)
    _rc, lines = cli(
        "--text", "--ascii", "--no-color", "--game", "spider", "--seed", "1", stdin="q\n"
    )
    out = "\n".join(lines)
    board = deal("spider", 1, suits=suits)
    assert without_status(render_text(board, symbols=False)) in out
    assert without_status(render_text(deal("spider", 1), symbols=False)) not in out


# -- the full-screen game or text mode -------------------------------------------------

# the terminal types the stubbed terminfo knows: xterm can draw the game,
# while dumb and a glass teletype can't move the cursor
TERMINFO = {"xterm": {"cup": b"\x1b[%i%p1%d;%p2%dH"}, "dumb": {}, "glass": {}}


@pytest.fixture
def terminal(monkeypatch):
    """Returns run(*args): main() as if on a terminal, with both front ends
    stubbed out. run.started lists the ones started ("tui" or "text").

    curses looks the terminal type up in TERMINFO, not the real database:
    it only does so once per process, and the database may not be there.
    """
    import curses

    import soliterm.cli as cli_mod
    import soliterm.tui as tui_mod

    started = []
    looked_up = []

    def setupterm(term=None, fd=-1):
        if term not in TERMINFO:
            raise curses.error("setupterm: could not find terminal")
        looked_up[:] = [term]

    monkeypatch.setattr(curses, "setupterm", setupterm)
    # the lambda reads looked_up[0] when it is called, not now
    monkeypatch.setattr(curses, "tigetstr", lambda cap: TERMINFO[looked_up[0]].get(cap))  # noqa: PLW0108
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(tui_mod, "main", lambda **kw: started.append("tui") or 0)
    monkeypatch.setattr(cli_mod, "run_text", lambda *a, **kw: started.append("text") or 0)

    def run(*args):
        # at call time: pytest hands the test a new sys.stdout
        monkeypatch.setattr(sys, "stdin", TtyInput(""))
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        return main(list(args))

    run.started = started
    return run


def failing_tui_import(monkeypatch, exc):
    """Make `from . import tui` in the command line raise `exc`."""
    import builtins

    real_import = builtins.__import__

    def fake(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 1 and fromlist and "tui" in fromlist:
            raise exc
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake)


def test_a_terminal_gets_the_full_screen_game(terminal, capsys):
    assert terminal("--game", "golf") == 0
    assert terminal.started == ["tui"]
    assert capsys.readouterr().err == ""


def test_without_curses_text_mode_says_why(terminal, monkeypatch, capsys):
    # the front end is loaded afresh, and its own `import curses` fails
    import soliterm

    monkeypatch.delattr(soliterm, "tui")
    for name in [m for m in sys.modules if m.split(".")[:2] == ["soliterm", "tui"]]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "curses", None)
    assert terminal("--game", "golf") == 0
    assert terminal.started == ["text"]
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "text mode" in err and "curses" in err
    assert "windows-curses" not in err


def test_without_curses_on_windows_suggests_windows_curses(terminal, monkeypatch, capsys):
    exc = ModuleNotFoundError("No module named '_curses'", name="_curses")
    failing_tui_import(monkeypatch, exc)
    monkeypatch.setattr(os, "name", "nt")
    try:
        terminal("--game", "golf")
    finally:
        monkeypatch.setattr(os, "name", "posix")
    assert terminal.started == ["text"]
    err = capsys.readouterr().err
    assert "pip install windows-curses" in err and "text mode" in err


def test_a_module_missing_from_the_package_is_named(terminal, monkeypatch, capsys):
    exc = ModuleNotFoundError("No module named 'soliterm.camo'", name="soliterm.camo")
    failing_tui_import(monkeypatch, exc)
    assert terminal("--game", "golf") == 0
    assert terminal.started == ["text"]
    err = capsys.readouterr().err
    assert "soliterm.camo" in err and "windows-curses" not in err


def test_a_bug_in_the_full_screen_game_is_not_hidden(terminal, monkeypatch):
    failing_tui_import(monkeypatch, NameError("name 'curses' is not defined"))
    with pytest.raises(NameError):
        terminal("--game", "golf")
    assert terminal.started == []


@pytest.mark.parametrize("term", [None, "", "dumb"])
def test_without_a_terminal_type_text_mode_says_why(terminal, monkeypatch, capsys, term):
    if term is None:
        monkeypatch.delenv("TERM")
    else:
        monkeypatch.setenv("TERM", term)
    assert terminal("--game", "golf") == 0
    assert terminal.started == ["text"]
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "TERM" in err and "text mode" in err


def test_an_unknown_terminal_type_means_text_mode(terminal, monkeypatch, capsys):
    # say, ssh from a terminal the far end has no terminfo entry for
    monkeypatch.setenv("TERM", "xterm-kitty")
    assert terminal("--game", "golf") == 0
    assert terminal.started == ["text"]
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "TERM=xterm-kitty" in err and "text mode" in err


def test_a_terminal_that_cannot_move_the_cursor_means_text_mode(terminal, monkeypatch, capsys):
    monkeypatch.setenv("TERM", "glass")
    assert terminal("--game", "golf") == 0
    assert terminal.started == ["text"]
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "TERM=glass" in err and "text mode" in err


def test_the_windows_console_needs_no_terminal_type(terminal, monkeypatch, capsys):
    monkeypatch.delenv("TERM")
    monkeypatch.setattr(os, "name", "nt")
    try:
        terminal("--game", "golf")
    finally:
        monkeypatch.setattr(os, "name", "posix")
    assert terminal.started == ["tui"]
    assert capsys.readouterr().err == ""


def test_curses_itself_turns_down_an_unknown_terminal_type():
    # the real terminfo lookup, in a process of its own
    code = "from soliterm import cli; print(cli._terminal_problem())"
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=dict(child_env(), TERM="no-such-terminal"),
        check=False,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "TERM=no-such-terminal" in r.stdout


# -- entry points ----------------------------------------------------------------------


def child_env():
    """The environment for a child process: this one (with the isolated
    HOME from conftest), pointed at the checkout's src/."""
    src = str(Path(__file__).resolve().parents[1] / "src")
    return dict(
        os.environ, PYTHONPATH=os.pathsep.join(p for p in (src, os.environ.get("PYTHONPATH")) if p)
    )


def test_python_m_soliterm_runs_the_command_line():
    r = subprocess.run(
        [sys.executable, "-m", "soliterm", "--list"],
        capture_output=True,
        text=True,
        env=child_env(),
        check=False,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert [line.split()[0] for line in r.stdout.splitlines()[1:]] == GAME_ORDER


@pytest.mark.parametrize(
    "args,stdin",
    [
        (["--text", "--ascii", "--seed", "1"], "p\n" * 200),
        (["--list"], ""),
        (["--stats"], ""),
    ],
    ids=["text", "list", "stats"],
)
def test_output_to_a_reader_that_went_away_ends_quietly(args, stdin):
    # like piping into head: the far end of stdout is already closed
    r, w = os.pipe()
    os.close(r)
    try:
        p = subprocess.run(
            [sys.executable, "-m", "soliterm", *args],
            input=stdin,
            stdout=w,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env(),
            check=False,
            timeout=60,
        )
    finally:
        os.close(w)
    assert p.stderr == ""
    assert p.returncode == 141
