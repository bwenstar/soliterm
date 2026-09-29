"""soliterm.records - each game's records and the dailies, from the history.

Nothing here is stored. Each function goes through the games in
history.jsonl, as history.games() gives them, when it's asked, so what
it says always agrees with the history, and a list of games can be
passed in instead. A line of a game only a newer version knows is left
out of the records of the games this one knows.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

from . import deals, history
from .engine import GAME_ORDER, GAMES, is_day
from .history import Streak

# What every win of a game scores, where they all score the same, so a
# screen can tell a best score that won from one that came close, and say
# how close, as 38 of 52. These games score what a win completes, the
# cards on the foundations in Klondike, the runs in Spider and Scorpion,
# the cards cleared in Golf, so every win scores the most there is, as
# AisleRiot's help gives it. None is a game whose wins score differently:
# Triple Peaks scores each card by the length of the run it's in, with a
# bonus for each peak and for clearing the lot, and in standard scoring
# takes 5 off for each card turned from the stock. In every game a higher
# score is better, and a lost game keeps what it scored up to then.
# tests/test_records.py fails for a game missing from here, so a new game
# has to say which it is.
WIN_SCORE: dict[str, int | None] = {
    "klondike": 52,
    "spider": 96,
    "spiderette": 48,
    "freecell": 52,
    "eightoff": 52,
    "golf": 35,
    "triplepeaks": None,
    "yukon": 52,
    "scorpion": 100,
    "bakersdozen": 52,
    "fortythieves": 1000,
    "canfield": 52,
}


class Best(NamedTuple):
    """A game in the history that holds a record: when it was played, on
    which deal with which options, and how it went. A field its line has
    nothing to go by for is None, or {} for the options."""

    at: str
    deal: int | None
    options: dict
    daily: str | None  # the day, for a daily deal
    won: bool
    seconds: int
    moves: int
    score: int | None


class Records(NamedTuple):
    """One game's records here."""

    played: int
    won: int
    fastest: Best | None  # the fastest win, fewer moves breaking a tie
    fewest: Best | None  # the win in the fewest moves, the faster breaking a tie
    # the best score for each set of options played with, as the options
    # list them, lost games too
    best_scores: tuple[Best, ...]
    streak: Streak  # the win streak now and the longest


def _best(e: dict) -> Best:
    deal, options, score, daily = (e.get(k) for k in ("deal", "options", "score", "daily"))
    return Best(
        e["at"],
        deal if type(deal) is int and deal >= 0 else None,
        dict(options) if isinstance(options, dict) else {},
        daily if is_day(daily) else None,
        e["result"] == "won",
        e["seconds"],
        e["moves"],
        score if type(score) is int and score >= 0 else None,
    )


def _by_time(e: dict) -> tuple[int, int]:
    return e["seconds"], e["moves"]


def _by_moves(e: dict) -> tuple[int, int]:
    return e["moves"], e["seconds"]


def _options_key(e: dict) -> tuple | None:
    """The options a game was played with, as something to look them up by,
    or None if its line has none to go by."""
    options = e.get("options")
    if not isinstance(options, dict):
        return None
    found = tuple(sorted(options.items()))
    try:
        hash(found)
    except TypeError:  # a list in a hand-edited line, say
        return None
    return found


def _keep_score(kept: dict[tuple, dict], e: dict) -> None:
    """Keep e in `kept` if it's the best score yet with its options."""
    score, options = e.get("score"), _options_key(e)
    if type(score) is not int or score < 0 or options is None:
        return
    if options not in kept or score > kept[options]["score"]:
        kept[options] = e


def _in_options_order(key: str, kept: dict[tuple, dict]) -> tuple[Best, ...]:
    """The best scores kept, in the order the game lists its options'
    values, the defaults first, and any it doesn't know after them."""
    spec = GAMES[key].option_spec()

    def place(b: Best) -> list[int]:
        return [
            allowed.index(b.options[name]) if b.options.get(name) in allowed else len(allowed)
            for name, _, allowed in spec
        ]

    return tuple(sorted(map(_best, kept.values()), key=place))


def records(entries: list[dict] | None = None) -> dict[str, Records]:
    """Every game's records, in menu order, from one pass over `entries`,
    the history by default.

    The best score is counted over every game, lost as well as won: a game
    not won yet still says how close it came, and a game of Triple Peaks
    that clears two peaks and then gets stuck can score more than a win that
    took the whole stock. When two games tie for a record, the first to get
    there keeps it.
    """
    if entries is None:
        entries = history.games()
    played = dict.fromkeys(GAME_ORDER, 0)
    won = dict.fromkeys(GAME_ORDER, 0)
    fastest: dict[str, dict] = {}
    fewest: dict[str, dict] = {}
    scores: dict[str, dict[tuple, dict]] = {key: {} for key in GAME_ORDER}
    streaks = dict.fromkeys(GAME_ORDER, Streak(0, 0))
    for e in entries:
        key = e["game"]
        if key not in played:
            continue  # a game from a newer version
        win = e["result"] == "won"
        played[key] += 1
        streaks[key] = streaks[key].after(win)
        if win:
            won[key] += 1
            if key not in fastest or _by_time(e) < _by_time(fastest[key]):
                fastest[key] = e
            if key not in fewest or _by_moves(e) < _by_moves(fewest[key]):
                fewest[key] = e
        _keep_score(scores[key], e)
    return {
        key: Records(
            played[key],
            won[key],
            _best(fastest[key]) if key in fastest else None,
            _best(fewest[key]) if key in fewest else None,
            _in_options_order(key, scores[key]),
            streaks[key],
        )
        for key in GAME_ORDER
    }


class DealBest(NamedTuple):
    """The best earlier win of the deal a game was just played on, and
    whether that game beat it."""

    best: Best
    beaten: bool


def _deal_of(e: dict) -> tuple | None:
    """The game, deal number and options of a line, or None if it has no
    deal or options to go by."""
    deal, options = e.get("deal"), e.get("options")
    if type(deal) is not int or not isinstance(options, dict):
        return None
    return e["game"], deal, options


def on_this_deal(entry: dict, entries: list[dict] | None = None) -> DealBest | None:
    """How `entry`, the line of a game just recorded, did against the best
    earlier win of the same game, deal number and options, for the win
    banner to say "a new best on this deal (was 3:10)" or "your best on
    this deal: 2:41, 98 moves". A daily is its deal number with the
    standard options, so it's the same deal as a plain one of that number
    with those options, as it has the same cards.

    The earlier games are the ones before `entry` in `entries`, the history
    by default, or all of them when it isn't there, as when its line
    couldn't be written. Returns None when none of them won the deal.

    A win beats the best on time, and on moves when the times are the same.
    Time is what the statistics, AisleRiot's too, rank wins by, and it's
    counted in whole seconds, so a quick game can tie.
    """
    if entries is None:
        entries = history.games()
    this = _deal_of(entry)
    if this is None:
        return None
    best = None
    for e in entries:
        if e is entry or e == entry:
            break
        won = e["result"] == "won" and _deal_of(e) == this
        if won and (best is None or _by_time(e) < _by_time(best)):
            best = e
    if best is None:
        return None
    beaten = entry["result"] == "won" and _by_time(entry) < _by_time(best)
    return DealBest(_best(best), beaten)


class DayResult(NamedTuple):
    """How a game's daily deal went on a day."""

    result: str | None  # "won", "lost" when played and not won yet, None when not played
    best: Best | None  # the best of that day's wins, on time with moves breaking a tie


def dailies(entries: list[dict] | None = None, day: date | None = None) -> dict[str, DayResult]:
    """How each game's daily deal went on `day`, today by default, in menu
    order, from `entries`, the history by default.

    A daily belongs to the day of its deal, the "daily" of its line, not
    the day it was finished: one started before midnight and won after it
    is the day before's, and so is one resumed from a save the next day.
    The plain deal of a daily's number isn't that daily, as tomorrow's can
    be played today that way.

    This is only there to show. Nothing should refuse to deal a daily, or
    deal it any differently, because of what it says: a daily can always
    be played again. The dailies came without a "you've played today's
    daily" state on purpose, as it was one a player could get stuck in.
    """
    if entries is None:
        entries = history.games()
    wanted = (deals.today() if day is None else day).isoformat()
    found = dict.fromkeys(GAME_ORDER, DayResult(None, None))
    fastest: dict[str, dict] = {}
    for e in entries:
        key = e["game"]
        if e.get("daily") != wanted or key not in found:
            continue
        if e["result"] != "won":
            found[key] = DayResult("lost", None)
        elif key not in fastest or _by_time(e) < _by_time(fastest[key]):
            fastest[key] = e
    for key, e in fastest.items():  # won, whatever else was lost that day
        found[key] = DayResult("won", _best(e))
    return found


_DAY = timedelta(days=1)


def _won_days(entries: list[dict]) -> set[date]:
    """The days with a daily won, in any game."""
    found = set()
    for e in entries:
        daily = e.get("daily")
        if e["result"] == "won" and isinstance(daily, str) and is_day(daily):
            found.add(date.fromisoformat(daily))
    return found


def _runs(days: set[date]) -> dict[date, int]:
    """How many days in a row each of `days` ends."""
    found: dict[date, int] = {}
    last: date | None = None
    for day in sorted(days):
        found[day] = found[last] + 1 if last is not None and last + _DAY == day else 1
        last = day
    return found


def daily_streak(entries: list[dict] | None = None, today: date | None = None) -> Streak:
    """The days in a row with a daily won, in any game, now and the longest,
    from `entries`, the history by default.

    The streak now runs to today, or to yesterday while today's dailies
    aren't won yet, so it only ends when a whole day goes by without one.
    A daily counts for the day of its deal, as in dailies(), and a daily of
    a game only a newer version has counts too, as the day was still won.
    Days are counted on the calendar, one date after another, and never
    from the times the games were finished, so a change of the clocks, or
    a game won after midnight, doesn't move a daily to another day.
    """
    if entries is None:
        entries = history.games()
    if today is None:
        today = deals.today()
    runs = _runs(_won_days(entries))
    current = runs.get(today) or runs.get(today - _DAY, 0)
    return Streak(current, max(runs.values(), default=0))
