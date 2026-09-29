"""--debug-info: the report a bug needs, made without writing, moving or
migrating a single file.
"""

import io
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import soliterm
from soliterm import cli, store
from soliterm.cli import main

LABELS = [
    "soliterm",
    "python",
    "platform",
    "terminal",
    "curses",
    "locale",
    "config",
    "stats",
    "aisleriot keyfile",
    "aisleriot program",
    "sharing",
    "aisle-cli files",
]

AR_KLONDIKE = "[klondike.scm]\nStatistic=10;40;120;900;\n"


def stat(wins, total, best, worst):
    return {"wins": wins, "total": total, "best": best, "worst": worst}


@pytest.fixture
def debug_info(monkeypatch, capsys):
    """Returns run(*args): the lines main(["--debug-info", *args]) prints,
    once it has checked that it ended well and said nothing on stderr.

    The terminal check is stubbed out, as curses reads the terminfo
    database only once per process: the real one would answer for
    whichever test got there first.
    """
    monkeypatch.setattr(cli, "_check_terminal", lambda: ("", ""))

    def run(*args):
        rc = main(["--debug-info", *args])
        out, err = capsys.readouterr()
        assert rc == 0
        assert err == ""
        return out.splitlines()

    return run


def value(lines, label):
    """What the report says after `label: `."""
    found = [line[len(label) + 2 :] for line in lines if line.startswith(f"{label}: ")]
    assert len(found) == 1, f"no single {label} line"
    return found[0]


def put(path, value):
    """Write a file under the test home, as JSON unless it is bytes or text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return path


def tilde(*parts):
    return os.path.join("~", *parts)


def config_file(home):
    return home / ".config" / "soliterm" / "config.json"


def stats_file(home):
    return home / ".local" / "share" / "soliterm" / "stats.json"


def old_files(home):
    return home / ".config" / "aisle-cli" / "config.json", (
        home / ".local" / "share" / "aisle-cli" / "stats.json"
    )


def snapshot(root):
    """Every path under `root` with its mtime, and each file's bytes."""
    seen = {".": (os.stat(root).st_mtime_ns, None)}
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(folder, name)
            data = None if name in dirs else Path(path).read_bytes()
            seen[os.path.relpath(path, root)] = (os.stat(path).st_mtime_ns, data)
    return seen


# -- what it says ----------------------------------------------------------------------


def test_debug_info_prints_every_line(debug_info):
    lines = debug_info()
    assert [line.split(": ", 1)[0] for line in lines] == LABELS
    assert lines[0] == f"soliterm: {soliterm.__version__}"


def test_debug_info_prints_home_as_a_tilde(debug_info, isolated_home, keyfile, monkeypatch):
    keyfile(AR_KLONDIKE)
    sol = str(isolated_home / "bin" / "sol")
    monkeypatch.setattr(shutil, "which", lambda name: sol if name == "sol" else None)
    lines = debug_info()
    assert str(isolated_home) not in "\n".join(lines)
    assert value(lines, "config") == (
        f"{tilde('.config', 'soliterm', 'config.json')} (not there yet)"
    )
    assert value(lines, "stats") == (
        f"{tilde('.local', 'share', 'soliterm', 'stats.json')} (not there yet)"
    )
    assert value(lines, "aisleriot keyfile") == (
        f"{tilde('.config', 'gnome-games', 'aisleriot')} (there)"
    )
    assert value(lines, "aisleriot program") == tilde("bin", "sol")
    assert value(lines, "aisle-cli files") == (
        f"{tilde('.config', 'aisle-cli', 'config.json')} (not there), "
        f"{tilde('.local', 'share', 'aisle-cli', 'stats.json')} (not there)"
    )


def test_debug_info_says_whether_the_full_screen_game_can_run(debug_info, monkeypatch):
    pytest.importorskip("curses")
    assert value(debug_info(), "curses").endswith(", the full-screen game can run here")
    why = "TERM=dumb can't move the cursor, so playing in text mode"
    monkeypatch.setattr(cli, "_check_terminal", lambda: (why, ""))
    assert value(debug_info(), "curses").endswith(f"; {why}")
    # and when it plays as a terminal type of its own choosing
    note = "TERM=xterm-kitty isn't known here, so playing as xterm-256color"
    monkeypatch.setattr(cli, "_check_terminal", lambda: ("", note))
    assert value(debug_info(), "curses").endswith(f", the full-screen game can run here; {note}")


@pytest.mark.parametrize(
    ("case", "why"),
    [
        ("no-sync", "off for this run (--no-sync)"),
        ("env", "off for this run (SOLITERM_NO_AISLERIOT is set)"),
        ("config", "off (sync_aisleriot is false in config.json)"),
        ("no aisleriot", "off (no AisleRiot here)"),
    ],
    ids=["no-sync", "env", "config", "no aisleriot"],
)
def test_debug_info_says_why_sharing_is_off(
    debug_info, isolated_home, keyfile, monkeypatch, case, why
):
    if case != "no aisleriot":
        keyfile(AR_KLONDIKE)  # so sharing would be on, but for the reason
    if case == "env":
        monkeypatch.setenv("SOLITERM_NO_AISLERIOT", "1")
    if case == "config":
        put(config_file(isolated_home), {"sync_aisleriot": False})
    args = ["--no-sync"] if case == "no-sync" else []
    assert value(debug_info(*args), "sharing") == f"{why}; merged: not yet; games waiting: 0"


def test_debug_info_counts_the_games_waiting_for_aisleriot(debug_info, isolated_home, keyfile):
    keyfile(AR_KLONDIKE)
    unsynced = {"klondike": stat(1, 2, 60, 60), "golf": stat(0, 1, 0, 0), "chess": stat(5, 5, 9, 9)}
    meta = {"merged_into_aisleriot": True, "unsynced": unsynced}
    put(stats_file(isolated_home), {"klondike": stat(11, 42, 60, 900), store.META_KEY: meta})
    # chess is a newer version's game, which only it can share
    assert value(debug_info(), "sharing") == "on; merged: yes; games waiting: 3"


@pytest.mark.parametrize(
    ("config", "stats", "merged"),
    [
        ({}, {store.META_KEY: {"merged_into_aisleriot": True}}, "yes"),
        ({"merged_into_aisleriot": True}, {}, "yes"),
        # the store counts stats from before the marker, beside a keyfile,
        # as merged; the report shows the markers only
        ({}, {"klondike": stat(1, 2, 60, 60)}, "not yet"),
    ],
    ids=["stats", "config", "older stats"],
)
def test_debug_info_shows_only_the_merge_markers(
    debug_info, isolated_home, keyfile, config, stats, merged
):
    keyfile(AR_KLONDIKE)
    put(config_file(isolated_home), config)
    put(stats_file(isolated_home), stats)
    assert value(debug_info(), "sharing") == f"on; merged: {merged}; games waiting: 0"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"], ids=["with a BOM", "UTF-16"])
def test_debug_info_reads_files_saved_with_a_bom_or_in_utf_16(
    debug_info, isolated_home, keyfile, encoding
):
    keyfile(AR_KLONDIKE)
    put(config_file(isolated_home), json.dumps({"sync_aisleriot": False}).encode(encoding))
    meta = {"merged_into_aisleriot": True, "unsynced": {"golf": stat(1, 1, 50, 50)}}
    put(stats_file(isolated_home), json.dumps({store.META_KEY: meta}).encode(encoding))
    lines = debug_info()
    assert value(lines, "config") == f"{tilde('.config', 'soliterm', 'config.json')} (there)"
    assert value(lines, "stats") == f"{tilde('.local', 'share', 'soliterm', 'stats.json')} (there)"
    assert value(lines, "sharing") == (
        "off (sync_aisleriot is false in config.json); merged: yes; games waiting: 1"
    )


# -- what it leaves alone ----------------------------------------------------------------


def new_home(home):
    """A first run: nothing there yet."""


def played_home(home):
    """Settings, stats with a game waiting for AisleRiot, and its keyfile."""
    put(config_file(home), {"last_game": "golf", "options": {"klondike": {"draw": 3}}})
    meta = {"merged_into_aisleriot": True, "unsynced": {"golf": stat(1, 1, 50, 50)}}
    put(stats_file(home), {"golf": stat(3, 5, 50, 90), store.META_KEY: meta})
    put(home / ".config" / "gnome-games" / "aisleriot", AR_KLONDIKE)


def old_home(home):
    """Only aisle-cli's files, which any other run would copy over."""
    old_config, old_stats = old_files(home)
    put(old_config, {"last_game": "spider"})
    put(old_stats, {"spider": stat(1, 4, 300, 300)})


def damaged_home(home):
    """Settings and stats the next run moves aside."""
    put(config_file(home), b'{"last_game": "golf"')
    put(stats_file(home), b"\x80 not UTF-8")
    put(home / ".config" / "gnome-games" / "aisleriot", AR_KLONDIKE)


@pytest.mark.parametrize(
    "fill",
    [new_home, played_home, old_home, damaged_home],
    ids=["new", "played", "from aisle-cli", "damaged"],
)
def test_debug_info_writes_nothing(debug_info, isolated_home, fill):
    fill(isolated_home)
    before = snapshot(isolated_home)
    debug_info()
    assert snapshot(isolated_home) == before


def test_debug_info_runs_before_migration(debug_info, isolated_home):
    old_home(isolated_home)
    lines = debug_info()
    assert value(lines, "aisle-cli files") == (
        f"{tilde('.config', 'aisle-cli', 'config.json')} (there), "
        f"{tilde('.local', 'share', 'aisle-cli', 'stats.json')} (there)"
    )
    assert not os.path.exists(store.config_dir())
    assert not os.path.exists(store.data_dir())
    # any other run would have copied them over
    assert main(["--list"]) == 0
    assert os.path.exists(store.config_path()) and os.path.exists(store.stats_path())


@pytest.mark.parametrize(
    "broken",
    [b'{"last_game": "golf"', b"[1, 2]", b"\x80 not UTF-8"],
    ids=["cut short", "not an object", "not UTF-8"],
)
def test_debug_info_leaves_a_broken_config_where_it_is(debug_info, isolated_home, broken):
    path = put(config_file(isolated_home), broken)
    lines = debug_info()
    assert value(lines, "config") == (
        f"{tilde('.config', 'soliterm', 'config.json')} "
        "(there but broken (the next run moves it aside))"
    )
    assert path.read_bytes() == broken
    assert os.listdir(path.parent) == ["config.json"]
    assert store.notices() == []


def test_debug_info_says_when_a_file_cant_be_read(debug_info, isolated_home):
    # a folder where the file should be can't be opened on any system
    stats_file(isolated_home).mkdir(parents=True)
    path = tilde(".local", "share", "soliterm", "stats.json")
    assert value(debug_info(), "stats").startswith(f"{path} (can't be read (")


@pytest.mark.parametrize(
    ("terminals", "shown"),
    [
        ({1: (120, 40), 0: (100, 30)}, "120x40"),
        ({0: (100, 30), 2: (90, 20)}, "100x30"),
        ({2: (90, 20)}, "90x20"),
        ({}, "size unknown"),
    ],
)
def test_debug_info_takes_the_size_from_the_first_terminal(
    debug_info, monkeypatch, terminals, shown
):
    # stdout first, then stdin, so the size still shows with stdout piped
    def size(fd):
        if fd not in terminals:
            raise OSError("not a terminal")
        return os.terminal_size(terminals[fd])

    monkeypatch.setattr(os, "get_terminal_size", size)
    assert f"; {shown}; " in value(debug_info(), "terminal")


def test_debug_info_prints_what_the_terminal_cant_show_as_escapes(monkeypatch):
    monkeypatch.setattr(cli, "_check_terminal", lambda: ("", ""))
    # a byte the locale couldn't decode, and a letter ASCII can't hold, in a
    # path, as the C locale has no way to put one in the environment
    monkeypatch.setenv("TERM_PROGRAM", "caf\udce9")
    monkeypatch.setattr(sys, "executable", "/opt/caf\u00e9/bin/python3")
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", out)
    assert main(["--debug-info"]) == 0
    out.flush()
    text = raw.getvalue().decode("ascii")
    assert "TERM_PROGRAM=caf\\udce9" in text
    assert "(/opt/caf\\xe9/bin/python3)" in text


# -- the command line --------------------------------------------------------------------


def test_debug_info_clashes_with_stats(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--stats", "--debug-info"])
    assert exc.value.code == 2
    assert "argument --debug-info: not allowed with argument --stats" in capsys.readouterr().err
