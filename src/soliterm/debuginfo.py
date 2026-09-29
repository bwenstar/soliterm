"""soliterm.debuginfo - what --debug-info prints for a bug report.

The report only looks. It runs before the aisle-cli files are copied over
and reads our files itself, not through the store, which would move a
damaged file aside or note what went wrong. So nothing is written, moved
or migrated, and the files are shown as the next run will find them.
"""

from __future__ import annotations

import json
import locale
import os
import platform
import shutil
import sys

from . import __version__, migrate, store
from . import aisleriot as ar

# the environment that decides how the game draws, and how text comes out
TERMINAL_VARS = ("TERM", "COLORTERM", "TERM_PROGRAM", "COLORFGBG", "NO_COLOR")
LOCALE_VARS = ("LC_ALL", "LC_CTYPE", "LANG")


def report(no_sync: bool = False) -> list[str]:
    """The report, one `label: value` line for each thing a bug report
    needs. `no_sync` is --no-sync, which the store hasn't been told yet."""
    config_state, config = _json_file(store.config_path())
    stats_state, stats = _json_file(store.stats_path())
    where = _tilde(sys.executable) if sys.executable else "path unknown"
    python = f"{platform.python_version()} {platform.python_implementation()} ({where})"
    old = ", ".join(f"{_tilde(path)} ({_state(path)[0]})" for path in migrate._old_paths())
    return [
        f"soliterm: {__version__}",
        f"python: {python}",
        f"platform: {platform.platform()}",
        f"terminal: {_terminal()}",
        f"curses: {_curses()}",
        f"locale: {_locale()}",
        f"config: {_tilde(store.config_path())} ({config_state})",
        f"stats: {_tilde(store.stats_path())} ({stats_state})",
        f"aisleriot keyfile: {_tilde(ar.keyfile_path())} ({_state(ar.keyfile_path())[0]})",
        f"aisleriot program: {_program()}",
        f"sharing: {_sharing(no_sync, config, stats)}",
        f"aisle-cli files: {old}",
    ]


def text(no_sync: bool = False, encoding: str | None = None) -> str:
    """The report as one string that `encoding` can always write. A name
    from the environment or a path that the terminal can't show comes out
    as a backslash escape, so the report still prints in full."""
    encoding = encoding or "utf-8"
    joined = "\n".join(report(no_sync))
    return joined.encode(encoding, "backslashreplace").decode(encoding)


def _tilde(path: str) -> str:
    """`path` with the home folder written as ~, which also keeps the
    player's name out of a public bug report."""
    home = os.path.expanduser("~").rstrip(os.sep)
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :]
    return path


def _state(path: str) -> tuple[str, bytes | None]:
    """Whether the file is "there", "not there" or "can't be read (why)",
    and what is in it when it could be read."""
    try:
        with open(path, "rb") as fh:
            return "there", fh.read()
    except FileNotFoundError:
        return "not there", None
    except OSError as exc:
        return f"can't be read ({exc.strerror or exc})", None


def _json_file(path: str) -> tuple[str, dict]:
    """How one of our JSON files stands, and the object in it ({} if there
    isn't one). A broken file is what the store would move aside."""
    state, raw = _state(path)
    if state == "not there":
        return "not there yet", {}  # made once there is something to keep
    if raw is None:
        return state, {}
    try:
        data = json.loads(raw)  # read as the store reads it (see _read_json)
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        return "there but broken (the next run moves it aside)", {}
    return state, data


def _env(names: tuple[str, ...]) -> str:
    return " ".join(f"{name}={os.environ.get(name, 'unset')}" for name in names)


def _terminal() -> str:
    return f"{_env(TERMINAL_VARS)}; {_size()}; {_tty('stdin')}, {_tty('stdout')}"


def _size() -> str:
    """The size of the first of stdout, stdin and stderr that is a
    terminal, so it still shows with stdout piped into a clipboard tool."""
    for fd in (1, 0, 2):
        try:
            size = os.get_terminal_size(fd)
        except (OSError, ValueError):
            continue
        return f"{size.columns}x{size.lines}"
    return "size unknown"


def _tty(name: str) -> str:
    stream = getattr(sys, name)
    try:
        tty = stream is not None and stream.isatty()
    except (AttributeError, OSError, ValueError):  # a stand-in stream, or closed
        tty = False
    return f"{name} is a terminal" if tty else f"{name} isn't a terminal"


def _curses() -> str:
    try:
        import curses
    except ImportError as exc:
        return f"not available ({exc})"
    from .cli import _check_terminal  # here, since cli imports this module

    found = getattr(curses, "ncurses_version", None)
    if found:
        version = f"ncurses {found.major}.{found.minor}.{found.patch}"
    else:
        version = "curses (version unknown)"
    problem, note = _check_terminal()
    if problem:
        return f"{version}; {problem}"
    if note:
        return f"{version}, the full-screen game can run here; {note}"
    return f"{version}, the full-screen game can run here"


def _locale() -> str:
    preferred = locale.getpreferredencoding(False)
    stdout = getattr(sys.stdout, "encoding", None) or "unknown"
    return f"{_env(LOCALE_VARS)}; preferred {preferred}, stdout {stdout}"


def _program() -> str:
    for name in ("sol", "aisleriot"):
        path = shutil.which(name)
        if path:
            return _tilde(path)
    return "not found"


def _sharing(no_sync: bool, config: dict, stats: dict) -> str:
    """Whether results go to AisleRiot, and if not why, then the merge
    marker and how many games are waiting to go into its keyfile."""
    if no_sync:
        state = "off for this run (--no-sync)"
    elif store.sync_disabled():
        # --no-sync is handed to the store after the report, so this is
        # the environment
        state = "off for this run (SOLITERM_NO_AISLERIOT is set)"
    elif config.get("sync_aisleriot") is False:
        state = "off (sync_aisleriot is false in config.json)"
    elif not ar.available():
        state = "off (no AisleRiot here)"
    else:
        state = "on"
    # the markers as written, not the store's guess for stats older than them
    marked = store._meta(stats).get("merged_into_aisleriot") is True
    merged = marked or config.get("merged_into_aisleriot") is True
    waiting = sum(stat["total"] for stat in store._unsynced(stats).values())
    return f"{state}; merged: {'yes' if merged else 'not yet'}; games waiting: {waiting}"
