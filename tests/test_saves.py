"""Unfinished games kept in the saves folder, one of each kind, and what
happens to a save that is damaged, too big or from a newer version."""

import errno
import glob
import json
import os

import pytest

from soliterm import saves, store
from soliterm.engine import GAMES

from helpers import (
    OtherCopy,
    crashed,
    deal,
    from_before_the_counts,
    in_play_elsewhere,
    nothing_in_play,
    saved,
)


def played(key="klondike", seed=4, deals=3):
    g = deal(key, seed)
    for _ in range(deals):
        g.deal()
    return g


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj))


def set_aside():
    return glob.glob(saves.save_path("klondike") + ".corrupt-*")


def test_keep_then_take_gives_the_game_back():
    g = played()
    g.undo()
    assert saves.keep(g, 42.4)
    h, seconds = saves.take("klondike")
    assert seconds == 42
    assert h.serialize() == g.serialize()
    assert (h._undo, h._redo) == (g._undo, g._redo)
    assert h.deal_number == 4
    assert store.notices() == []


def test_take_removes_the_save():
    assert saves.keep(played(), 42)
    assert saves.take("klondike")
    assert not os.path.exists(saves.save_path("klondike"))
    assert saves.take("klondike") is None
    assert saves.waiting() == {}


def test_keep_refuses_a_taken_slot():
    assert saves.keep(played(deals=3), 42)
    assert not saves.keep(played(deals=5), 50)
    assert read(saves.save_path("klondike"))["moves"] == 3
    assert store.notices() == [
        "a saved Klondike game was already waiting, so this one counted as lost"
    ]


def test_waiting_lists_seconds_and_moves():
    assert saves.waiting() == {}
    g = played()
    g.moves = 31
    assert saves.keep(g, 42)
    assert saves.keep(played("golf"), 7)
    assert saves.waiting() == {
        "klondike": {"seconds": 42, "moves": 31},
        "golf": {"seconds": 7, "moves": 3},
    }


def test_waiting_says_which_save_is_a_daily():
    g = played()
    g.daily = "2026-09-24"
    assert saves.keep(g, 42)
    assert saves.keep(played("golf"), 7)
    assert saves.waiting() == {
        "klondike": {"seconds": 42, "moves": 3, "daily": "2026-09-24"},
        "golf": {"seconds": 7, "moves": 3},
    }
    assert read(saves.save_path("klondike"))["daily"] == "2026-09-24"
    h, _ = saves.take("klondike")
    assert h.daily == "2026-09-24"


@pytest.mark.parametrize("daily", [True, 20260924, "2026-9-24", "2026-02-30", "today"])
def test_waiting_calls_a_save_a_daily_only_with_a_day_to_it(daily):
    # which resuming it would find out, and set it aside
    assert saves.keep(played(), 42)
    path = saves.save_path("klondike")
    write(path, {**read(path), "daily": daily})
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 3}}


def test_a_save_without_daily_still_resumes():
    g = played()
    assert saves.keep(g, 42)
    path = saves.save_path("klondike")
    save = read(path)
    del save["daily"]  # as the first saves were written
    write(path, save)
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 3}}
    h, seconds = saves.take("klondike")
    assert (h.serialize(), seconds, h.daily) == (g.serialize(), 42, None)


def damage(save):
    # a card too many in the waste
    save["position"] = save["position"].replace("\ns1|waste|none|0|", "\ns1|waste|none|0|1SU,")


@pytest.mark.parametrize(
    "change",
    [
        lambda path, save: write(path, '{"format": 1, "sec'),
        lambda path, save: write(path, {}),
        lambda path, save: write(path, {**save, "seconds": True}),
        lambda path, save: write(path, {**save, "format": "1"}),
        lambda path, save: write(path, {**save, **played("spider").snapshot(500)}),
        lambda path, save: damage(save) or write(path, save),
    ],
    ids=[
        "bad JSON",
        "nothing in it",
        "a bool for seconds",
        "a format of text",
        "a spider game",
        "a card added",
    ],
)
def test_a_damaged_save_is_set_aside(change):
    assert saves.keep(played(), 42)
    path = saves.save_path("klondike")
    change(path, read(path))
    assert saves.take("klondike") is None
    assert not os.path.exists(path)
    assert len(set_aside()) == 1
    assert "was damaged" in store.notices()[0]
    assert saves.keep(played(), 42)  # the slot is free again


def test_an_oversized_save_is_set_aside(monkeypatch):
    assert saves.keep(played(), 42)
    monkeypatch.setattr(saves, "SAVE_MAX_BYTES", 100)
    assert saves.waiting() == {}
    assert len(set_aside()) == 1


def test_a_save_from_a_newer_version_is_left_alone():
    path = saves.save_path("klondike")
    write(path, {"format": 2, "game": "klondike", "seconds": 5, "moves": 1, "score": 0})
    with open(path, encoding="utf-8") as fh:
        before = fh.read()
    assert saves.take("klondike") is None
    assert saves.waiting() == {}
    assert not saves.keep(played(), 42)
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == before
    assert store.notices() == [
        (
            f"{path} was saved by a newer Soliterm, so it is left alone "
            "and a Klondike game left unfinished counts as lost"
        )
    ]


def test_unknown_keys_in_a_save_are_ignored():
    g = played()
    assert saves.keep(g, 42)
    path = saves.save_path("klondike")
    write(path, {**read(path), "colour": [1, 2], "theme": "dark"})
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 3}}
    h, _ = saves.take("klondike")
    assert h.serialize() == g.serialize()


# -- hints and undos


def test_a_save_carries_the_hints_and_undos_and_gives_them_back():
    g = played()
    g.hint()
    assert g.undo()
    assert saves.keep(g, 42)
    assert (saved()["hints"], saved()["undos"]) == (1, 1)
    h, _ = saves.take("klondike")
    assert (h.hints, h.undos) == (1, 1)


def test_a_save_from_before_the_counts_gives_them_unknown():
    assert saves.keep(played(), 42)
    from_before_the_counts()
    g, _ = saves.take("klondike")
    assert (g.hints, g.undos) == (None, None)
    g.hint()
    assert saves.keep(g, 50)
    assert not {"hints", "undos"} & set(saved())


def test_a_save_with_the_counts_is_one_1_0_resumes():
    # 1.0 leaves a save alone if its format is past 1, checks its game,
    # seconds, moves and score, and takes up only the fields it knows
    assert saves.keep(played(), 42)
    save = saved()
    assert save["format"] == 1
    known = {"format", "version", "saved", "seconds", "game", "options", "deal", "daily"}
    known |= {"chosen", "moves", "score", "position", "undo", "redo"}
    assert set(save) - known == {"hints", "undos"}


# -- a game in play ------------------------------------------------------------------


def lock_free(key="klondike"):
    """Whether a copy of the game could take key's save up now, with no
    copy holding the game's lock."""
    fd = store._lock_file(saves._lock_path(key))
    if fd is None:
        return False
    store._let_go(fd)
    return True


def folder():
    """Every file in the saves folder, and what's in it, but for the locks:
    there's nothing in them, and Windows won't read one while it's held."""
    found = {}
    for name in sorted(os.listdir(saves.saves_dir())):
        found[name] = None
        if not name.endswith(".lock"):
            with open(os.path.join(saves.saves_dir(), name), "rb") as fh:
                found[name] = fh.read()
    return found


ELSEWHERE = "a saved Klondike game is being played somewhere else, so this one counted as lost"


def test_taking_a_save_up_puts_it_in_play():
    assert saves.keep(played(), 42)
    save = read(saves.save_path("klondike"))
    assert saves.take("klondike")
    assert not os.path.exists(saves.save_path("klondike"))
    assert read(saves.in_play_path("klondike")) == save
    assert not lock_free()


def test_a_game_in_play_leaves_nothing_1_0_would_offer_or_set_aside():
    # 1.0 looks for saves/<game>.json, for each game it has, and nothing else
    assert saves.keep(played(), 42)
    assert saves.keep(played("golf"), 7)
    assert saves.take("klondike") and saves.take("golf")
    assert list(folder()) == [
        "golf.in-play.json",
        "golf.lock",
        "klondike.in-play.json",
        "klondike.lock",
    ]
    assert not {f"{key}.json" for key in GAMES} & set(folder())


def test_keeping_it_again_puts_the_new_save_in_place_of_the_old():
    assert saves.keep(played(), 42)
    g, _ = saves.take("klondike")
    g.deal()
    assert saves.keep(g, 50)
    assert saves.waiting() == {"klondike": {"seconds": 50, "moves": 4}}
    assert nothing_in_play()
    assert lock_free()


def test_the_old_save_goes_only_once_the_new_one_is_there(monkeypatch):
    assert saves.keep(played(), 42)
    g, _ = saves.take("klondike")
    old_one_there = []
    real = store._write_json

    def write(path, obj):
        old_one_there.append(os.path.exists(saves.in_play_path("klondike")))
        return real(path, obj)

    monkeypatch.setattr(store, "_write_json", write)
    assert saves.keep(g, 50)
    assert old_one_there == [True]
    assert nothing_in_play()


def test_a_new_save_that_fails_leaves_the_old_one_in_play(monkeypatch):
    assert saves.keep(played(), 42)
    g, _ = saves.take("klondike")
    monkeypatch.setattr(store, "_write_json", lambda path, obj: False)
    assert not saves.keep(g, 50)
    assert os.path.exists(saves.in_play_path("klondike"))
    assert not lock_free()
    # counting it lets it go, as the game then does
    saves.let_go("klondike")
    assert nothing_in_play()
    assert lock_free()


def test_letting_go_takes_the_game_out_of_play_for_good():
    assert saves.keep(played(), 42)
    assert saves.take("klondike")
    saves.let_go("klondike")
    assert nothing_in_play()
    assert lock_free()
    assert saves.waiting() == {}
    assert saves.take("klondike") is None
    saves.let_go("klondike")  # again, with nothing in play: nothing to do
    assert store.notices() == []


def test_a_game_left_in_play_is_offered_again_as_it_was_taken_up():
    assert saves.keep(played(), 42)
    g, _ = saves.take("klondike")
    g.deal()  # a move not kept, lost with the copy that made it
    crashed()
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 3}}
    h, seconds = saves.take("klondike")
    assert (h.moves, seconds) == (3, 42)
    assert not os.path.exists(saves.save_path("klondike"))


def test_a_game_left_in_play_can_be_taken_up_without_asking_first():
    assert saves.keep(played(), 42)
    assert saves.take("klondike")
    crashed()
    h, seconds = saves.take("klondike")
    assert (h.moves, seconds) == (3, 42)


def test_a_save_beside_a_game_left_in_play_is_newer_and_stays():
    assert saves.keep(played(deals=5), 50)
    newer = read(saves.save_path("klondike"))
    os.remove(saves.save_path("klondike"))
    assert saves.keep(played(deals=3), 42)
    assert saves.take("klondike")
    crashed()
    # kept since, as 1.0 would, with no eye for the game in play
    write(saves.save_path("klondike"), newer)
    assert saves.waiting() == {"klondike": {"seconds": 50, "moves": 5}}
    assert not os.path.exists(saves.in_play_path("klondike"))


def test_a_game_in_play_elsewhere_is_neither_offered_nor_taken_up_here():
    assert saves.keep(played(), 42)
    with in_play_elsewhere():
        before = folder()
        assert saves.waiting() == {}
        assert saves.take("klondike") is None
        assert saves.elsewhere("klondike")
        # and it leaves no room to keep another game of its kind
        assert not saves.keep(played(deals=5), 50)
        assert folder() == before
    assert store.notices() == [ELSEWHERE]
    # once that copy has gone, the game is this one's to offer
    assert not saves.elsewhere("klondike")
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 3}}


@pytest.mark.parametrize(
    "change",
    [
        lambda: write(saves.in_play_path("klondike"), '{"format": 1, "sec'),
        lambda: write(saves.save_path("klondike"), read(saves.in_play_path("klondike"))),
    ],
    ids=["damaged", "a save beside it"],
)
def test_a_game_in_play_elsewhere_is_left_alone_whatever_is_there(change):
    assert saves.keep(played(), 42)
    with in_play_elsewhere():
        change()
        before = folder()
        assert saves.waiting() == {}
        assert saves.take("klondike") is None
        assert not saves.keep(played(deals=5), 50)
        assert folder() == before
        assert set_aside() == []


def no_locks(fd):
    raise OSError(errno.ENOLCK, "No locks available")


@pytest.mark.parametrize(
    "no_lock",
    [
        lambda monkeypatch: monkeypatch.setattr(store, "_lock_now", no_locks),
        lambda monkeypatch: os.mkdir(saves._lock_path("klondike")),
    ],
    ids=["no locks", "no lock file"],
)
def test_a_save_whose_lock_cant_be_had_is_taken_up_as_1_0_did(monkeypatch, no_lock):
    # as on NFS with no lock daemon, where the stats have no lock either:
    # it's played, out of the folder at once so it can't be played twice
    assert saves.keep(played(), 42)
    no_lock(monkeypatch)
    g, seconds = saves.take("klondike")
    assert (g.moves, seconds) == (3, 42)
    assert not os.path.exists(saves.save_path("klondike"))
    assert not os.path.exists(saves.in_play_path("klondike"))
    assert saves._playing == {}
    assert saves.waiting() == {}
    # and kept again on the way out
    g.deal()
    assert saves.keep(g, 50)
    assert saves.waiting() == {"klondike": {"seconds": 50, "moves": 4}}
    assert store.notices() == []


def test_a_save_that_cant_come_out_of_the_folder_is_left_there(monkeypatch):
    assert saves.keep(played(), 42)
    monkeypatch.setattr(store, "_lock_now", no_locks)

    def remove(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "remove", remove)
    assert saves.take("klondike") is None
    assert saves.waiting() == {"klondike": {"seconds": 42, "moves": 3}}
    [notice] = store.notices()
    assert notice == (
        f"can't take {saves.save_path('klondike')} out of the saves folder "
        "(Permission denied), so it is left there and a new hand dealt"
    )


def test_a_game_in_play_whose_lock_cant_be_had_is_left_alone():
    # as there's no knowing whether a copy of the game still plays it
    assert saves.keep(played(), 42)
    assert saves.take("klondike")
    crashed()
    os.remove(saves._lock_path("klondike"))
    os.mkdir(saves._lock_path("klondike"))
    assert saves.waiting() == {}
    assert os.path.exists(saves.in_play_path("klondike"))


def test_a_game_in_play_in_another_copy_is_neither_offered_nor_taken_up_here():
    assert saves.keep(played(), 42)
    with OtherCopy() as other:
        other.says("Resumed your Klondike game (0:42, 3 moves)")
        assert saves.waiting() == {}
        assert saves.take("klondike") is None
        assert not saves.keep(played(deals=5), 50)
        other.types("d")
        other.says("moves=4 ")
        assert other.quits() == 0
    # it kept the game again, a move on
    assert saves.waiting()["klondike"]["moves"] == 4
    assert store.notices() == [ELSEWHERE]
