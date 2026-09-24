"""Moving over from aisle-cli: its config and stats are copied into the
soliterm folders the first time, and the AisleRiot merge never runs twice.
"""

import json
import ntpath
import os
from pathlib import Path

import pytest

from soliterm import aisleriot as ar
from soliterm import migrate, store
from soliterm.cli import main

AR_KLONDIKE = "[klondike.scm]\nStatistic=10;40;120;900;\n"


def stat(wins, total, best, worst):
    return {"wins": wins, "total": total, "best": best, "worst": worst}


@pytest.fixture
def old(isolated_home):
    """Paths of aisle-cli's files, and put(name, obj_or_text) to write one."""
    paths = {"config": isolated_home / ".config" / "aisle-cli" / "config.json",
             "stats": isolated_home / ".local" / "share" / "aisle-cli" / "stats.json"}

    def put(name, value):
        path = paths[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value),
                        encoding="utf-8")
        return path

    put.paths = paths
    return put


def new_config():
    with open(store.config_path(), encoding="utf-8") as fh:
        return json.load(fh)


def new_stats():
    with open(store.stats_path(), encoding="utf-8") as fh:
        return json.load(fh)


def new_records():
    """The copied stats less the bookkeeping entry."""
    return {k: v for k, v in new_stats().items() if k != store.META_KEY}


def test_the_data_dirs_are_called_soliterm(isolated_home):
    assert store.config_path() == str(isolated_home / ".config" / "soliterm" / "config.json")
    assert store.stats_path() == str(isolated_home / ".local" / "share" / "soliterm"
                                     / "stats.json")


def test_aisle_cli_files_are_copied_over(old, capsys):
    cfg = {"last_game": "golf", "symbols": False, "sync_aisleriot": True,
           "merged_into_aisleriot": True, "options": {"klondike": {"draw": 3}}}
    stats = {"golf": stat(2, 3, 40, 90)}
    old("config", cfg)
    old("stats", stats)
    before = {name: path.read_bytes() for name, path in old.paths.items()}

    migrate.ensure()

    copied = new_config()
    moved = copied.pop("migrated_from")
    assert copied == cfg
    assert moved["app"] == "aisle-cli"
    assert len(moved["at"]) == 10 and moved["at"][4] == "-"    # an ISO date
    assert new_records() == stats
    # the old config's merge flag now sits with the stats
    assert new_stats()[store.META_KEY] == {"merged_into_aisleriot": True}
    # copied, not moved: the old version still has its files
    assert {name: path.read_bytes() for name, path in old.paths.items()} == before
    assert store.load_config()["last_game"] == "golf"
    assert store.game_options(store.load_config(), "klondike") == {"draw": 3}
    assert store.get_stat("golf") == stat(2, 3, 40, 90)
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 1 and "aisle-cli" in err[0] and store.config_dir() in err[0]


def test_the_migration_note_survives_a_config_save(old):
    old("config", {"last_game": "golf"})
    migrate.ensure()
    store.save_config(store.load_config())
    assert new_config()["migrated_from"]["app"] == "aisle-cli"


@pytest.mark.parametrize("present", ["config", "data"])
def test_nothing_is_copied_once_a_soliterm_dir_exists(old, capsys, present):
    old("config", {"last_game": "golf"})
    old("stats", {"golf": stat(2, 3, 40, 90)})
    os.makedirs(store.config_dir() if present == "config" else store.data_dir())
    migrate.ensure()
    assert not os.path.exists(store.config_path())
    assert not os.path.exists(store.stats_path())
    assert capsys.readouterr().err == ""


def test_nothing_happens_without_aisle_cli_files(isolated_home, capsys):
    os.makedirs(isolated_home / ".config" / "aisle-cli")
    migrate.ensure()
    assert not os.path.exists(store.config_dir())
    assert not os.path.exists(store.data_dir())
    assert capsys.readouterr().err == ""


def test_running_twice_copies_once(old, capsys):
    old("config", {"last_game": "golf"})
    old("stats", {"golf": stat(2, 3, 40, 90)})
    migrate.ensure()
    capsys.readouterr()
    first = (Path(store.config_path()).read_bytes(), Path(store.stats_path()).read_bytes())
    old("stats", {"golf": stat(9, 9, 9, 9)})    # the old version played on
    migrate.ensure()
    assert (Path(store.config_path()).read_bytes(),
            Path(store.stats_path()).read_bytes()) == first
    assert capsys.readouterr().err == ""


def test_old_stats_beside_the_keyfile_are_marked_merged(old, keyfile):
    # no config: only the stats, which the old version kept in step with
    # the keyfile
    keyfile(AR_KLONDIKE)
    old("stats", {"klondike": stat(10, 40, 120, 900)})
    migrate.ensure()
    assert new_stats()[store.META_KEY]["merged_into_aisleriot"] is True
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(10, 41, 120, 900)


def test_a_stale_old_merge_flag_does_not_merge_again(old, keyfile):
    # the old TUI could write a stale config with the flag back off
    keyfile(AR_KLONDIKE)
    old("config", {"sync_aisleriot": True, "merged_into_aisleriot": False})
    old("stats", {"klondike": stat(10, 40, 120, 900)})
    migrate.ensure()
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(10, 41, 120, 900)


def test_old_stats_from_before_aisleriot_are_merged_later_once(old, keyfile):
    old("stats", {"golf": stat(1, 1, 42, 42)})
    migrate.ensure()
    assert new_stats()[store.META_KEY]["merged_into_aisleriot"] is False
    keyfile("[golf.scm]\nStatistic=5;10;30;100;\n")    # AisleRiot turns up
    store.record_result("golf", won=False, seconds=5)
    assert ar.read_stat("golf.scm") == stat(6, 12, 30, 100)
    store.record_result("golf", won=False, seconds=5)
    assert ar.read_stat("golf.scm") == stat(6, 13, 30, 100)


def test_a_merge_marker_already_in_the_old_stats_is_kept(old, keyfile):
    keyfile(AR_KLONDIKE)
    meta = {"merged_into_aisleriot": True, "unsynced": {"golf": stat(1, 1, 42, 42)}}
    old("stats", {"klondike": stat(10, 40, 120, 900), store.META_KEY: meta})
    migrate.ensure()
    assert new_stats()[store.META_KEY] == meta


def test_damaged_old_files_are_copied_as_they_are(old, capsys):
    old("config", "{not json")
    old("stats", '{"golf": {"wins": 1,')
    migrate.ensure()
    assert Path(store.config_path()).read_text(encoding="utf-8") == "{not json"
    assert Path(store.stats_path()).read_text(encoding="utf-8") == '{"golf": {"wins": 1,'
    assert "aisle-cli" in capsys.readouterr().err
    # and then dealt with the usual way: kept aside, and a fresh start
    assert store.load_config()["last_game"] == "klondike"
    assert store.load_stats() == {}
    kept = [n for n in os.listdir(store.data_dir()) if ".corrupt-" in n]
    assert len(kept) == 1
    assert old.paths["config"].read_text() == "{not json"


def test_an_unreadable_old_file_is_tried_again_next_time(old, monkeypatch, capsys):
    old("stats", {"golf": stat(2, 3, 40, 90)})
    real_open = open

    def no_access(path, *args, **kwargs):
        if str(path) == str(old.paths["stats"]):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", no_access)
    migrate.ensure()
    monkeypatch.setattr("builtins.open", real_open)
    assert "Permission denied" in capsys.readouterr().err
    assert not os.path.exists(store.data_dir())
    migrate.ensure()
    assert new_records() == {"golf": stat(2, 3, 40, 90)}


def test_a_windows_home_comes_from_userprofile(old, tmp_path, monkeypatch):
    # Windows has no HOME; the home folder is USERPROFILE, which conftest
    # points at the test home. HOME goes somewhere else to tell them apart.
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var)
    monkeypatch.setenv("HOME", str(tmp_path / "not-home"))
    monkeypatch.setattr(os.path, "expanduser", ntpath.expanduser)
    old("stats", {"golf": stat(2, 3, 40, 90)})
    migrate.ensure()
    assert store.stats_path().startswith(os.environ["USERPROFILE"])
    assert new_records() == {"golf": stat(2, 3, 40, 90)}
    assert not os.path.exists(tmp_path / "not-home")


def test_the_command_line_copies_before_it_reads_anything(old, capsys):
    old("stats", {"golf": stat(2, 3, 40, 90)})
    assert main(["--stats"]) == 0
    out, err = capsys.readouterr()
    golf = [line for line in out.splitlines() if line.startswith("Golf ")]
    assert golf[0].split()[1:3] == ["2", "3"]
    assert "aisle-cli" in err
