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
from typing import Dict, List, Optional

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
        with open(keyfile_path(), "r", encoding="utf-8") as fh:
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


def _write_text(text: str) -> bool:
    """Write the keyfile atomically.

    The file is shared with a live program (AisleRiot), so we write a temp file
    in the same directory and os.replace() it onto the target: a crash or full
    disk can never leave the keyfile truncated or half-written. The temp file
    takes the keyfile's mode, so a replaced keyfile keeps its permissions.
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
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, keyfile_path())
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
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
    current = None
    for line in _read_text().splitlines():
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
    try:
        text = _read_text()
    except OSError:
        return False
    # Preserve the file's exact trailing newline: splitlines() drops the
    # final-newline artifact without eroding real blank lines, and we restore
    # the terminator verbatim when rejoining. (The file is a Linux GNOME config
    # and always uses '\n'; _read_text normalises line endings anyway.)
    lines = text.splitlines()
    final = "\n" if text.endswith("\n") else ""   # keep "no trailing newline" as-is
    eol = "\n"

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
        lines[stat_idx] = new_line
    elif header_idx is not None:
        # insert right after the section header
        lines.insert(header_idx + 1, new_line)
    else:
        # section doesn't exist: append a fresh one (blank-line separated)
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"[{section}]")
        lines.append(new_line)

    out = eol.join(lines) + final
    return _write_text(out)


def all_known_stats() -> Dict[str, Dict[str, int]]:
    """Every stat we recognise from the keyfile, keyed by OUR game key."""
    out: Dict[str, Dict[str, int]] = {}
    for section, game_key in SECTION_TO_GAME.items():
        s = read_stat(section)
        if s is not None:
            out[game_key] = s
    return out
