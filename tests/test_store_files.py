"""Keeping config.json and stats.json whole: atomic saves, damaged files kept
aside, and two copies of the game recording at once.
"""

import glob
import json
import multiprocessing
import os

import pytest

from soliterm import store


def stat(wins, total, best, worst):
    return {"wins": wins, "total": total, "best": best, "worst": worst}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def failing_json(monkeypatch):
    # the disk fills up half way through writing the JSON out
    def boom(*args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(json, "dump", boom)
    monkeypatch.setattr(json, "dumps", boom)


def test_a_failed_stats_save_keeps_the_old_file(monkeypatch):
    store.record_result("golf", won=True, seconds=42)
    before = read(store.stats_path())
    failing_json(monkeypatch)
    assert store.save_stats({"golf": stat(9, 9, 9, 9)}) is False
    assert read(store.stats_path()) == before
    assert set(os.listdir(store.data_dir())) <= {"stats.json", "stats.lock"}


def test_a_failed_config_save_keeps_the_old_file(monkeypatch):
    cfg = store.load_config()
    cfg["last_game"] = "golf"
    store.save_config(cfg)
    before = read(store.config_path())
    failing_json(monkeypatch)
    cfg["last_game"] = "spider"
    assert store.save_config(cfg) is False
    assert read(store.config_path()) == before
    assert os.listdir(store.config_dir()) == ["config.json"]


@pytest.mark.parametrize("text", ['{"golf": {"wins": 3, "tot', "[1, 2]", ""])
def test_a_damaged_stats_file_is_kept_aside(text):
    write(store.stats_path(), text)
    store.record_result("golf", won=True, seconds=42)
    kept = glob.glob(store.stats_path() + ".corrupt-*")
    assert len(kept) == 1 and read(kept[0]) == text
    assert store.get_stat("golf") == stat(1, 1, 42, 42)
    assert any(kept[0] in n for n in store.notices())


def test_a_damaged_config_is_kept_aside():
    write(store.config_path(), "{not json")
    assert store.load_config() == store.DEFAULT_CONFIG
    kept = glob.glob(store.config_path() + ".corrupt-*")
    assert len(kept) == 1 and read(kept[0]) == "{not json"
    assert any(kept[0] in n for n in store.notices())


def test_two_damaged_files_in_the_same_second_are_both_kept(monkeypatch):
    monkeypatch.setattr(store.time, "strftime", lambda fmt, *a: "20260101-120000")
    write(store.stats_path(), "{one")
    store.load_stats()
    write(store.stats_path(), "{two")
    store.load_stats()
    kept = sorted(read(p) for p in glob.glob(store.stats_path() + ".corrupt-*"))
    assert kept == ["{one", "{two"]


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0,
                    reason="needs POSIX file modes, not root")
def test_an_unreadable_stats_file_is_never_replaced():
    write(store.stats_path(), json.dumps({"golf": stat(5, 9, 30, 90)}))
    os.chmod(store.stats_path(), 0)
    try:
        store.record_result("golf", won=True, seconds=42)
        assert store.save_stats({}) is False
    finally:
        os.chmod(store.stats_path(), 0o644)
    assert json.loads(read(store.stats_path())) == {"golf": stat(5, 9, 30, 90)}
    assert any("can't read" in n for n in store.notices())


def _record_many(n):
    for _ in range(n):
        store.record_result("golf", won=True, seconds=42)


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(),
                    reason="needs fork")
def test_two_games_recording_at_once_lose_nothing():
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_record_many, args=(25,)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    assert [p.exitcode for p in procs] == [0, 0, 0, 0]
    assert store.get_stat("golf") == stat(100, 100, 42, 42)
