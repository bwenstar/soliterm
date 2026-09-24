"""Unfinished games kept in the saves folder, one of each kind, and what
happens to a save that is damaged, too big or from a newer version."""

import glob
import json
import os

import pytest

from soliterm import saves, store

from helpers import deal


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
        lambda path, save: write(path, {**save, "seconds": True}),
        lambda path, save: write(path, {**save, "format": "1"}),
        lambda path, save: write(path, {**save, **played("spider").snapshot(500)}),
        lambda path, save: damage(save) or write(path, save),
    ],
    ids=["bad JSON", "a bool for seconds", "a format of text", "a spider game", "a card added"],
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
