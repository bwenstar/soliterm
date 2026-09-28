"""Keeping config.json and stats.json whole: atomic saves, damaged files kept
aside, and two copies of the game recording at once.
"""

import glob
import json
import multiprocessing
import os
import signal
import threading
import time

import pytest

from soliterm import store

from helpers import stats_json_in_use


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


def test_an_interrupted_write_leaves_no_tmp_file(monkeypatch):
    store.record_result("golf", won=True, seconds=42)
    before = read(store.stats_path())

    def interrupted(fd):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "fsync", interrupted)
    with pytest.raises(KeyboardInterrupt):
        store.save_stats({"golf": stat(9, 9, 9, 9)})
    assert read(store.stats_path()) == before
    assert set(os.listdir(store.data_dir())) <= {"stats.json", "stats.lock"}


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


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"], ids=["with a BOM", "UTF-16"])
def test_files_saved_with_a_bom_or_in_utf_16_are_read(encoding):
    # as Notepad and PowerShell save a file edited by hand on Windows
    for path, obj in [
        (store.config_path(), {"last_game": "golf", "symbols": False}),
        (store.stats_path(), {"golf": stat(2, 3, 40, 90)}),
    ]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding=encoding) as fh:
            json.dump(obj, fh)
    assert store.load_config()["last_game"] == "golf"
    assert store.load_config()["symbols"] is False
    assert store.get_stat("golf") == stat(2, 3, 40, 90)
    store.record_result("golf", won=True, seconds=42)
    assert store.get_stat("golf") == stat(3, 4, 40, 90)
    assert glob.glob(store.config_path() + ".corrupt-*") == []
    assert glob.glob(store.stats_path() + ".corrupt-*") == []
    assert store.notices() == []


def test_two_damaged_files_in_the_same_second_are_both_kept(monkeypatch):
    monkeypatch.setattr(store.time, "strftime", lambda fmt, *a: "20260101-120000")
    write(store.stats_path(), "{one")
    store.load_stats()
    write(store.stats_path(), "{two")
    store.load_stats()
    kept = sorted(read(p) for p in glob.glob(store.stats_path() + ".corrupt-*"))
    assert kept == ["{one", "{two"]


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX file modes, not root"
)
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


def test_a_result_stats_json_could_not_take_is_reported(monkeypatch):
    store.record_result("golf", won=True, seconds=42)
    before = read(store.stats_path())
    stats_json_in_use(monkeypatch)
    store.record_result("golf", won=False, seconds=42)
    assert read(store.stats_path()) == before
    assert any(
        f"couldn't write {store.stats_path()}" in n and "that game is missing" in n
        for n in store.notices()
    )


def test_a_reset_stats_json_could_not_take_clears_nothing(monkeypatch):
    store.record_result("golf", won=True, seconds=42)
    before = read(store.stats_path())
    stats_json_in_use(monkeypatch)
    assert store.reset_stats() is None
    assert read(store.stats_path()) == before
    assert any(
        f"couldn't write {store.stats_path()}" in n and "nothing was cleared" in n
        for n in store.notices()
    )


def _record_many(n):
    for _ in range(n):
        store.record_result("golf", won=True, seconds=42)


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="needs fork")
def test_two_games_recording_at_once_lose_nothing():
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_record_many, args=(25,)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    assert [p.exitcode for p in procs] == [0, 0, 0, 0]
    assert store.get_stat("golf") == stat(100, 100, 42, 42)


needs_flock = pytest.mark.skipif(
    store.fcntl is None or not hasattr(signal, "pthread_kill"), reason="needs flock and signals"
)


@needs_flock
def test_ctrl_c_still_stops_a_wait_for_the_lock():
    os.makedirs(store.data_dir())
    main = threading.get_ident()
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:
        # another copy of the game has the lock, and keeps it for a while
        store.fcntl.flock(other.fileno(), store.fcntl.LOCK_EX)

        def other_copy():
            time.sleep(0.2)
            signal.pthread_kill(main, signal.SIGINT)
            time.sleep(0.5)
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)

        waiting = threading.Thread(target=other_copy)
        waiting.start()
        try:
            with pytest.raises(KeyboardInterrupt), store.signals_held():
                store.record_result("golf", won=True, seconds=42)
        finally:
            waiting.join()
    # Ctrl-C came while it waited, not once the lock was let go
    assert store.get_stat("golf")["total"] == 0


@needs_flock
def test_a_wait_for_the_lock_is_told_of_first():
    os.makedirs(store.data_dir())
    told = []
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:
        store.fcntl.flock(other.fileno(), store.fcntl.LOCK_EX)

        def note():
            told.append(store.LOCK_WAIT)
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)  # it lets go

        with store.lock_wait_note(note):
            store.record_result("golf", won=True, seconds=42)
            assert told == [store.LOCK_WAIT]
            # with the lock free, there is no wait to tell of
            store.record_result("golf", won=True, seconds=42)
    assert told == [store.LOCK_WAIT]
    assert store.get_stat("golf")["wins"] == 2


@needs_flock
@pytest.mark.parametrize("error", [BrokenPipeError, ValueError])
def test_a_wait_note_that_fails_still_waits_for_the_lock(error):
    os.makedirs(store.data_dir())
    with open(os.path.join(store.data_dir(), "stats.lock"), "a") as other:
        store.fcntl.flock(other.fileno(), store.fcntl.LOCK_EX)

        def note():
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)  # it lets go
            # as print does on a stderr that has closed, or been closed
            raise error

        # it has the lock, so another copy can't take it now
        with store.lock_wait_note(note), store._locked(), pytest.raises(BlockingIOError):
            store.fcntl.flock(other.fileno(), store.fcntl.LOCK_EX | store.fcntl.LOCK_NB)


@pytest.mark.skipif(os.name != "posix", reason="needs POSIX file modes")
def test_the_lock_file_is_the_players_own():
    old = os.umask(0o022)
    try:
        store.record_result("golf", won=True, seconds=42)
    finally:
        os.umask(old)
    assert os.stat(os.path.join(store.data_dir(), "stats.lock")).st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="needs POSIX file modes")
def test_a_lock_file_open_to_others_is_made_the_players_own():
    # as an older version left it
    os.makedirs(store.data_dir())
    path = os.path.join(store.data_dir(), "stats.lock")
    with open(path, "a"):
        pass
    os.chmod(path, 0o644)
    store.record_result("golf", won=True, seconds=42)
    assert os.stat(path).st_mode & 0o777 == 0o600


# -- values of the wrong type ----------------------------------------------------------

BAD_STATS = """{
  "golf": {"wins": "x", "total": 4, "best": null, "worst": 1e400},
  "spider": [1, 2],
  "klondike": {"wins": true, "total": -3, "best": 2.5, "worst": 90.0},
  "freecell": {"wins": 2, "total": 3, "best": 50, "worst": 70}
}"""


def test_a_stat_of_the_wrong_type_reads_as_zero_on_its_own():
    write(store.stats_path(), BAD_STATS)
    assert store.get_stat("golf") == stat(0, 4, 0, 0)
    assert store.get_stat("spider") == stat(0, 0, 0, 0)
    assert store.get_stat("klondike") == stat(0, 0, 0, 90)
    assert store.get_stat("freecell") == stat(2, 3, 50, 70)


def test_recording_over_bad_stats_works():
    write(store.stats_path(), BAD_STATS)
    assert store.record_result("golf", won=True, seconds=42) == stat(1, 5, 42, 42)


def test_clearing_bad_stats_works():
    write(store.stats_path(), BAD_STATS.replace('"total": 4', '"total": "4"'))
    assert store.reset_stats() == 1
    assert store.get_stat("freecell") == stat(0, 0, 0, 0)
