"""The command line: --list, --stats, --reset-stats and a scripted text session."""

import io
import os
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

import soliterm
from soliterm import aisleriot as ar
from soliterm import cli as cli_mod
from soliterm import history, saves, store, textmode
from soliterm.cli import main
from soliterm.deals import Deal
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


@pytest.mark.parametrize("args", [["--seed=-1"], ["--seed", "2147483648"]])
def test_a_deal_number_out_of_range_is_an_argument_error(capsys, args):
    with pytest.raises(SystemExit) as exc:
        main(["--text", *args])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--seed" in err and "run from 0 to 2147483647" in err


# -- --deal and --seed -----------------------------------------------------------------


def text_board(g):
    return without_status(render_text(g, symbols=False))


def play_briefly(cli, *args):
    rc, lines = cli("--text", "--ascii", "--no-color", *args, stdin="q\n")
    assert rc == 0
    return "\n".join(lines)


@pytest.mark.parametrize(
    "args, g",
    [
        (["--game", "golf", "--deal", "48213"], deal("golf", 48213)),
        (["--deal", "klondike:d3:48213"], deal("klondike", 48213, draw=3)),
        (["--deal=spider:s2:7"], deal("spider", 7, suits=2)),
        (["--deal", "FreeCell #617"], deal("freecell", 617)),
        (
            ["--game", "klondike", "--deal", "klondike:ru:5"],
            deal("klondike", 5, redeals="unlimited"),
        ),
    ],
)
def test_deal_takes_a_number_or_a_share_code(cli, args, g):
    assert text_board(g) in play_briefly(cli, *args)


def test_seed_still_works_but_is_not_in_the_help(cli, capsys):
    out = play_briefly(cli, "--game", "yukon", "--seed", "5")
    assert text_board(deal("yukon", 5)) in out
    assert text_board(deal("spider", 7, suits=2)) in play_briefly(cli, "--seed", "spider:s2:7")
    with pytest.raises(SystemExit):
        main(["--help"])
    help_text = capsys.readouterr().out
    assert "--deal" in help_text and "--seed" not in help_text


@pytest.mark.parametrize("flag", ["--seed", "--deal"])
def test_seed_0_still_works(cli, flag):
    assert text_board(deal("golf", 0)) in play_briefly(cli, "--game", "golf", flag, "0")


def test_seed_and_deal_together_are_refused(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--text", "--seed", "5", "--deal", "6"])
    assert exc.value.code == 2
    assert "argument --seed: not allowed with argument --deal" in capsys.readouterr().err


def test_game_must_match_the_share_code(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--text", "--game", "freecell", "--deal", "klondike:5"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--game freecell doesn't match the share code's game (klondike)" in err
    assert text_board(deal("klondike", 5)) in play_briefly(
        cli, "--game", "klondike", "--deal", "klondike:5"
    )


def test_a_bare_number_plays_the_last_game(cli):
    cfg = store.load_config()
    cfg["last_game"] = "golf"
    store.save_config(cfg)
    out = play_briefly(cli, "--deal", "5")
    assert out.startswith("Soliterm - Golf - Deal 5 ")
    assert text_board(deal("golf", 5)) in out


def test_a_bare_number_keeps_the_saved_options_and_a_code_does_not(cli):
    cfg = store.load_config()
    cfg["last_game"] = "spider"
    store.set_game_options(cfg, "spider", {"suits": 2})
    store.save_config(cfg)
    assert text_board(deal("spider", 5, suits=2)) in play_briefly(cli, "--deal", "5")
    # a code with no options means the standard ones
    out = play_briefly(cli, "--deal", "spider:5")
    assert text_board(deal("spider", 5)) in out
    assert text_board(deal("spider", 5, suits=2)) not in out
    # and playing it saves nothing
    assert store.game_options(store.load_config(), "spider") == {"suits": 2}


@pytest.mark.parametrize(
    "args, error",
    [
        (["--deal", "chess:5"], "argument --deal: no game called 'chess'"),
        (["--deal", "klondike"], "argument --deal: klondike needs a deal number too"),
        (["--seed", "12x"], "argument --seed: '12x' isn't a deal number"),
        (["--deal", "-5"], "argument --deal: deal numbers run from 0 to 2147483647, not -5"),
    ],
)
def test_a_bad_share_code_is_an_argument_error(capsys, args, error):
    with pytest.raises(SystemExit) as exc:
        main(["--text", *args])
    assert exc.value.code == 2
    assert error in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--deal", "--seed"])
def test_debug_info_still_prints_with_a_deal(cli, flag):
    rc, lines = cli("--debug-info", flag, "klondike:d3:5")
    assert rc == 0
    assert lines[0] == f"soliterm: {soliterm.__version__}"


# -- --draw and --suits ----------------------------------------------------------------


def test_draw_picks_klondike_for_this_run_only(cli):
    cfg = store.load_config()
    cfg["last_game"] = "golf"
    store.save_config(cfg)
    out = play_briefly(cli, "--draw", "3", "--deal", "5")
    assert out.startswith("Soliterm - Klondike - Deal 5 ")
    assert text_board(deal("klondike", 5, draw=3)) in out
    # over the saved options, which it leaves as they were
    cfg = store.load_config()
    store.set_game_options(cfg, "klondike", {"redeals": "none"})
    store.save_config(cfg)
    out = play_briefly(cli, "--game", "klondike", "--draw", "3", "--deal", "5")
    assert text_board(deal("klondike", 5, draw=3, redeals="none")) in out
    cfg = store.load_config()
    assert store.game_options(cfg, "klondike") == {"redeals": "none"}
    assert cfg["last_game"] == "golf"


def test_suits_picks_spider(cli):
    cfg = store.load_config()
    store.set_game_options(cfg, "spider", {"suits": 4})
    store.save_config(cfg)
    assert text_board(deal("spider", 7, suits=2)) in play_briefly(
        cli, "--suits", "2", "--seed", "7"
    )
    out = play_briefly(cli, "--game", "spider", "--suits", "1", "--deal", "7")
    assert text_board(deal("spider", 7, suits=1)) in out
    assert store.game_options(store.load_config(), "spider") == {"suits": 4}


def test_the_full_screen_game_is_handed_the_flag_options(terminal, monkeypatch):
    import soliterm.tui as tui_mod

    starts = []
    monkeypatch.setattr(tui_mod, "main", lambda start, **kw: starts.append(start) or 0)
    assert terminal("--draw", "3") == 0
    assert terminal("--suits", "2", "--deal", "9") == 0
    assert starts == [Deal("klondike", None, {"draw": 3}), Deal("spider", 9, {"suits": 2})]


@pytest.mark.parametrize(
    "args, error",
    [
        (["--game", "spider", "--draw", "3"], "--draw only goes with Klondike, not Spider"),
        (["--game", "klondike", "--suits", "2"], "--suits only goes with Spider, not Klondike"),
        (
            ["--game", "golf", "--deal", "5", "--draw", "1"],
            "--draw only goes with Klondike, not Golf",
        ),
    ],
)
def test_draw_with_spider_is_refused(capsys, args, error):
    with pytest.raises(SystemExit) as exc:
        main(["--text", *args])
    assert exc.value.code == 2
    assert f"soliterm: error: {error}\n" in capsys.readouterr().err


def test_draw_and_suits_together_are_refused(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--text", "--draw", "3", "--suits", "2"])
    assert exc.value.code == 2
    assert "error: --draw and --suits are for different games" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args, flag",
    [
        (["--deal", "klondike:5", "--draw", "3"], "--draw"),
        (["--seed", "klondike:d3:5", "--draw", "3"], "--draw"),
        (["--deal", "spider:5", "--suits", "2"], "--suits"),
    ],
)
def test_a_share_code_with_draw_is_refused(capsys, args, flag):
    with pytest.raises(SystemExit) as exc:
        main(["--text", *args])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert f"error: a share code carries its own options, so leave out {flag}" in err


@pytest.mark.parametrize("args", [["--draw", "2"], ["--suits", "3"], ["--draw", "three"]])
def test_draw_and_suits_take_only_the_values_the_game_has(capsys, args):
    with pytest.raises(SystemExit) as exc:
        main(["--text", *args])
    assert exc.value.code == 2
    assert f"argument {args[0]}: invalid" in capsys.readouterr().err


@pytest.mark.parametrize("name, key", [("draw", "klondike"), ("suits", "spider")])
def test_one_game_has_each_option_flag(capsys, name, key):
    # what lets --draw and --suits pick the game
    owners = [k for k in GAME_ORDER if name in GAMES[k].default_options()]
    assert owners == [key]
    with pytest.raises(SystemExit):
        main(["--help"])
    values = "|".join(str(v) for n, _, vals in GAMES[key].option_spec() if n == name for v in vals)
    assert f"--{name} {values}" in capsys.readouterr().out


def test_the_help_fits_a_40_column_terminal(capsys, monkeypatch):
    # argparse's usage wrapping has tripped over option groups before
    monkeypatch.setenv("COLUMNS", "40")
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--deal N|CODE" in capsys.readouterr().out


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
    assert lines[0] == "Game              Wins  Total   Win%    Best   Worst  Streak Longest"
    for key in GAME_ORDER:
        assert stats_row(lines, key) == ["0", "0", "N/A", "N/A", "N/A", "N/A", "N/A"]
    assert len(lines) == 1 + len(GAME_ORDER)


def test_stats_show_recorded_games(cli):
    store.record_result("klondike", True, 65)
    store.record_result("klondike", True, 200)
    store.record_result("klondike", False, 30)
    store.record_result("eightoff", False, 10)
    _rc, lines = cli("--stats")
    assert stats_row(lines, "klondike") == ["2", "3", "67%", "1:05", "3:20", "N/A", "N/A"]
    assert stats_row(lines, "eightoff") == ["0", "1", "0%", "N/A", "N/A", "N/A", "N/A"]
    assert stats_row(lines, "spider") == ["0", "0", "N/A", "N/A", "N/A", "N/A", "N/A"]


def test_stats_flag_prints_recent_games(cli, monkeypatch):
    days = iter(range(1, 13))
    monkeypatch.setattr(history, "now", lambda: f"2026-09-{next(days):02d}T14:05:11+10:00")
    g = deal("klondike", 1)
    g.moves = 131
    for _ in range(11):
        history.record(g, False, 543)
    g.moves = 1
    history.record(g, True, 142)
    _rc, lines = cli("--stats")
    assert stats_row(lines, "klondike") == ["1", "12", "8%", "2:22", "2:22", "1", "1"]
    at = lines.index("Recent games")
    assert lines[at - 1] == ""
    assert lines[at + 1 :] == [
        "2026-09-12 14:05  Klondike        won     2:22    1 move",
        *[
            f"2026-09-{day:02d} 14:05  Klondike        lost    9:03  131 moves"
            for day in range(11, 2, -1)
        ],
    ]


def test_stats_flag_leaves_recent_out_with_no_history(cli):
    store.record_result("golf", True, 50)  # counted, but not in the history
    _rc, lines = cli("--stats")
    assert stats_row(lines, "golf") == ["1", "1", "100%", "0:50", "0:50", "N/A", "N/A"]
    assert len(lines) == 1 + len(GAME_ORDER)


def test_stats_read_through_to_aisleriot(cli, keyfile):
    keyfile(f"[{ar.GAME_TO_SECTION['freecell']}]\nStatistic=3;4;75;300;\n")
    _rc, lines = cli("--stats")
    assert stats_row(lines, "freecell") == ["3", "4", "75%", "1:15", "5:00", "N/A", "N/A"]


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
    assert stats_row(lines, "golf") == ["0", "0", "N/A", "N/A", "N/A", "N/A", "N/A"]


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


def two_games():
    """Two games counted, so there are statistics and a history of them."""
    g = deal("golf", 1)
    g.deal()
    history.record(g, True, 50)
    history.record(g, False, 20)


def test_reset_stats_backs_up_and_clears_the_history(cli):
    two_games()
    before = Path(history.history_path()).read_text()
    rc, lines = cli("--reset-stats", "--yes")
    assert rc == 0
    assert f"Backup saved to {history.history_path()}.bak" in lines
    assert Path(history.history_path() + ".bak").read_text() == before
    assert history.games() == []
    assert store.get_stat("golf")["total"] == 0


@pytest.mark.parametrize("with_history", [True, False])
def test_the_reset_prompt_names_the_history(cli, with_history):
    if with_history:
        two_games()
    else:
        store.record_result("golf", True, 50)
    rc, _lines = cli("--reset-stats", stdin="no\n", tty=True)
    assert rc == 1
    also = ", and the history of your games" if with_history else ""
    assert f"This erases the statistics of all {len(GAME_ORDER)} games{also}.\n" in cli.err


def test_no_stats_and_no_history_means_nothing_to_clear(cli):
    rc, lines = cli("--reset-stats", "--yes")
    assert (rc, lines) == (0, ["There are no statistics to clear."])
    # a history on its own is still something to clear
    two_games()
    store.reset_stats()
    rc, lines = cli("--reset-stats", "--yes")
    assert rc == 0 and lines[-1] == "Statistics cleared."
    assert history.games() == []


def test_reset_leaves_saved_games_alone(cli):
    two_games()
    g = deal("klondike", 4)
    g.deal()
    assert saves.keep(g, 42)
    rc, _lines = cli("--reset-stats", "--yes")
    assert rc == 0
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 1}}


# -- --no-sync -------------------------------------------------------------------------


def test_no_sync_shows_and_clears_only_the_local_stats(cli, keyfile):
    path = keyfile(f"[{ar.GAME_TO_SECTION['freecell']}]\nStatistic=3;4;75;300;\n")
    before = path.read_text()
    rc, lines = cli("--no-sync", "--stats")
    assert stats_row(lines, "freecell") == ["0", "0", "N/A", "N/A", "N/A", "N/A", "N/A"]
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
    assert lines[0] == "Soliterm - Klondike - Deal 1 (text mode). Type h for help."
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
    shown = (boards[0], boards[0], boards[1], boards[2])
    assert status == [b.rpartition("\n")[2].split(" | ")[0] for b in shown]
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
    assert "new deal 6" in lines


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


# -- saved games in text mode ----------------------------------------------------------


@pytest.fixture
def stopped_clock(monkeypatch):
    """Text mode's clock, stopped, so the times it prints are known."""
    monkeypatch.setattr(textmode, "time", types.SimpleNamespace(monotonic=lambda: 1000.0))


def test_text_mode_saves_on_q_at_a_tty(cli, stopped_clock):
    rc, lines = cli("--text", stdin="d\nq\n", tty=True)
    assert rc == 0
    assert lines[-2:] == ["Saved your game (0:00, 1 move) for next time.", "bye"]
    assert saves.waiting() == {"klondike": {"seconds": 0, "moves": 1}}
    assert store.get_stat("klondike")["total"] == 0


def test_ctrl_d_at_a_tty_saves(cli, stopped_clock):
    rc, lines = cli("--text", stdin="d\n", tty=True)
    assert rc == 0
    assert lines[-1] == "Saved your game (0:00, 1 move) for next time."
    assert saves.waiting() == {"klondike": {"seconds": 0, "moves": 1}}
    assert store.get_stat("klondike")["total"] == 0


def test_text_mode_resumes_at_a_tty(cli, stopped_clock):
    g = deal("klondike", 7)
    g.deal()
    g.moves = 31
    assert saves.keep(g, 42)
    rc, lines = cli("--text", "--ascii", "--no-color", stdin="q\n", tty=True)
    assert rc == 0
    assert lines[0] == "Soliterm - Klondike - Deal 7 (text mode). Type h for help."
    assert lines[1] == "Resumed your Klondike game (0:42, 31 moves). Type n for a new deal."
    assert without_status(render_text(g, symbols=False)) in "\n".join(lines)
    # still under way without a move made, so it goes back as it was
    assert lines[-2:] == ["Saved your game (0:42, 31 moves) for next time.", "bye"]
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 31}}
    assert store.get_stat("klondike")["total"] == 0


@pytest.mark.parametrize(
    "chosen", [("--deal", "3"), ("--draw", "3")], ids=["a deal number", "an option"]
)
def test_a_chosen_deal_is_kept_but_never_resumed(cli, stopped_clock, chosen):
    _rc, lines = cli("--text", *chosen, stdin="d\nq\n", tty=True)
    assert lines[-2] == "Saved your game (0:00, 1 move) for next time."
    _rc, lines = cli("--text", *chosen, stdin="d\nd\nq\n", tty=True)
    assert lines[1] == "a saved Klondike game is waiting, so this one won't be kept"
    assert saves.waiting() == {"klondike": {"seconds": 0, "moves": 1}}
    assert store.get_stat("klondike")["total"] == 1
    assert cli.err == (
        "soliterm: a saved Klondike game was already waiting, so this one counted as lost\n"
    )


def test_piped_text_mode_neither_resumes_nor_saves(cli):
    g = deal("klondike", 7)
    g.deal()
    assert saves.keep(g, 42)
    _rc, lines = cli("--text", stdin="d\nq\n")
    assert not any(line.startswith(("Resumed", "Saved")) for line in lines)
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 1}}
    assert store.get_stat("klondike")["total"] == 1


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
    monkeypatch.setattr(tui_mod, "main", lambda *a, **kw: started.append("tui") or 0)
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


def test_the_full_screen_game_is_handed_the_deal(terminal, monkeypatch):
    import soliterm.tui as tui_mod

    starts = []
    monkeypatch.setattr(tui_mod, "main", lambda start, **kw: starts.append(start) or 0)
    assert terminal("--deal", "spider:s2:7") == 0
    assert terminal("--game", "golf", "--seed", "5") == 0
    assert terminal("--game", "golf") == 0
    assert terminal() == 0
    assert starts == [Deal("spider", 7, {"suits": 2}), Deal("golf", 5), Deal("golf"), None]


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


# -- leaving on a signal -----------------------------------------------------------------

# Windows has no SIGHUP, and os.kill there ends the process whatever the signal
posix_signals = pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals")


@pytest.fixture
def quieted(monkeypatch):
    """Record the calls to _quiet_output rather than let it point this
    process's output at devnull."""
    calls = []
    monkeypatch.setattr(cli_mod, "_quiet_output", lambda: calls.append(True))
    return calls


@posix_signals
def test_sighup_raises_keyboard_interrupt_and_quiets_output(quieted):
    with cli_mod._leave_on_signals():
        with pytest.raises(KeyboardInterrupt):
            os.kill(os.getpid(), signal.SIGHUP)
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    assert quieted == [True]


@posix_signals
def test_sigterm_leaves_output_alone(quieted):
    with cli_mod._leave_on_signals(), pytest.raises(KeyboardInterrupt):
        os.kill(os.getpid(), signal.SIGTERM)
    assert quieted == []


@posix_signals
def test_the_old_handlers_come_back(quieted):
    def mine(signum, frame):
        pass

    hup = signal.getsignal(signal.SIGHUP)
    before = signal.signal(signal.SIGTERM, mine)
    try:
        for fire in (False, True):
            with cli_mod._leave_on_signals():
                if fire:
                    with pytest.raises(KeyboardInterrupt):
                        os.kill(os.getpid(), signal.SIGHUP)
            assert signal.getsignal(signal.SIGTERM) is mine
            assert signal.getsignal(signal.SIGHUP) == hup
    finally:
        signal.signal(signal.SIGTERM, before)


@posix_signals
def test_a_second_signal_waits_for_the_save(quieted):
    saved = []
    with cli_mod._leave_on_signals():
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except KeyboardInterrupt:
            # the save the first signal set off
            os.kill(os.getpid(), signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGHUP)
            saved.append(True)
    assert saved == [True]
    assert quieted == []


@posix_signals
def test_a_hangup_exits_130_whatever_curses_made_of_it(monkeypatch, quieted):
    def hung_up(args, parser):
        try:
            os.kill(os.getpid(), signal.SIGHUP)
        except KeyboardInterrupt:
            pass  # the game is saved
        return 1  # as when curses can't put back a terminal that is gone

    monkeypatch.setattr(cli_mod, "_run", hung_up)
    assert main([]) == 130
    assert quieted == [True]
