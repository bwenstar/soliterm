"""Shared fixtures for the test suite.

Every test runs with HOME and the XDG base directories pointed into its own
tmp_path, so no test can read or write the player's real config, stats or
AisleRiot keyfile. The store and keyfile modules resolve their paths at call
time, so setting the environment here is enough.
"""

import signal

import pytest

from soliterm import aisleriot as ar
from soliterm import saves, store


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
    monkeypatch.delenv("SOLITERM_NO_AISLERIOT", raising=False)
    # the store's notices and --no-sync are per run; start each test afresh
    monkeypatch.setattr(store, "_notices", [])
    monkeypatch.setattr(store, "_no_sync", False)
    monkeypatch.setattr(saves, "_kept", [])
    # AisleRiot may be installed here, or even open; a test that wants it
    # says so
    monkeypatch.setattr(ar, "installed", lambda: False)
    monkeypatch.setattr(ar, "PROC_ROOT", str(tmp_path / "no-proc"))
    monkeypatch.setattr(store, "_looked_for_aisleriot", False)
    return home


@pytest.fixture
def ctrl_c():
    """Have SIGINT raise KeyboardInterrupt, as Ctrl-C does, for a test that
    sends it. A script that starts the tests in the background starts them
    with SIGINT ignored, and Python then leaves it that way."""
    before = signal.signal(signal.SIGINT, signal.default_int_handler)
    yield
    signal.signal(signal.SIGINT, before)


@pytest.fixture
def keyfile(isolated_home):
    """Write a fake AisleRiot keyfile into the test home; returns its path.

    The keyfile being there is what makes the store treat AisleRiot as
    installed and start syncing.
    """
    path = isolated_home / ".config" / "gnome-games" / "aisleriot"

    def write(text):
        path.parent.mkdir(parents=True, exist_ok=True)
        # as bytes, so Windows doesn't write each "\n" as "\r\n"
        path.write_bytes(text.encode("utf-8"))
        return path

    write.path = path
    return write
