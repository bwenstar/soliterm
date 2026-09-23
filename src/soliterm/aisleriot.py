"""soliterm.aisleriot - bridge to the installed GNOME AisleRiot statistics.

AisleRiot (the `/usr/games/sol` binary) stores per-game statistics in a GLib
GKeyFile at $XDG_CONFIG_HOME/gnome-games/aisleriot (default ~/.config/...).
Each game has a section keyed by its Scheme file name, e.g.:

    [spider.scm]
    Statistic=20;112;591;1966;
    Options=2

The Statistic value is `wins;total;best;worst;` where best/worst are winning
times in whole seconds (best = fastest, worst = slowest; 0 means "no win yet").

This module lets our CLI share that exact file so games played in either
program are mirrored in both. It edits the file surgically - only the
`Statistic=` line of the games we manage is touched; every other key, section,
comment, and the file's ordering are preserved so AisleRiot's own config
(Recent, Theme, per-game Options, ...) is never disturbed.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

# Our game keys -> AisleRiot section names. AisleRiot's config sections use the
# Scheme file name with hyphens converted to underscores (e.g. the file
# eight-off.scm is recorded under [eight_off.scm], as triple_peaks.scm shows).
GAME_TO_SECTION: Dict[str, str] = {
    "klondike": "klondike.scm",
    "spider": "spider.scm",
    "freecell": "freecell.scm",
    "eightoff": "eight_off.scm",
    "golf": "golf.scm",
    "yukon": "yukon.scm",
    "bakersdozen": "bakers_dozen.scm",
    "fortythieves": "forty_thieves.scm",
    "canfield": "canfield.scm",
}

SECTION_TO_GAME: Dict[str, str] = {v: k for k, v in GAME_TO_SECTION.items()}


def _config_base() -> str:
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return base


def gnome_games_dir() -> str:
    return os.path.join(_config_base(), "gnome-games")


def keyfile_path() -> str:
    return os.path.join(gnome_games_dir(), "aisleriot")


def available() -> bool:
    """True if AisleRiot's config location exists (so we should sync with it).

    Based purely on the (possibly XDG-overridden) config path, so test harnesses
    that point XDG_CONFIG_HOME at a temp dir don't accidentally engage with the
    real AisleRiot file.
    """
    return os.path.isdir(gnome_games_dir()) or os.path.exists(keyfile_path())


# --------------------------------------------------------------------------- #
# Low-level keyfile access
# --------------------------------------------------------------------------- #

def _read_text() -> str:
    """The keyfile's text, or "" when there is no keyfile yet.

    Only a missing file reads as empty. Any other error (no permission, an
    I/O error) is raised: taking an unreadable keyfile for an empty one would
    make the next write replace all of AisleRiot's settings and stats.
    """
    try:
        # newline="": no newline translation, so "\r\n" and a lone "\r"
        # come back exactly as they are in the file. surrogateescape: bytes
        # that aren't UTF-8 (a value in another encoding) read without an
        # error and are written back unchanged by _write_text.
        with open(keyfile_path(), "r", encoding="utf-8", errors="surrogateescape",
                  newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def readable() -> bool:
    """False if the keyfile is there but can't be read."""
    try:
        _read_text()
    except OSError:
        return False
    return True


class _Changed(Exception):
    """The keyfile is no longer what we based our edit on."""


def _write_text(text: str, expect: Optional[str] = None) -> bool:
    """Write the keyfile atomically.

    The file is shared with a live program (AisleRiot), so we write a temp file
    in the same directory and os.replace() it onto the target: a crash or full
    disk can never leave the keyfile truncated or half-written. The temp file
    takes the keyfile's mode, so a replaced keyfile keeps its permissions.

    With `expect`, the keyfile is read once more right before it is replaced,
    and _Changed is raised (with nothing written) if it no longer holds
    exactly that text.
    """
    import tempfile
    try:
        d = gnome_games_dir()
        os.makedirs(d, exist_ok=True)
        try:
            mode: Optional[int] = os.stat(keyfile_path()).st_mode & 0o7777
        except OSError:
            mode = None
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".aisleriot.", suffix=".tmp")
        try:
            if mode is not None:
                os.chmod(tmp, mode)
            with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape",
                           newline="") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            if expect is not None and _read_text() != expect:
                raise _Changed()
            os.replace(tmp, keyfile_path())
        except (OSError, _Changed) as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            if isinstance(exc, _Changed):
                raise
            return False
        return True
    except OSError:
        return False


def _is_header(line: str) -> Optional[str]:
    s = line.strip()
    if len(s) >= 2 and s.startswith("[") and s.endswith("]"):
        return s[1:-1]
    return None


def _parse_statistic(value: str) -> Optional[Dict[str, int]]:
    parts = [p for p in value.strip().split(";") if p != ""]
    if len(parts) < 4:
        return None
    try:
        wins, total, best, worst = (int(parts[0]), int(parts[1]),
                                    int(parts[2]), int(parts[3]))
    except ValueError:
        return None
    return {"wins": wins, "total": total, "best": best, "worst": worst}


def read_stat(section: str) -> Optional[Dict[str, int]]:
    """The (wins,total,best,worst) dict for a section, or None if not present.

    Raises OSError if the keyfile exists but can't be read.
    """
    return _stat_in(_read_text(), section)


def _stat_in(text: str, section: str) -> Optional[Dict[str, int]]:
    current = None
    for line in text.split("\n"):
        head = _is_header(line)
        if head is not None:
            current = head
            continue
        if current == section and "=" in line:
            key, _, val = line.partition("=")
            if key.strip() == "Statistic":
                return _parse_statistic(val)
    return None


def _format_statistic(stat: Dict[str, int]) -> str:
    return (f"Statistic={int(stat.get('wins', 0))};{int(stat.get('total', 0))};"
            f"{int(stat.get('best', 0))};{int(stat.get('worst', 0))};")


def _is_statistic_line(line: str) -> bool:
    """True if `line` is a Statistic key, matching how read_stat / GLib parse it.

    GLib (and read_stat) strip whitespace around '=', so 'Statistic = ...' and
    'Statistic\\t=\\t...' are valid Statistic keys; write_stat must recognise and
    replace them, not insert a duplicate.
    """
    if "=" not in line:
        return False
    key, _, _ = line.partition("=")
    return key.strip() == "Statistic"


def write_stat(section: str, stat: Dict[str, int]) -> bool:
    """Surgically set a section's Statistic line, preserving everything else.

    Only the targeted Statistic line changes; all other keys, sections,
    comments, ordering, and trailing whitespace are kept byte-for-byte.
    Returns False, and writes nothing, if the keyfile can't be read.
    """
    return update_stat(section, lambda current: stat) is not None


# How many times update_stat works a change out again when the keyfile keeps
# changing under it, before giving up.
_UPDATE_TRIES = 5


def update_stat(section: str,
                change: Callable[[Optional[Dict[str, int]]], Optional[Dict[str, int]]]
                ) -> Optional[Dict[str, int]]:
    """Set a section's Statistic from its value at the moment of writing.

    `change` gets the current stat (None if there is none) and returns the
    new one, or None to leave the file alone. The keyfile is read again just
    before it is replaced; if anything wrote it in the meantime, the change
    is worked out again from what is there now, so a stat saved by someone
    else is never put back to an older value.

    Returns the stat written, or None if nothing was written (the keyfile
    can't be read or written, it would not hold still, or `change` said no).

    This only closes the gap between our read and our write. AisleRiot reads
    the keyfile once when it starts and writes its own copy back whenever it
    saves, so a result we record while it is running is lost from the keyfile
    at its next save. Our stats.json still has it.
    """
    for _ in range(_UPDATE_TRIES):
        try:
            text = _read_text()
        except OSError:
            return None
        new = change(_stat_in(text, section))
        if new is None:
            return None
        try:
            ok = _write_text(_with_stat(text, section, new), expect=text)
        except _Changed:
            continue
        return new if ok else None
    return None


def _with_stat(text: str, section: str, stat: Dict[str, int]) -> str:
    """`text` with the section's Statistic line set to `stat`."""
    # GLib ends a line at "\n" and nowhere else. splitlines() would also
    # break at "\r", "\x0c", "\u2028" and others, which can sit inside a
    # value, and the rejoined file would have a newline in their place.
    # Lines in a CRLF file keep their "\r", and lines we add get one too.
    lines = text.split("\n")
    final = "\n" if text.endswith("\n") else ""   # keep "no trailing newline" as-is
    if final or lines == [""]:
        lines.pop()
    cr = "\r" if "\r\n" in text else ""

    new_line = _format_statistic(stat)
    in_section = False
    header_idx: Optional[int] = None
    stat_idx: Optional[int] = None

    for i, line in enumerate(lines):
        head = _is_header(line)
        if head is not None:
            if head == section:
                header_idx = i
                in_section = True
            elif in_section:
                in_section = False
            continue
        if in_section and stat_idx is None and _is_statistic_line(line):
            stat_idx = i

    if stat_idx is not None:
        lines[stat_idx] = new_line + ("\r" if lines[stat_idx].endswith("\r") else "")
    elif header_idx is not None:
        # insert right after the section header
        lines.insert(header_idx + 1, new_line + cr)
    else:
        # section doesn't exist: append a fresh one (blank-line separated)
        if lines and lines[-1].strip() != "":
            lines.append(cr)
        lines.append(f"[{section}]" + cr)
        lines.append(new_line + cr)

    return "\n".join(lines) + final


def all_known_stats() -> Dict[str, Dict[str, int]]:
    """Every stat we recognise from the keyfile, keyed by OUR game key."""
    out: Dict[str, Dict[str, int]] = {}
    for section, game_key in SECTION_TO_GAME.items():
        s = read_stat(section)
        if s is not None:
            out[game_key] = s
    return out
