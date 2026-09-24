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
import re
import shutil
from typing import Callable

# Our game keys -> AisleRiot section names. AisleRiot's config sections use the
# Scheme file name with hyphens converted to underscores (e.g. the file
# eight-off.scm is recorded under [eight_off.scm], as triple_peaks.scm shows).
GAME_TO_SECTION: dict[str, str] = {
    "klondike": "klondike.scm",
    "spider": "spider.scm",
    "spiderette": "spiderette.scm",
    "freecell": "freecell.scm",
    "eightoff": "eight_off.scm",
    "golf": "golf.scm",
    "yukon": "yukon.scm",
    "bakersdozen": "bakers_dozen.scm",
    "fortythieves": "forty_thieves.scm",
    "canfield": "canfield.scm",
}

SECTION_TO_GAME: dict[str, str] = {v: k for k, v in GAME_TO_SECTION.items()}


def _config_base() -> str:
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return base


def gnome_games_dir() -> str:
    return os.path.join(_config_base(), "gnome-games")


def keyfile_path() -> str:
    return os.path.join(gnome_games_dir(), "aisleriot")


def installed() -> bool:
    """True if the AisleRiot program (sol, or aisleriot) is on the PATH."""
    return any(shutil.which(name) for name in ("sol", "aisleriot"))


def available() -> bool:
    """True if there is an AisleRiot to share stats with: its keyfile is
    there, or the program is installed and will make one once it has run.

    An empty gnome-games folder isn't enough, as other GNOME games keep
    their settings there too. The keyfile is looked for at the (possibly
    XDG-overridden) config path, so test harnesses that point
    XDG_CONFIG_HOME at a temp dir never reach the real AisleRiot file.
    """
    return os.path.exists(keyfile_path()) or installed()


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
        with open(keyfile_path(), encoding="utf-8", errors="surrogateescape", newline="") as fh:
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


def _write_text(text: str, expect: str | None = None) -> bool:
    """Write the keyfile atomically.

    The file is shared with a live program (AisleRiot), so we write a temp file
    in the same directory and os.replace() it onto the target: a crash or full
    disk can never leave the keyfile truncated or half-written. The temp file
    takes the keyfile's mode, so a replaced keyfile keeps its permissions.
    The gnome-games folder is AisleRiot's to make: if it isn't there yet,
    nothing is written.

    With `expect`, the keyfile is read once more right before it is replaced,
    and _Changed is raised (with nothing written) if it no longer holds
    exactly that text.
    """
    import tempfile

    try:
        d = gnome_games_dir()
        try:
            mode: int | None = os.stat(keyfile_path()).st_mode & 0o7777
        except OSError:
            mode = None
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".aisleriot.", suffix=".tmp")
        try:
            if mode is not None:
                os.chmod(tmp, mode)
            with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
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


# The keyfile is read here the way GLib reads it, so that we and AisleRiot
# always see the same numbers. GLib's idea of white space (g_ascii_isspace)
# leaves out the vertical tab.
_SPACE = " \t\n\f\r"


def _split(text: str) -> list[str]:
    """`text` in lines as GLib splits it: at "\n" only, dropping the "\r" of
    a "\r\n". On a last line with no "\n" after it, a "\r" is kept as part
    of the line.
    """
    lines = text.split("\n")
    return [s[:-1] if s.endswith("\r") and i < len(lines) - 1 else s for i, s in enumerate(lines)]


def _is_header(line: str) -> str | None:
    s = line.lstrip(_SPACE).rstrip(" \t")
    if len(s) >= 2 and s.startswith("[") and s.endswith("]") and "]" not in s[1:-1]:
        return s[1:-1]
    return None


_ESCAPES = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\", ";": ";"}


def _list_items(value: str) -> list[str] | None:
    """A list value split at its ";"s with escapes undone, or None if it has
    an escape GLib rejects. As in GLib, a last ";" ends the list rather than
    starting an empty item.
    """
    items: list[str] = []
    item = ""
    chars = iter(value)
    for c in chars:
        if c == "\\":
            unescaped = _ESCAPES.get(next(chars, ""), "")
            if not unescaped:
                return None
            item += unescaped  # an escaped ";" stays in the item
        elif c == ";":
            items.append(item)
            item = ""
        else:
            item += c
    if item:
        items.append(item)
    return items


# what strtol() reads: optional C white space, a sign, decimal digits
_STRTOL = re.compile(r"[ \t\n\v\f\r]*[+-]?[0-9]+")


def _glib_int(item: str) -> int | None:
    """`item` as g_key_file_get_integer_list() reads it, or None where GLib
    says it isn't a number (so "+5", "007" and "5 x" pass, "5x" and "0x5"
    don't, and a blank item is 0).
    """
    if not item:
        return None
    m = _STRTOL.match(item)
    end = m.end() if m else 0
    if end < len(item) and item[end] not in _SPACE:
        return None
    n = int(item[:end]) if m else 0
    return n if -(2**31) <= n < 2**31 else None


def _parse_statistic(value: str) -> dict[str, int]:
    """A Statistic value as AisleRiot reads it: four integers, or all zeros if
    GLib can't read the list or it doesn't hold exactly four.
    """
    items = _list_items(value.lstrip(_SPACE))
    nums = [_glib_int(i) for i in items] if items is not None else []
    if len(nums) != 4 or None in nums:
        nums = [0, 0, 0, 0]
    return {k: n or 0 for k, n in zip(("wins", "total", "best", "worst"), nums)}


def read_stat(section: str) -> dict[str, int] | None:
    """The (wins,total,best,worst) dict for a section, or None if not present.

    As in GLib, the last Statistic line wins, and a section that appears
    more than once is read as one.

    Raises OSError if the keyfile exists but can't be read.
    """
    return _stat_in(_read_text(), section)


def _stat_in(text: str, section: str) -> dict[str, int] | None:
    current = None
    value: str | None = None
    for line in _split(text):
        head = _is_header(line)
        if head is not None:
            current = head
            continue
        if current == section and _is_statistic_line(line):
            value = line.lstrip(_SPACE).partition("=")[2]
    return None if value is None else _parse_statistic(value)


def _format_statistic(stat: dict[str, int]) -> str:
    return (
        f"Statistic={int(stat.get('wins', 0))};{int(stat.get('total', 0))};"
        f"{int(stat.get('best', 0))};{int(stat.get('worst', 0))};"
    )


def _is_statistic_line(line: str) -> bool:
    """True if `line` is a Statistic key, matching how read_stat / GLib parse it.

    GLib (and read_stat) strip whitespace around '=', so 'Statistic = ...' and
    'Statistic\\t=\\t...' are valid Statistic keys; write_stat must recognise and
    replace them, not insert a duplicate.
    """
    line = line.lstrip(_SPACE)
    if "=" not in line or line.startswith("#"):
        return False
    key, _, _ = line.partition("=")
    return key.rstrip(_SPACE) == "Statistic"


def write_stat(section: str, stat: dict[str, int]) -> bool:
    """Surgically set a section's Statistic line, preserving everything else.

    Only the targeted Statistic line changes; all other keys, sections,
    comments, ordering, and trailing whitespace are kept byte-for-byte.
    Returns False, and writes nothing, if the keyfile can't be read.
    """
    return update_stat(section, lambda current: stat) is not None


# How many times update_stat works a change out again when the keyfile keeps
# changing under it, before giving up.
_UPDATE_TRIES = 5


def update_stat(
    section: str, change: Callable[[dict[str, int] | None], dict[str, int] | None]
) -> dict[str, int] | None:
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


def _with_stat(text: str, section: str, stat: dict[str, int]) -> str:
    """`text` with the section's Statistic line set to `stat`."""
    # GLib ends a line at "\n" and nowhere else. splitlines() would also
    # break at "\r", "\x0c", "\u2028" and others, which can sit inside a
    # value, and the rejoined file would have a newline in their place.
    # Lines in a CRLF file keep their "\r", and lines we add get one too.
    lines = text.split("\n")
    seen = _split(text)  # the same lines, as GLib reads them
    final = "\n" if text.endswith("\n") else ""  # keep "no trailing newline" as-is
    if final or lines == [""]:
        lines.pop()
    cr = "\r" if "\r\n" in text else ""

    new_line = _format_statistic(stat)
    in_section = False
    header_idx: int | None = None
    stat_idx: int | None = None

    for i in range(len(lines)):
        head = _is_header(seen[i])
        if head is not None:
            in_section = head == section
            if in_section:
                header_idx = i
            continue
        if in_section and _is_statistic_line(seen[i]):
            stat_idx = i  # the last one is the one GLib reads

    if stat_idx is not None:
        # keep the "\r" of a "\r\n"; one with no "\n" after it was part of
        # the old value
        lines[stat_idx] = new_line + ("\r" if seen[stat_idx] != lines[stat_idx] else "")
        return "\n".join(lines) + final

    if header_idx is not None:
        # insert right after the section header
        at, new = header_idx + 1, [new_line]
    else:
        # section doesn't exist: append a fresh one (blank-line separated)
        at = len(lines)
        new = [f"[{section}]", new_line]
        if lines and lines[-1].strip() != "":
            new.insert(0, "")
    if at == len(lines) and not final:
        # adding to the end of a file with no newline at its end: end the
        # last line first, and the file after ours. A "\r" on that line is
        # part of its value, so it keeps it by getting a "\r\n" of its own.
        if lines and (cr or lines[-1].endswith("\r")):
            lines[-1] += "\r"
        final = "\n"
    lines[at:at] = [s + cr for s in new]
    return "\n".join(lines) + final


def all_known_stats() -> dict[str, dict[str, int]]:
    """Every stat we recognise from the keyfile, keyed by OUR game key."""
    out: dict[str, dict[str, int]] = {}
    for section, game_key in SECTION_TO_GAME.items():
        s = read_stat(section)
        if s is not None:
            out[game_key] = s
    return out
