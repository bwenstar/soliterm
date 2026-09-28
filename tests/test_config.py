"""Config persistence, including the UI preferences the TUI toggles save."""

import glob
import io
import json
import os
import sys

import pytest

from soliterm import store
from soliterm.cli import main


def test_ui_preferences_are_unset_until_saved():
    cfg = store.load_config()
    for key in ("color", "code_skin", "camo_theme", "view", "theme", "four_color"):
        assert key not in cfg


def test_ui_preferences_persist():
    cfg = store.load_config()
    cfg["color"] = False
    cfg["code_skin"] = True
    cfg["camo_theme"] = "docker"
    assert store.save_config(cfg)
    again = store.load_config()
    assert again["color"] is False
    assert again["code_skin"] is True
    assert again["camo_theme"] == "docker"
    again["color"] = True
    store.save_config(again)
    assert store.load_config()["color"] is True


@pytest.mark.parametrize("view", ["legacy", "expanded"])
def test_the_view_persists(view):
    cfg = store.load_config()
    cfg["view"] = view
    store.save_config(cfg)
    assert store.load_config()["view"] == view


def test_a_bad_view_value_is_ignored():
    cfg = store.load_config()
    cfg["view"] = "legacy"
    store.save_config(cfg)
    with open(store.config_path(), encoding="utf-8") as fh:
        data = json.load(fh)
    data["view"] = "garbage"
    with open(store.config_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    assert "view" not in store.load_config()


def test_per_game_options_round_trip():
    cfg = store.load_config()
    store.set_game_options(cfg, "spider", {"suits": 2})
    store.save_config(cfg)
    cfg = store.load_config()
    assert store.game_options(cfg, "spider") == {"suits": 2}
    assert store.game_options(cfg, "klondike") == {}


@pytest.mark.parametrize("text", ["{not json", "[1, 2, 3]", ""])
def test_an_unreadable_config_falls_back_to_the_defaults(text):
    store.save_config(store.load_config())
    with open(store.config_path(), "w", encoding="utf-8") as fh:
        fh.write(text)
    assert store.load_config() == store.DEFAULT_CONFIG


def write_config(data):
    os.makedirs(store.config_dir(), exist_ok=True)
    with open(store.config_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def test_theme_and_four_color_load_and_bad_types_are_dropped():
    write_config({"theme": "solarized", "four_color": True})
    cfg = store.load_config()
    assert cfg["theme"] == "solarized"
    assert cfg["four_color"] is True
    write_config({"theme": ["dark"], "four_color": 1})
    cfg = store.load_config()
    assert "theme" not in cfg
    assert "four_color" not in cfg


def test_a_config_value_of_the_wrong_type_falls_back_on_its_own():
    write_config(
        {
            "last_game": 7,
            "symbols": "no",
            "options": [],
            "sync_aisleriot": 0,
            "merged_into_aisleriot": "yes",
            "color": "off",
            "code_skin": 1,
            "camo_theme": 5,
            "view": "legacy",
            "theme": 5,
            "four_color": "yes",
        }
    )
    cfg = store.load_config()
    assert cfg == {**store.DEFAULT_CONFIG, "view": "legacy"}


def test_json_booleans_still_load():
    write_config(
        {
            "symbols": False,
            "sync_aisleriot": False,
            "merged_into_aisleriot": True,
            "color": False,
            "code_skin": True,
        }
    )
    cfg = store.load_config()
    assert cfg["symbols"] is False and cfg["sync_aisleriot"] is False
    assert cfg["merged_into_aisleriot"] is True
    assert cfg["color"] is False and cfg["code_skin"] is True


def test_animation_is_kept_when_it_is_a_bool():
    # no toggle saves it: it is only ever there by hand
    write_config({"animation": "no"})
    assert "animation" not in store.load_config()
    write_config({"animation": False})
    cfg = store.load_config()
    assert cfg["animation"] is False
    cfg["color"] = True  # as v saves it
    store.save_config(cfg)
    assert store.load_config()["animation"] is False


@pytest.mark.parametrize(
    "saved",
    [
        {"suits": 3},
        {"suits": "2"},
        {"suits": True},
        {"suits": 2.5},
        {"colour": 2},
    ],
)
def test_a_saved_option_the_game_does_not_offer_is_dropped(saved):
    write_config({"options": {"spider": saved}})
    assert store.game_options(store.load_config(), "spider") == {}


def test_good_options_survive_next_to_bad_ones():
    write_config(
        {
            "options": {
                "klondike": {"draw": 3, "speed": "fast"},
                "spider": {"suits": 7},
                "golf": {"draw": 3},
            }
        }
    )
    cfg = store.load_config()
    assert store.game_options(cfg, "klondike") == {"draw": 3}
    assert store.game_options(cfg, "spider") == {}
    assert store.game_options(cfg, "golf") == {}


def test_text_mode_deals_spider_with_a_bad_saved_option(monkeypatch, capsys):
    write_config({"last_game": "spider", "options": {"spider": {"suits": 3}}})
    monkeypatch.setattr(sys, "stdin", io.StringIO("q\n"))
    assert main(["--text", "--no-color", "--seed", "1"]) == 0
    assert "Spider" in capsys.readouterr().out


def test_a_last_game_that_no_longer_exists_falls_back_to_klondike(monkeypatch, capsys):
    write_config({"last_game": "pyramid"})
    assert store.load_config()["last_game"] == "klondike"
    monkeypatch.setattr(sys, "stdin", io.StringIO("q\n"))
    assert main(["--text", "--no-color", "--seed", "1"]) == 0
    assert "Klondike" in capsys.readouterr().out


def read_config():
    with open(store.config_path(), encoding="utf-8") as fh:
        return json.load(fh)


def test_a_change_leaves_the_rest_of_the_file_as_it_is():
    # a hand edit made since the game loaded the config, and keys and a
    # game only a newer version knows
    on_disk = {
        "theme": "dark",
        "sync_aisleriot": False,
        "future_key": [1, 2],
        "options": {"spider": {"suits": 2}, "pyramid": {"rounds": 3}},
    }
    write_config(on_disk)
    assert store.update_config(color=False, options={"klondike": {"draw": 3}})
    assert read_config() == {
        **on_disk,
        "color": False,
        "options": {"spider": {"suits": 2}, "pyramid": {"rounds": 3}, "klondike": {"draw": 3}},
    }


def test_new_options_go_over_options_of_the_wrong_type():
    write_config({"options": [1, 2], "theme": "dark"})
    assert store.update_config(options={"klondike": {"draw": 3}})
    assert read_config() == {"options": {"klondike": {"draw": 3}}, "theme": "dark"}


@pytest.mark.parametrize("text", [None, "{not json", "[1, 2, 3]", ""])
def test_a_change_to_a_missing_or_damaged_config_starts_a_new_one(text):
    if text is not None:
        os.makedirs(store.config_dir())
        with open(store.config_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
    assert store.update_config(theme="dark")
    assert read_config() == {"theme": "dark"}
    kept = glob.glob(store.config_path() + ".corrupt-*")
    assert len(kept) == (0 if text is None else 1)
