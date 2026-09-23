"""Shared fixtures for the test suite.

Every test runs with HOME and the XDG base directories pointed into its own
tmp_path, so no test can read or write the player's real config, stats or
AisleRiot keyfile. The store and keyfile modules resolve their paths at call
time, so setting the environment here is enough.
"""

import pytest

from soliterm import aisleriot as ar
from soliterm import store


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("LOGNAME", "tester")
    monkeypatch.delenv("NO_COLOR", raising=False)
    # the store's notices are per run; start each test with none
    monkeypatch.setattr(store, "_notices", [])
    # AisleRiot may be installed here; a test that wants it says so
    monkeypatch.setattr(ar, "installed", lambda: False)
    return home


@pytest.fixture
def keyfile(isolated_home):
    """Write a fake AisleRiot keyfile into the test home; returns its path.

    The keyfile being there is what makes the store treat AisleRiot as
    installed and start syncing.
    """
    path = isolated_home / ".config" / "gnome-games" / "aisleriot"

    def write(text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    write.path = path
    return write
