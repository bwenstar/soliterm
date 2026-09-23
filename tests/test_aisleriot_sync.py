"""Sharing statistics with an installed GNOME AisleRiot through its keyfile.

The keyfile fixture writes into the test's own home, so the real one is
never touched.
"""

import json
import os

from soliterm import aisleriot as ar
from soliterm import store

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
    keyfile(KEYFILE)
    write_json(store.stats_path(), {"spider": stat(5, 30, 400, 1500),
                                    "golf": stat(2, 8, 120, 300)})
    write_json(store.config_path(), {"sync_aisleriot": True,
                                     "merged_into_aisleriot": False})
    store.record_result("klondike", won=True, seconds=100)   # triggers the merge
    assert ar.read_stat("spider.scm") == stat(25, 142, 400, 1966)
    assert ar.read_stat("golf.scm") == stat(2, 8, 120, 300)
    # the next result must not add the local totals again
    store.record_result("spider", won=False, seconds=10)
    assert ar.read_stat("spider.scm")["total"] == 143


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

