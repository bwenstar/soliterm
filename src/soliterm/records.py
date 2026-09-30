"""soliterm.records - records, dailies and achievements, from the history.

Nothing here is stored. Each function goes through the games in
history.jsonl, as history.games() gives them, when it's asked, so what
it says always agrees with the history, and a list of games can be
passed in instead: reading the history takes longer than any of these,
so a screen that shows more than one reads it once and passes it to
each. A line of a game only a newer version knows is left out of the
records of the games this one knows.

So --reset-stats, which copies the history to history.jsonl.bak and then
clears it, takes the records, the dailies and the achievements with it,
and putting history.jsonl.bak back as history.jsonl brings them back.
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
# takes 5 off for each card turned from the stock. Pyramid scores a point
# for each card taken off, and as AisleRiot counts a win, one can leave a
# line of cards down the right edge. In every game a higher score is
# better, and a lost game keeps what it scored up to then.
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
    "pyramid": None,
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


def _won_days(entries: list[dict]) -> dict[date, int]:
    """The days with a daily won, in any game, each with the place in
    `entries` of the first line that won one."""
    found: dict[date, int] = {}
    for n, e in enumerate(entries):
        daily = e.get("daily")
        if e["result"] == "won" and isinstance(daily, str) and is_day(daily):
            found.setdefault(date.fromisoformat(daily), n)
    return found


def _runs(days: dict[date, int]) -> dict[date, int]:
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
    return _streak(_runs(_won_days(entries)), today)


def _streak(runs: dict[date, int], today: date | None) -> Streak:
    """daily_streak() from _runs()."""
    if today is None:
        today = deals.today()
    current = runs.get(today) or runs.get(today - _DAY, 0)
    return Streak(current, max(runs.values(), default=0))


class Achievement(NamedTuple):
    """Something to do, and whether it's done."""

    earned: bool
    at: str | None  # when it was earned: the "at" of the line that earned it
    done: int  # how far along it is, out of goal
    goal: int
    left: tuple[str, ...] = ()  # the games still to win, for a win in every game


class Achievements(NamedTuple):
    """Every achievement, and how far along each is."""

    clean: dict[str, Achievement]  # each game won with no hint and no undo
    every_game: Achievement  # a win in every game
    seven_dailies: Achievement  # dailies won seven days in a row


_WEEK = 7  # the days in a row for seven dailies


def _earned(
    entries: list[dict], n: int | None, done: int, goal: int, left: tuple[str, ...] = ()
) -> Achievement:
    """An achievement earned by the nth line of `entries`, or if n is None,
    one not earned yet and `done` out of `goal` of the way there."""
    if n is None:
        return Achievement(False, None, done, goal, left)
    return Achievement(True, entries[n]["at"], goal, goal)


def achievements(entries: list[dict] | None = None, today: date | None = None) -> Achievements:
    """What's been done, from `entries`, the history by default. Like the
    rest here, it's worked out when it's asked for and never stored, and
    each is earned by the first line that did it.

    A clean win is a win with no hint asked for and no move undone, so it
    has to be a line that counts both, as from 1.1 on. A win in every game
    is in every game this version has, so a game added later is one left
    to win until it's won. Seven dailies is earned when daily_streak()'s
    longest reaches seven days, and until then it's as far along as the
    streak now, on `today`, today by default.
    """
    if entries is None:
        entries = history.games()
    first_win: dict[str, int] = {}
    clean: dict[str, int] = {}
    known = set(GAME_ORDER)
    for n, e in enumerate(entries):
        key = e["game"]
        if e["result"] != "won" or key not in known:
            continue
        first_win.setdefault(key, n)
        if key not in clean and history.counts(e) == (0, 0):
            clean[key] = n
    left = tuple(key for key in GAME_ORDER if key not in first_win)
    last_won = None if left else max(first_win.values())
    days = _won_days(entries)
    runs = _runs(days)
    # for each seven days in a row, the line that won the last of them to
    # be won, and the first of those earned it
    weeks = [
        max(days[day - back * _DAY] for back in range(_WEEK))
        for day, run in runs.items()
        if run >= _WEEK
    ]
    return Achievements(
        {key: _earned(entries, clean.get(key), 0, 1) for key in GAME_ORDER},
        _earned(entries, last_won, len(first_win), len(GAME_ORDER), left),
        _earned(entries, min(weeks, default=None), _streak(runs, today).current, _WEEK),
    )
