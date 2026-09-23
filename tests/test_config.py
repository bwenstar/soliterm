"""Config persistence, including the UI preferences the TUI toggles save."""

import json

import pytest

from soliterm import store


def test_ui_preferences_are_unset_until_saved():
    cfg = store.load_config()
    for key in ("color", "code_skin", "camo_theme", "view"):
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
