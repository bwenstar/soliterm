"""soliterm.history - every game counted here, one line each, in
history.jsonl."""

from __future__ import annotations

import datetime
import json
import os
import re
from typing import NamedTuple

from . import store
from .engine import GAMES, Solitaire


class Streak(NamedTuple):
    current: int  # wins in a row up to the last game, so 0 after a loss
    longest: int

    def after(self, won: bool) -> Streak:
        """The streak after one more game."""
        cur = self.current + 1 if won else 0
        return Streak(cur, max(self.longest, cur))


def history_path() -> str:
    return os.path.join(store.data_dir(), "history.jsonl")


def now() -> str:
    """The local time to the second, as the history and the saves write it."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def record(g: Solitaire, won: bool, seconds: float) -> tuple[dict, dict]:
    """Count g in the statistics and add a line for it to the history.

    Returns the game's statistics after, as store.record_result does, and
    its line. Unlike the statistics, the history keeps the time of a loss.
    """
    entry = entry_of(g, won, seconds)
    with store._locked():
        stat = store.record_result(g.gamedef.key, won, seconds)
        _append(entry)
    return stat, entry


def entry_of(g: Solitaire, won: bool, seconds: float) -> dict:
    """The line record() writes for g, won or lost in `seconds`."""
    secs = round(seconds)
    entry = {
        "at": now(),
        "game": g.gamedef.key,
        "options": dict(g.options),
        "deal": g.deal_number,
        "result": "won" if won else "lost",
        "seconds": max(1, secs) if won else secs,
        "moves": g.moves,
        "score": g.score,
        **g.counts(),
    }
    if g.daily:
        entry["daily"] = g.daily
    return entry


def _append(entry: dict) -> None:
    path = history_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "ab+", opener=_for_the_player) as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell() > 0:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    # a line cut short stays one bad line, not two
                    fh.write(b"\n")
            fh.write(json.dumps(entry).encode() + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        store._notice(
            f"can't write {path} ({exc.strerror or exc}), so that game is missing from the history"
        )


def _for_the_player(path: str, flags: int) -> int:
    # a new history is the player's alone, as the other files are, where
    # one there already keeps its mode
    return os.open(path, flags, 0o600)


def games() -> list[dict]:
    """Every game in the history, oldest first.

    A line that isn't a game (one cut short, say, or from a newer version)
    is skipped, never set aside: one bad line mustn't cost the rest.
    """
    path = history_path()
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return []
    except OSError as exc:
        store._notice(
            f"can't read {path} ({exc.strerror or exc}), "
            "so the streaks and recent games are left out"
        )
        return []
    found = []
    for line in raw.splitlines():
        try:
            e = json.loads(line.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        if _is_game(e):
            found.append(e)
    return found


# The start of the time now() writes, as far as --stats shows it, and a game
# key the way the games have them, a newer version's too. --stats prints
# both, so a line with anything else in them, such as the escapes of a
# hand-edited file, isn't a game.
_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
_KEY = re.compile(r"[a-z0-9_-]{1,32}")


def _is_game(e: object) -> bool:
    return (
        isinstance(e, dict)
        and isinstance(e.get("at"), str)
        and _AT.match(e["at"]) is not None
        and isinstance(e.get("game"), str)
        and _KEY.fullmatch(e["game"]) is not None
        and e.get("result") in ("won", "lost")
        and all(type(e.get(k)) is int and e[k] >= 0 for k in ("seconds", "moves"))
    )


def counts(e: dict) -> tuple[int | None, int | None]:
    """The hints asked for and the moves undone in a game in the history,
    each None where it isn't known, as for a line from before they were
    counted, or one of a game resumed from a save that old."""

    def known(name: str) -> int | None:
        n = e.get(name)
        return n if type(n) is int and n >= 0 else None

    return known("hints"), known("undos")


def streaks() -> dict[str, Streak]:
    """Each game's win streak now and its longest, for the games in the history."""
    found: dict[str, Streak] = {}
    for e in games():
        found[e["game"]] = found.get(e["game"], Streak(0, 0)).after(e["result"] == "won")
    return found


def streak_text(key: str) -> str:
    """The win streak a game of `key` is on, as the win banner and text mode
    put it, or "" if it is under two wins."""
    cur, longest = streaks().get(key, Streak(0, 0))
    if cur < 2:
        return ""
    if cur == longest:
        return f"{cur} wins in a row, your longest yet"
    return f"{cur} wins in a row (longest {longest})"


def recent(n: int) -> list[dict]:
    """The last n games in the history, newest first."""
    return games()[::-1][:n]


def any_games() -> bool:
    return bool(games())


def line(e: dict) -> str:
    """A game as --stats lists it, as in
    2026-09-24 14:05  Klondike        won     2:22  131 moves
    with "  daily" after it for a daily deal.
    """
    when = e["at"][:16].replace("T", " ")
    key, moves = e["game"], e["moves"]
    name = GAMES[key].name if key in GAMES else key  # a game from a newer version
    secs = store.fmt_time(e["seconds"])
    plural = "" if moves == 1 else "s"
    daily = "  daily" if e.get("daily") else ""
    return f"{when}  {name:<16}{e['result']:<6}{secs:>6}{moves:>5} move{plural}{daily}"


def backup() -> str | None:
    """Copy the history to history.jsonl.bak before --reset-stats clears it.

    Returns the backup, or None if there is no history; raises OSError if
    it can't be copied.
    """
    kept = history_path() + ".bak"
    return kept if store._copy_file(history_path(), kept) else None


def clear() -> None:
    path = history_path()
    with store._locked():
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            store._notice(
                f"couldn't clear {path} ({exc.strerror or exc}), so the history is still there"
            )
