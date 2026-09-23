"""The autouse fixture in conftest.py keeps every test away from real data."""

import os

from soliterm import aisleriot as ar
from soliterm import store


def test_store_and_keyfile_paths_live_under_the_test_home(isolated_home):
    for path in (store.config_path(), store.stats_path(), ar.keyfile_path()):
        assert path.startswith(str(isolated_home) + os.sep)


def test_home_and_user_are_faked(isolated_home):
    assert os.path.expanduser("~") == str(isolated_home)
    assert os.environ["USER"] == "tester"


def test_a_fresh_home_has_no_aisleriot_and_no_stats():
    assert not ar.available()
    assert not store.syncing()
    assert store.load_stats() == {}
    assert store.load_config() == store.DEFAULT_CONFIG


def test_the_keyfile_fixture_turns_syncing_on(keyfile):
    keyfile("[klondike.scm]\nStatistic=1;2;3;4;\n")
    assert ar.available() and store.syncing()
    assert store.get_stat("klondike") == {"wins": 1, "total": 2, "best": 3, "worst": 4}
