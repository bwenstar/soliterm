"""Sharing statistics with an installed GNOME AisleRiot through its keyfile.

The keyfile fixture writes into the test's own home, so the real one is
never touched.
"""

import io
import json
import os
import shutil
import sys

import pytest

from soliterm import aisleriot as ar
from soliterm import cli, store, textmode
from soliterm.engine import new_solitaire
from soliterm.tui.app import START_MESSAGE, App

from helpers import FakeScr, stats_json_in_use

# chmod can take read access away from us, but not from root, and not on
# Windows
needs_permissions = pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX file modes, not root"
)

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
    assert path.read_text() == KEYFILE.replace(
        "Statistic=20;112;591;1966;", "Statistic=21;113;480;1966;"
    )


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
    assert path.read_text() == (
        "[Aisleriot Config]\nRecent=spider;\n\n[golf.scm]\nStatistic=1;2;3;4;\n"
    )


def test_a_crlf_keyfile_keeps_its_line_endings(keyfile):
    path = keyfile(KEYFILE.replace("\n", "\r\n"))
    assert ar.read_stat("spider.scm") == stat(20, 112, 591, 1966)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    ar.write_stat("golf.scm", stat(1, 1, 42, 42))
    want = (
        KEYFILE.replace("20;112;591;1966", "21;113;480;1966")
        + "\n[golf.scm]\nStatistic=1;1;42;42;\n"
    )
    assert path.read_bytes() == want.replace("\n", "\r\n").encode()


# GLib ends a line at "\n" only; the other breaks str.splitlines() knows are
# ordinary characters inside a value
ODD_BREAKS = "\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"


def test_only_newlines_end_a_line(keyfile):
    keyfile(
        "[Aisleriot Config]\n"
        "Note=a" + "".join(b + "[golf.scm]" + b + "Statistic=9;9;9;9;" for b in ODD_BREAKS) + "\n"
    )
    assert ar.read_stat("golf.scm") is None


def test_odd_line_breaks_in_other_values_are_kept(keyfile):
    text = f"[Aisleriot Config]\nTheme=a{ODD_BREAKS}b\n\n[spider.scm]\nStatistic=1;1;1;1;\n"
    path = keyfile(text)
    ar.write_stat("spider.scm", stat(2, 2, 2, 2))
    ar.write_stat("golf.scm", stat(1, 1, 42, 42))
    assert path.read_bytes().decode("utf-8") == (
        text.replace("1;1;1;1;", "2;2;2;2;") + "\n[golf.scm]\nStatistic=1;1;42;42;\n"
    )


def test_a_keyfile_that_is_not_utf8_is_kept_byte_for_byte(keyfile):
    path = keyfile("")
    raw = (
        b"[Aisleriot Config]\nTheme=caf\xe9.svgz\n\n"
        b"[spider.scm]\nStatistic=20;112;591;1966;\nName=\xff\xfe\n"
    )
    path.write_bytes(raw)
    assert store.get_stat("spider") == stat(20, 112, 591, 1966)
    store.record_result("spider", won=False, seconds=5)
    assert path.read_bytes() == raw.replace(b"20;112;", b"20;113;")


# -- reading the keyfile the way AisleRiot (GLib) does -----------------------------


def test_the_last_statistic_in_a_section_is_the_one_read_and_written(keyfile):
    path = keyfile("[spider.scm]\nStatistic=1;1;1;1;\nStatistic=20;112;591;1966;\n")
    assert ar.read_stat("spider.scm") == stat(20, 112, 591, 1966)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    assert path.read_text() == "[spider.scm]\nStatistic=1;1;1;1;\nStatistic=21;113;480;1966;\n"


def test_a_section_written_twice_counts_as_one(keyfile):
    path = keyfile(
        "[spider.scm]\nStatistic=1;1;1;1;\n\n[golf.scm]\nStatistic=2;2;2;2;\n\n"
        "[spider.scm]\nStatistic=20;112;591;1966;\nOptions=2\n"
    )
    assert ar.read_stat("spider.scm") == stat(20, 112, 591, 1966)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    assert path.read_text().count("Statistic=1;1;1;1;") == 1
    assert ar.read_stat("spider.scm") == stat(21, 113, 480, 1966)


def test_a_statistic_in_an_earlier_copy_of_the_section_still_counts(keyfile):
    path = keyfile("[spider.scm]\nStatistic=20;112;591;1966;\n\n[spider.scm]\nOptions=2\n")
    assert ar.read_stat("spider.scm") == stat(20, 112, 591, 1966)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    assert path.read_text() == (
        "[spider.scm]\nStatistic=21;113;480;1966;\n\n[spider.scm]\nOptions=2\n"
    )


@pytest.mark.parametrize(
    "value, want",
    [
        ("20;112;591;1966", stat(20, 112, 591, 1966)),  # the last ; is optional
        ("  +20;0112; 591;1966 ;", stat(20, 112, 591, 1966)),
        ("20;112;591;1966;5;", stat(0, 0, 0, 0)),  # AisleRiot wants four
        ("20;112;591;", stat(0, 0, 0, 0)),
        ("20;;591;1966;", stat(0, 0, 0, 0)),
        ("20;112;591;1966;   ", stat(0, 0, 0, 0)),  # a fifth, blank value
        ("2_0;112;591;1966;", stat(0, 0, 0, 0)),
        ("0x14;112;591;1966;", stat(0, 0, 0, 0)),
        ("20;112;591;2147483648;", stat(0, 0, 0, 0)),
        ("20;112;5.9;1966;", stat(0, 0, 0, 0)),
        ("20; ;591;1966 x;", stat(20, 0, 591, 1966)),  # strtol, then a space: fine
        ("20;112;\\s591;1966;", stat(20, 112, 591, 1966)),  # \s is an escaped space
        ("20;112;591\\;1966;", stat(0, 0, 0, 0)),  # \; is a ; inside a value
        ("20;112;591;1966\\q;", stat(0, 0, 0, 0)),  # no such escape
        ("20;112;591;1966\\", stat(0, 0, 0, 0)),
    ],
)
def test_a_statistic_value_reads_as_glib_reads_it(keyfile, value, want):
    keyfile(f"[spider.scm]\nStatistic={value}\n")
    assert ar.read_stat("spider.scm") == want


def test_a_last_line_with_no_newline_reads_and_writes_as_in_glib(keyfile):
    # GLib only drops the "\r" of a "\r\n", so on a last line with no
    # newline after it the "\r" is part of the value
    path = keyfile("[spider.scm]\r\nStatistic=20;112;591;1966;\r")
    assert ar.read_stat("spider.scm") == stat(0, 0, 0, 0)
    ar.write_stat("spider.scm", stat(21, 113, 480, 1966))
    assert path.read_bytes() == b"[spider.scm]\r\nStatistic=21;113;480;1966;"
    path = keyfile("[golf.scm]\r\nOptions=2")
    ar.write_stat("golf.scm", stat(1, 1, 42, 42))
    ar.write_stat("spider.scm", stat(2, 2, 2, 2))
    assert path.read_bytes() == (
        b"[golf.scm]\r\nStatistic=1;1;42;42;\r\nOptions=2\r\n"
        b"\r\n[spider.scm]\r\nStatistic=2;2;2;2;\r\n"
    )


@pytest.mark.parametrize(
    "value, want",
    [
        ("5;9;6000;6000;", stat(5, 9, 6000, 6000)),
        ("5;9;6001;6001;", stat(5, 9, 0, 0)),
        ("5;9;120;21645;", stat(5, 9, 120, 0)),
        ("5;9;-60;900;", stat(5, 9, 0, 900)),
    ],
)
def test_a_time_over_100_minutes_reads_as_no_time(keyfile, value, want):
    # as AisleRiot reads it: its Statistics window shows N/A
    keyfile(f"[spider.scm]\nStatistic={value}\n")
    assert ar.read_stat("spider.scm") == want
    assert store.get_stat("spider") == want


def test_a_statistic_aisleriot_reads_as_zeros_counts_from_zero(keyfile):
    path = keyfile("[spider.scm]\nStatistic=20;112;591;1966;5;\nOptions=2\n")
    assert store.get_stat("spider") == stat(0, 0, 0, 0)
    store.record_result("spider", won=False, seconds=5)
    assert path.read_text() == "[spider.scm]\nStatistic=0;1;0;0;\nOptions=2\n"


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


@pytest.mark.skipif(os.name != "posix", reason="needs POSIX file modes")
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
    store.record_result("klondike", won=True, seconds=100)  # triggers the merge
    assert ar.read_stat("spider.scm") == stat(21, 114, 400, 1966)
    assert ar.read_stat("golf.scm") == stat(1, 1, 120, 120)
    # the next result must not add the local totals again
    store.record_result("spider", won=False, seconds=10)
    assert ar.read_stat("spider.scm")["total"] == 115


@pytest.mark.parametrize(
    "seconds, worst", [(6000, 6000), (6001, 900), (21645, 900)], ids=["6000", "6001", "21645"]
)
def test_a_win_over_100_minutes_goes_into_the_keyfile_with_no_time(keyfile, seconds, worst):
    # AisleRiot would read the time back as none, so it mustn't take the
    # place of a worst time it can read
    path = keyfile(AR_KLONDIKE)
    assert store.record_result("klondike", won=True, seconds=seconds) == stat(11, 41, 120, worst)
    assert path.read_text() == f"[klondike.scm]\nStatistic=11;41;120;{worst};\n"
    path = keyfile("[Aisleriot Config]\nRecent=golf;\n")
    store.record_result("golf", won=True, seconds=seconds)
    time = seconds if seconds <= 6000 else 0
    assert ar.read_stat("golf.scm") == stat(1, 1, time, time)
    assert f"Statistic=1;1;{time};{time};" in path.read_text()


def test_a_win_over_100_minutes_keeps_its_time_while_not_shared(keyfile):
    store.record_result("klondike", won=True, seconds=21645)
    assert store.get_stat("klondike") == stat(1, 1, 21645, 21645)
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=60)  # merged in
    assert ar.read_stat("klondike.scm") == stat(11, 42, 120, 900)
    store.update_config(sync_aisleriot=False)
    store.record_result("klondike", won=True, seconds=21645)
    assert store.get_stat("klondike") == stat(12, 43, 120, 21645)
    store.update_config(sync_aisleriot=True)
    assert store.get_stat("klondike") == stat(12, 43, 120, 900)  # waiting
    store.record_result("klondike", won=False, seconds=60)
    assert ar.read_stat("klondike.scm") == stat(12, 44, 120, 900)


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
    cfg = store.load_config()  # the TUI loads this once at start
    store.record_result("klondike", won=False, seconds=5)
    store.save_config(cfg)  # and saves it back on every game
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
    store.record_result("klondike", won=False, seconds=5)  # mirrored locally
    os.remove(store.config_path())
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(0, 2, 0, 0)


def test_stats_from_an_older_version_beside_a_keyfile_count_as_merged(keyfile):
    # older versions kept the flag in config.json only; their stats.json
    # next to a keyfile is a mirror of it already
    keyfile(AR_KLONDIKE)
    write_json(store.stats_path(), {"klondike": stat(10, 40, 120, 900), "golf": stat(1, 1, 30, 30)})
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(10, 41, 120, 900)
    assert ar.read_stat("golf.scm") is None


def test_the_old_config_flag_still_counts(keyfile):
    write_json(
        store.stats_path(), {"_meta": {"merged_into_aisleriot": False}, "golf": stat(1, 1, 30, 30)}
    )
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
    path.write_text(AR_KLONDIKE)  # sol saves its own copy, without golf
    assert store.get_stat("golf") == stat(1, 2, 30, 30)
    assert store.record_result("golf", won=True, seconds=90) == stat(2, 3, 30, 90)
    assert ar.read_stat("golf.scm") == stat(2, 3, 30, 90)
    assert store.load_stats()["golf"] == stat(2, 3, 30, 90)


def test_a_deleted_keyfile_is_rebuilt_from_our_record(keyfile, monkeypatch):
    monkeypatch.setattr(ar, "installed", lambda: True)
    path = keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    os.remove(path)
    assert store.record_result("klondike", won=True, seconds=100) == stat(11, 42, 100, 900)
    assert ar.read_stat("klondike.scm") == stat(11, 42, 100, 900)
    assert store.load_stats()["klondike"] == stat(11, 42, 100, 900)


def no_writes(monkeypatch):
    real_write = ar._write_text
    monkeypatch.setattr(ar, "_write_text", lambda *args, **kwargs: False)
    return lambda: monkeypatch.setattr(ar, "_write_text", real_write)


def test_a_result_the_keyfile_could_not_take_is_kept_and_reported(keyfile, monkeypatch):
    keyfile(AR_KLONDIKE)
    writes_again = no_writes(monkeypatch)
    assert store.record_result("klondike", won=True, seconds=100) == stat(11, 41, 100, 900)
    assert ar.read_stat("klondike.scm") == stat(10, 40, 120, 900)
    assert any("couldn't write" in n and ar.keyfile_path() in n for n in store.notices())
    writes_again()
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(11, 42, 100, 900)


def test_a_shared_result_stats_json_could_not_take_is_reported(keyfile, monkeypatch):
    keyfile(AR_KLONDIKE)
    stats_json_in_use(monkeypatch)
    assert store.record_result("klondike", won=True, seconds=100) == stat(11, 41, 100, 900)
    assert ar.read_stat("klondike.scm") == stat(11, 41, 100, 900)
    assert not os.path.exists(store.stats_path())
    assert any(f"couldn't write {store.stats_path()}" in n for n in store.notices())


def test_history_the_keyfile_could_not_take_goes_in_later(keyfile, monkeypatch):
    store.record_result("golf", won=True, seconds=120)  # before AisleRiot
    keyfile(AR_KLONDIKE)
    writes_again = no_writes(monkeypatch)
    store.record_result("klondike", won=False, seconds=5)  # the merge fails too
    assert store.get_stat("golf") == stat(1, 1, 120, 120)
    assert store.get_stat("klondike") == stat(10, 41, 120, 900)
    writes_again()
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("golf.scm") == stat(1, 1, 120, 120)
    assert ar.read_stat("klondike.scm") == stat(10, 42, 120, 900)


def test_a_reset_the_keyfile_could_not_take_is_reported(keyfile, monkeypatch):
    keyfile(AR_KLONDIKE)
    no_writes(monkeypatch)
    store.reset_stats()
    assert any("couldn't write" in n for n in store.notices())


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
    path.write_text(AR_KLONDIKE.replace("10;40;", "12;43;"))  # two more in sol
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


# a game from a newer version, which this one can't share
FUTURE = {"futuregame": stat(2, 3, 50, 70)}


def test_games_a_newer_version_left_unshared_are_kept(keyfile):
    keyfile(AR_KLONDIKE + "\n[golf.scm]\nStatistic=4;10;30;90;\n")
    golf = stat(1, 1, 60, 60)
    meta = {"merged_into_aisleriot": True, "unsynced": {"golf": golf, **FUTURE}}
    write_json(store.stats_path(), {"golf": golf, "_meta": meta})
    store.record_result("golf", won=True, seconds=40)
    assert ar.read_stat("golf.scm") == stat(6, 12, 30, 90)
    assert store.load_stats()["_meta"]["unsynced"] == FUTURE


def test_games_a_newer_version_left_unshared_survive_a_local_result():
    share(False)
    meta = {"merged_into_aisleriot": True, "unsynced": dict(FUTURE)}
    write_json(store.stats_path(), {"_meta": meta})
    store.record_result("golf", won=True, seconds=40)
    unsynced = store.load_stats()["_meta"]["unsynced"]
    assert unsynced == {**FUTURE, "golf": stat(1, 1, 40, 40)}


def test_games_a_newer_version_left_unshared_survive_the_first_merge(keyfile):
    keyfile(AR_KLONDIKE)
    write_json(store.stats_path(), {"_meta": {"unsynced": dict(FUTURE)}})
    store.record_result("klondike", won=True, seconds=100)
    assert ar.read_stat("klondike.scm") == stat(11, 41, 100, 900)
    assert store.load_stats()["_meta"]["unsynced"] == FUTURE


def test_reset_zeroes_only_the_games_we_manage(keyfile):
    keyfile(
        "[Aisleriot Config]\nRecent=spider;\n\n"
        "[spider.scm]\nStatistic=20;112;591;1966;\n\n"
        "[poker.scm]\nStatistic=5;50;0;0;\n"
    )
    assert store.reset_stats() == 1  # only spider had a record
    assert ar.read_stat("spider.scm") == stat(0, 0, 0, 0)
    assert ar.read_stat("poker.scm") == stat(5, 50, 0, 0)


# -- the games added since aisle-cli 1.0.0 --------------------------------------------

# where AisleRiot keeps each one's record: its Scheme file's name, with
# hyphens turned into underscores
NEW_SECTIONS = {
    "spiderette": "spiderette.scm",
    "scorpion": "scorpion.scm",
    "triplepeaks": "triple_peaks.scm",
}


@pytest.mark.parametrize("key, section", NEW_SECTIONS.items())
def test_the_new_games_use_aisleriots_sections(key, section):
    assert ar.GAME_TO_SECTION[key] == section
    assert ar.SECTION_TO_GAME[section] == key


def test_spiderette_shows_aisleriots_record(keyfile):
    keyfile("[spiderette.scm]\nStatistic=2;5;300;400;\n")
    assert store.get_stat("spiderette") == stat(2, 5, 300, 400)


def test_reset_stats_zeroes_the_new_sections(keyfile, monkeypatch, capsys):
    path = keyfile("".join(f"[{s}]\nStatistic=2;5;300;400;\n\n" for s in NEW_SECTIONS.values()))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["--reset-stats", "--yes"]) == 0
    assert f"cleared for {len(NEW_SECTIONS)} game" in capsys.readouterr().out
    for key, section in NEW_SECTIONS.items():
        assert ar.read_stat(section) == stat(0, 0, 0, 0)
        assert store.get_stat(key) == stat(0, 0, 0, 0)
    assert path.read_text().count("Statistic=0;0;0;0;") == len(NEW_SECTIONS)


def test_without_aisleriot_stats_stay_in_local_json():
    assert not ar.available()
    assert not store.syncing()
    s = store.record_result("freecell", won=True, seconds=120)
    assert s == stat(1, 1, 120, 120)
    assert store.get_stat("freecell")["wins"] == 1
    assert store.load_stats()["freecell"] == s
    assert not os.path.exists(ar.keyfile_path())


# -- sharing turned off for one run -------------------------------------------------


def keyfile_untouchable(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the AisleRiot keyfile was opened")

    monkeypatch.setattr(ar, "_read_text", refuse)
    monkeypatch.setattr(ar, "_write_text", refuse)


@pytest.mark.parametrize("how", ["env", "call"])
def test_turning_sharing_off_for_a_run_leaves_the_keyfile_alone(keyfile, monkeypatch, how):
    path = keyfile(KEYFILE)
    if how == "env":
        monkeypatch.setenv("SOLITERM_NO_AISLERIOT", "1")
    else:
        store.disable_sync()
    keyfile_untouchable(monkeypatch)
    assert not store.syncing()
    assert store.record_result("klondike", won=True, seconds=50) == stat(1, 1, 50, 50)
    assert store.get_stat("klondike") == stat(1, 1, 50, 50)
    assert store.get_stat("spider") == stat(0, 0, 0, 0)
    assert store.any_stats()
    assert store.backup_stats() == [store.stats_path() + ".bak"]
    assert store.reset_stats() == 1
    assert path.read_text() == KEYFILE
    assert store.notices() == []


@pytest.mark.parametrize("value", ["", "0"])
def test_an_empty_or_zero_no_aisleriot_setting_still_shares(keyfile, monkeypatch, value):
    keyfile(AR_KLONDIKE)
    monkeypatch.setenv("SOLITERM_NO_AISLERIOT", value)
    assert store.syncing()
    assert store.get_stat("klondike") == stat(10, 40, 120, 900)


def test_games_kept_local_for_a_run_are_shared_later_only_once(keyfile):
    keyfile(AR_KLONDIKE)
    store.record_result("klondike", won=False, seconds=5)
    store.disable_sync()
    store.record_result("klondike", won=True, seconds=100)
    assert ar.read_stat("klondike.scm") == stat(10, 41, 120, 900)
    store._no_sync = False  # the next run
    store.record_result("klondike", won=False, seconds=5)
    assert ar.read_stat("klondike.scm") == stat(11, 43, 100, 900)


# -- is AisleRiot there? -------------------------------------------------------------

# the real check; conftest hides whatever AisleRiot this machine has
REAL_INSTALLED = ar.installed


def on_path(monkeypatch, *names):
    monkeypatch.setattr(ar, "installed", REAL_INSTALLED)
    monkeypatch.setattr(
        shutil, "which", lambda name: f"/usr/games/{name}" if name in names else None
    )


def test_an_empty_gnome_games_folder_is_not_aisleriot():
    # other GNOME games keep their settings there too
    os.makedirs(ar.gnome_games_dir())
    assert not ar.available() and not store.syncing()
    store.record_result("golf", won=True, seconds=42)
    assert os.listdir(ar.gnome_games_dir()) == []


@pytest.mark.parametrize("program", ["sol", "aisleriot"])
def test_aisleriot_on_the_path_is_found(monkeypatch, program):
    on_path(monkeypatch, program)
    assert ar.installed() and ar.available() and store.syncing()
    on_path(monkeypatch)
    assert not ar.installed() and not ar.available()


def test_results_wait_for_aisleriot_to_make_its_config(monkeypatch):
    on_path(monkeypatch, "sol")
    assert store.record_result("golf", won=True, seconds=42) == stat(1, 1, 42, 42)
    # that folder is AisleRiot's to make, and nothing has gone wrong
    assert not os.path.exists(ar.gnome_games_dir())
    assert store.notices() == []
    assert store.get_stat("golf") == stat(1, 1, 42, 42)
    # AisleRiot is run for the first time and saves its settings
    os.makedirs(ar.gnome_games_dir())
    with open(ar.keyfile_path(), "w", encoding="utf-8") as fh:
        fh.write("[Aisleriot Config]\nRecent=golf;\n")
    store.record_result("golf", won=False, seconds=5)
    assert ar.read_stat("golf.scm") == stat(1, 2, 42, 42)
    assert store.get_stat("golf") == stat(1, 2, 42, 42)


def test_a_reset_before_aisleriot_has_run_counts_our_games(monkeypatch):
    on_path(monkeypatch, "sol")
    store.record_result("golf", won=True, seconds=42)
    assert store.reset_stats() == 1
    assert store.get_stat("golf") == stat(0, 0, 0, 0)


# -- AisleRiot open while we play ----------------------------------------------------

# a made-up /proc needs user ids to own its processes
needs_uids = pytest.mark.skipif(not hasattr(os, "getuid"), reason="needs POSIX user ids")


def fake_proc(tmp_path, monkeypatch, *names):
    """Point the scan at a /proc of our own, with a process for each name
    from pid 100 up, all ours, beside the files that aren't processes."""
    root = tmp_path / "proc"
    root.mkdir()
    (root / "uptime").write_text("12.34 56.78\n")
    (root / "sys").mkdir()
    for pid, name in enumerate(names, 100):
        (root / str(pid)).mkdir()
        (root / str(pid) / "comm").write_text(f"{name}\n")
    monkeypatch.setattr(ar, "PROC_ROOT", str(root))
    return root


@needs_uids
def test_aisleriot_running_is_found(tmp_path, monkeypatch):
    fake_proc(tmp_path, monkeypatch, "bash", "sol", "gnome-shell")
    assert ar.running()


@needs_uids
def test_only_a_process_called_sol_is_aisleriot(tmp_path, monkeypatch):
    fake_proc(tmp_path, monkeypatch, "bash", "solitaire", "consol", "sol-helper")
    assert not ar.running()


@needs_uids
def test_another_users_aisleriot_is_left_alone(tmp_path, monkeypatch):
    fake_proc(tmp_path, monkeypatch, "sol")
    monkeypatch.setattr(os, "getuid", lambda: os.stat(tmp_path).st_uid + 1)
    opened = []

    def spy(path, *args, **kwargs):
        opened.append(path)
        return open(path, *args, **kwargs)

    monkeypatch.setattr(ar, "open", spy, raising=False)
    assert not ar.running()
    assert opened == []  # nothing of someone else's is read


@needs_uids
def test_a_process_that_ends_during_the_scan_is_passed_over(tmp_path, monkeypatch):
    root = fake_proc(tmp_path, monkeypatch, "bash")
    (root / "100" / "comm").unlink()  # gone after its owner was looked at
    (root / "101").symlink_to(root / "gone")  # gone before that
    assert not ar.running()
    (root / "102").mkdir()
    (root / "102" / "comm").write_text("sol\n")
    assert ar.running()


def test_no_proc_means_no_aisleriot_and_no_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "PROC_ROOT", str(tmp_path / "proc"))
    assert not ar.running()
    monkeypatch.setattr(ar, "PROC_ROOT", None)  # not Linux
    assert not ar.running()


def test_aisleriot_open_while_sharing_is_said_once(keyfile, monkeypatch):
    keyfile(KEYFILE)
    monkeypatch.setattr(ar, "running", lambda: True)
    assert store.aisleriot_open_note() == store.AISLERIOT_OPEN
    assert store.aisleriot_open_note() is None
    # on the message line at 80 columns in either look, and on stderr
    assert len(store.AISLERIOT_OPEN) <= 72


def test_aisleriot_closed_says_nothing(keyfile, monkeypatch):
    keyfile(KEYFILE)
    monkeypatch.setattr(ar, "running", lambda: False)
    assert store.aisleriot_open_note() is None


@pytest.mark.parametrize("how", ["env", "call", "config", "waiting"])
def test_nothing_is_looked_for_while_nothing_is_shared(keyfile, monkeypatch, how):
    if how == "waiting":
        # AisleRiot has yet to make its folder, so results wait here
        on_path(monkeypatch, "sol")
    else:
        keyfile(KEYFILE)
    if how == "env":
        monkeypatch.setenv("SOLITERM_NO_AISLERIOT", "1")
    elif how == "call":
        store.disable_sync()
    elif how == "config":
        share(False)

    def refuse():
        raise AssertionError("looked for AisleRiot")

    monkeypatch.setattr(ar, "running", refuse)
    assert store.aisleriot_open_note() is None


@pytest.mark.parametrize("code_skin", [False, True])
def test_the_first_game_on_screen_says_aisleriot_is_open(keyfile, monkeypatch, code_skin):
    keyfile(KEYFILE)
    monkeypatch.setattr(ar, "running", lambda: True)
    cfg = store.load_config()
    cfg["code_skin"] = code_skin
    store.save_config(cfg)
    app = App(FakeScr(24, 80))
    app.start_game("klondike")
    assert app.message == store.AISLERIOT_OPEN
    app.draw()
    assert store.AISLERIOT_OPEN in app.stdscr.text()
    app.start_game("golf")  # once is enough
    assert app.message == START_MESSAGE


def test_text_mode_says_aisleriot_is_open_on_stderr_before_the_board(keyfile, monkeypatch, capsys):
    keyfile(KEYFILE)
    commands = "n\nq\n"
    textmode.run_text(new_solitaire("klondike", 1), False, "klondike", io.StringIO(commands))
    closed = capsys.readouterr()
    assert closed.err == ""
    monkeypatch.setattr(store, "_looked_for_aisleriot", False)  # the next run
    monkeypatch.setattr(ar, "running", lambda: True)
    textmode.run_text(new_solitaire("klondike", 1), False, "klondike", io.StringIO(commands))
    opened = capsys.readouterr()
    assert opened.out == closed.out
    assert opened.err == f"soliterm: {store.AISLERIOT_OPEN}\n"  # and not again for n
    # between the header and the board, when both go to one place
    monkeypatch.setattr(store, "_looked_for_aisleriot", False)
    both = io.StringIO()
    monkeypatch.setattr(sys, "stdout", both)
    monkeypatch.setattr(sys, "stderr", both)
    textmode.run_text(new_solitaire("klondike", 1), False, "klondike", io.StringIO(commands))
    header, rest = closed.out.split("\n", 1)
    assert both.getvalue() == f"{header}\nsoliterm: {store.AISLERIOT_OPEN}\n{rest}"


def test_text_mode_with_stderr_closed_leaves_stdout_alone(keyfile, monkeypatch, capsys):
    keyfile(KEYFILE)
    monkeypatch.setattr(ar, "running", lambda: True)
    monkeypatch.setattr(sys, "stderr", None)  # what Python makes of 2>&-
    textmode.run_text(new_solitaire("klondike", 1), False, "klondike", io.StringIO("q\n"))
    assert store.AISLERIOT_OPEN not in capsys.readouterr().out


def test_text_mode_plays_on_when_nothing_reads_stderr(keyfile, monkeypatch, capsys):
    keyfile(KEYFILE)
    monkeypatch.setattr(ar, "running", lambda: True)
    read, write = os.pipe()
    os.close(read)  # whatever read stderr has gone
    with open(write, "w") as gone:
        monkeypatch.setattr(sys, "stderr", gone)
        g = new_solitaire("klondike", 1)
        assert textmode.run_text(g, False, "klondike", io.StringIO("q\n")) == 0
        assert capsys.readouterr().out.endswith("bye\n")
        # the line left in its buffer would fail again as Python flushes it
        # at exit, so it goes nowhere instead
        gone.flush()
