"""Sharing statistics with an installed GNOME AisleRiot through its keyfile.

The keyfile fixture writes into the test's own home, so the real one is
never touched.
"""

import json
import os

import pytest

from soliterm import aisleriot as ar
from soliterm import store

# chmod can take read access away from us, but not from root, and not on
# Windows
needs_permissions = pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX file modes, not root")

KEYFILE = """\
[Aisleriot Config]
Recent=spider;klondike;
Theme=tigullio.svgz

[spider.scm]
Statistic=20;112;591;1966;
Options=2

[klondike.scm]
Statistic=3;10;200;400;
Options=1
"""

AR_KLONDIKE = "[klondike.scm]\nStatistic=10;40;120;900;\n"


def stat(wins, total, best, worst):
    return {"wins": wins, "total": total, "best": best, "worst": worst}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


# -- reading and writing the keyfile ---------------------------------------------

def test_write_stat_only_touches_the_statistic_line(keyfile):
    path = keyfile(KEYFILE)
    assert ar.available()
    assert ar.read_stat("spider.scm") == stat(20, 112, 591, 1966)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    assert path.read_text() == KEYFILE.replace("Statistic=20;112;591;1966;",
                                               "Statistic=21;113;480;1966;")


def test_a_spaced_statistic_key_is_replaced_not_duplicated(keyfile):
    path = keyfile("[spider.scm]\nStatistic = 20;112;591;1966;\nOptions=2\n")
    ar.write_stat("spider.scm", stat(21, 113, 580, 1966))
    out = path.read_text()
    assert out.count("Statistic") == 1
    assert "Options=2" in out
    assert ar.read_stat("spider.scm") == stat(21, 113, 580, 1966)


def test_writes_keep_trailing_blank_lines_and_are_idempotent(keyfile):
    path = keyfile("[spider.scm]\nStatistic=1;1;1;1;\nOptions=2\n\n\n")
    ar.write_stat("spider.scm", stat(2, 2, 2, 2))
    first = path.read_text()
    ar.write_stat("spider.scm", stat(2, 2, 2, 2))
    assert first.endswith("Options=2\n\n\n")
    assert path.read_text() == first


def test_writing_the_value_already_there_changes_nothing(keyfile):
    text = "[spider.scm]\nStatistic=1;1;1;1;\nOptions=2\n\n\n"
    path = keyfile(text)
    ar.write_stat("spider.scm", stat(1, 1, 1, 1))
    assert path.read_text() == text


def test_a_missing_section_is_appended(keyfile):
    path = keyfile("[Aisleriot Config]\nRecent=spider;\n")
    ar.write_stat("golf.scm", stat(1, 2, 3, 4))
    assert path.read_text() == ("[Aisleriot Config]\nRecent=spider;\n\n"
                                "[golf.scm]\nStatistic=1;2;3;4;\n")


def test_writes_leave_no_temp_files_behind(keyfile):
    path = keyfile(KEYFILE)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    assert os.listdir(path.parent) == ["aisleriot"]


def test_a_failed_write_leaves_the_keyfile_intact(keyfile, monkeypatch):
    path = keyfile(KEYFILE)

    def boom(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    assert ar.write_stat("spider.scm", stat(21, 113, 480, 1966)) is False
    assert path.read_text() == KEYFILE
    assert os.listdir(path.parent) == ["aisleriot"]


def test_rewriting_the_keyfile_keeps_its_mode(keyfile):
    path = keyfile(KEYFILE)
    os.chmod(path, 0o644)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    assert os.stat(path).st_mode & 0o777 == 0o644


@needs_permissions
def test_an_unreadable_keyfile_is_never_written(keyfile):
    path = keyfile(KEYFILE)
    os.chmod(path, 0)
    try:
        assert ar.write_stat("golf.scm", stat(1, 1, 42, 42)) is False
    finally:
        os.chmod(path, 0o644)
    assert path.read_text() == KEYFILE


# -- syncing with the store ----------------------------------------------------------

def test_our_game_sees_aisleriot_wins(keyfile):
    keyfile(KEYFILE)
    assert store.syncing()
    s = store.get_stat("spider")
    assert s["wins"] == 20 and s["total"] == 112


def test_our_results_land_in_the_keyfile(keyfile):
    keyfile(KEYFILE)
    new = store.record_result("spider", won=True, seconds=300)
    assert new == stat(21, 113, 300, 1966)
    assert ar.read_stat("spider.scm") == new
    # a loss only bumps the total
    store.record_result("klondike", won=False, seconds=99)
    assert ar.read_stat("klondike.scm") == stat(3, 11, 200, 400)


def test_local_history_is_merged_into_the_keyfile_once(keyfile):
    # games played before AisleRiot was around
    store.record_result("spider", won=True, seconds=400)
    store.record_result("spider", won=False, seconds=10)
    store.record_result("golf", won=True, seconds=120)
    keyfile(KEYFILE)
    store.record_result("klondike", won=True, seconds=100)   # triggers the merge
    assert ar.read_stat("spider.scm") == stat(21, 114, 400, 1966)
    assert ar.read_stat("golf.scm") == stat(1, 1, 120, 120)
    # the next result must not add the local totals again
    store.record_result("spider", won=False, seconds=10)
    assert ar.read_stat("spider.scm")["total"] == 115


def test_a_save_by_aisleriot_just_before_ours_is_kept(keyfile, monkeypatch):
    path = keyfile(AR_KLONDIKE)
    # sol finishes a won game and saves while we are recording a loss
    by_sol = "[Aisleriot Config]\nRecent=klondike;\n\n" + AR_KLONDIKE.replace("10;40;", "11;41;")
    real_write = ar._write_text
    raced = []

    def write_after_sol(*args, **kwargs):
        if not raced:
            raced.append(True)
            path.write_text(by_sol)
        return real_write(*args, **kwargs)

    monkeypatch.setattr(ar, "_write_text", write_after_sol)
    assert store.record_result("klondike", won=False, seconds=60) == stat(11, 42, 120, 900)
    assert path.read_text() == by_sol.replace("11;41;", "11;42;")


def test_a_stale_config_save_does_not_merge_again(keyfile):
    keyfile(AR_KLONDIKE)
    cfg = store.load_config()          # the TUI loads this once at start
    store.record_result("klondike", won=False, seconds=5)
    store.save_config(cfg)             # and saves it back on every game
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(10, 42, 120, 900)


def test_losing_the_config_does_not_merge_again(keyfile):
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    os.remove(store.config_path())
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(10, 42, 120, 900)


def test_the_merge_marker_is_kept_in_stats_json(keyfile):
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    with open(store.stats_path(), encoding="utf-8") as fh:
        assert json.load(fh)["_meta"]["merged_into_aisleriot"] is True


def test_a_reset_keeps_the_merge_marker(keyfile):
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    store.reset_stats()
    store.record_result("klondike", won=False, seconds=5)    # mirrored locally
    os.remove(store.config_path())
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(0, 2, 0, 0)


def test_stats_from_an_older_version_beside_a_keyfile_count_as_merged(keyfile):
    # older versions kept the flag in config.json only; their stats.json
    # next to a keyfile is a mirror of it already
    keyfile(AR_KLONDIKE)
    write_json(store.stats_path(), {"klondike": stat(10, 40, 120, 900),
                                    "golf": stat(1, 1, 30, 30)})
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(10, 41, 120, 900)
    assert ar.read_stat("golf.scm") is None


def test_the_old_config_flag_still_counts(keyfile):
    write_json(store.stats_path(), {"_meta": {"merged_into_aisleriot": False},
                                    "golf": stat(1, 1, 30, 30)})
    write_json(store.config_path(), {"merged_into_aisleriot": True})
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("golf.scm") is None


def test_saving_the_config_never_clears_the_old_merge_flag():
    write_json(store.config_path(), {"merged_into_aisleriot": True})
    cfg = store.load_config()
    cfg["merged_into_aisleriot"] = False
    store.save_config(cfg)
    with open(store.config_path(), encoding="utf-8") as fh:
        assert json.load(fh)["merged_into_aisleriot"] is True


@needs_permissions
def test_an_unreadable_keyfile_leaves_the_results_local(keyfile):
    path = keyfile(KEYFILE)
    os.chmod(path, 0)
    try:
        store.record_result("golf", won=True, seconds=42)
        assert store.get_stat("golf") == stat(1, 1, 42, 42)
        store.reset_stats()
    finally:
        os.chmod(path, 0o644)
    assert path.read_text() == KEYFILE
    assert any("can't read" in n for n in store.notices())


def test_a_game_missing_from_the_keyfile_builds_on_our_record(keyfile):
    path = keyfile(AR_KLONDIKE)
    store.record_result("golf", won=True, seconds=30)
    store.record_result("golf", won=False, seconds=5)
    path.write_text(AR_KLONDIKE)        # sol saves its own copy, without golf
    assert store.get_stat("golf") == stat(1, 2, 30, 30)
    assert store.record_result("golf", won=True, seconds=90) == stat(2, 3, 30, 90)
    assert ar.read_stat("golf.scm") == stat(2, 3, 30, 90)
    assert store.load_stats()["golf"] == stat(2, 3, 30, 90)


def test_a_deleted_keyfile_is_rebuilt_from_our_record(keyfile):
    path = keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    os.remove(path)
    assert store.record_result("klondike", won=True, seconds=100) == stat(11, 42, 100, 900)
    assert ar.read_stat("klondike.scm") == stat(11, 42, 100, 900)
    assert store.load_stats()["klondike"] == stat(11, 42, 100, 900)


def share(on):
    cfg = store.load_config()
    cfg["sync_aisleriot"] = on
    store.save_config(cfg)


def test_games_played_while_not_sharing_reach_aisleriot_later(keyfile):
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    share(False)
    store.record_result("klondike", won=True, seconds=100)
    store.record_result("golf", won=True, seconds=60)
    assert ar.read_stat("klondike.scm") == stat(10, 41, 120, 900)
    share(True)
    assert store.get_stat("klondike") == stat(11, 42, 100, 900)
    assert store.get_stat("golf") == stat(1, 1, 60, 60)
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(11, 43, 100, 900)
    assert ar.read_stat("golf.scm") == stat(1, 1, 60, 60)
    # and only the once
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(11, 44, 100, 900)
    assert ar.read_stat("golf.scm") == stat(1, 1, 60, 60)
    assert store.get_stat("golf") == stat(1, 1, 60, 60)


def test_games_from_both_sides_add_up_once_sharing_is_back(keyfile):
    path = keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    share(False)
    store.record_result("klondike", won=True, seconds=100)
    path.write_text(AR_KLONDIKE.replace("10;40;", "12;43;"))    # two more in sol
    share(True)
    assert store.get_stat("klondike") == stat(13, 44, 100, 900)


def test_stopping_while_catching_up_never_counts_a_game_twice(keyfile, monkeypatch):
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    share(False)
    store.record_result("klondike", won=True, seconds=100)
    share(True)
    real_update = ar.update_stat

    def update_then_stop(*args):
        real_update(*args)
        raise KeyboardInterrupt

    monkeypatch.setattr(ar, "update_stat", update_then_stop)
    with pytest.raises(KeyboardInterrupt):
        store.record_result("klondike", won=False, seconds=5)
    monkeypatch.setattr(ar, "update_stat", real_update)
    assert ar.read_stat("klondike.scm") == stat(11, 43, 100, 900)
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(11, 44, 100, 900)


def test_a_reset_forgets_games_not_yet_shared(keyfile):
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    share(False)
    store.record_result("klondike", won=True, seconds=100)
    share(True)
    store.reset_stats()
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(0, 1, 0, 0)


def test_reset_zeroes_only_the_games_we_manage(keyfile):
    keyfile("[Aisleriot Config]\nRecent=spider;\n\n"
            "[spider.scm]\nStatistic=20;112;591;1966;\n\n"
            "[poker.scm]\nStatistic=5;50;0;0;\n")
    assert store.reset_stats() == 1          # only spider had a record
    assert ar.read_stat("spider.scm") == stat(0, 0, 0, 0)
    assert ar.read_stat("poker.scm") == stat(5, 50, 0, 0)


def test_without_aisleriot_stats_stay_in_local_json():
    assert not ar.available()
    assert not store.syncing()
    s = store.record_result("freecell", won=True, seconds=120)
    assert s == stat(1, 1, 120, 120)
    assert store.get_stat("freecell")["wins"] == 1
    assert store.load_stats()["freecell"] == s
    assert not os.path.exists(ar.keyfile_path())

