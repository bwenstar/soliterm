"""The records of each game, worked out from the history: games played and
won, the fastest win, the fewest moves, the best score, the longest
streak, and how a game just played did against its deal's best. And the
dailies of a day, and the streak of days with a daily won."""

import time
from datetime import date, timedelta

import pytest

from soliterm import deals, history, records
from soliterm.engine import GAME_ORDER, GAMES, Card
from soliterm.history import Streak
from soliterm.records import Best, DayResult, DealBest, Records

from helpers import EXPECTED_CARDS, clear_board, deal

AT = "2026-09-24T14:05:11+10:00"
KLONDIKE = {"draw": 1, "redeals": "standard"}
STANDARD = {"scoring": "standard"}
MULTIPLIER = {"scoring": "multiplier"}


def game(key="klondike", result="won", seconds=100, moves=50, **more):
    """A line of the history, as history.record writes it."""
    options = KLONDIKE if key == "klondike" else GAMES[key].default_options()
    e = {
        "at": AT,
        "game": key,
        "options": options,
        "deal": 7,
        "result": result,
        "seconds": seconds,
        "moves": moves,
        "score": 0,
    }
    return {**e, **more}


def best(e):
    return Best(
        e["at"],
        e["deal"],
        e["options"],
        e.get("daily"),
        e["result"] == "won",
        e["seconds"],
        e["moves"],
        e["score"],
    )


NOTHING = Records(0, 0, None, None, (), Streak(0, 0))


def test_a_history_with_no_games_has_every_game_with_no_records():
    found = records.records([])
    assert list(found) == GAME_ORDER
    assert all(r == NOTHING for r in found.values())


def test_the_records_come_from_the_history_by_default():
    assert records.records() == records.records([])
    g = deal("golf", 3)
    history.record(g, True, 61)
    (e,) = history.games()
    assert records.records()["golf"].fastest == best(e)


def test_games_played_and_won_count_each_game_on_its_own():
    lines = [game(), game(result="lost"), game("golf", "lost"), game()]
    found = records.records(lines)
    assert found["klondike"][:2] == (3, 2)
    assert found["golf"][:2] == (1, 0)
    assert found["spider"] == NOTHING


def test_the_fastest_win_is_the_shortest_time_with_fewer_moves_breaking_a_tie():
    lines = [
        game(seconds=90, moves=80, at="2026-09-20T10:00:00+10:00"),
        game(result="lost", seconds=20, moves=5),  # a loss holds no record
        game(seconds=60, moves=70, deal=12, at="2026-09-21T10:00:00+10:00"),
        game(seconds=60, moves=65, deal=13, at="2026-09-22T10:00:00+10:00"),
        game(seconds=60, moves=65, deal=14, at="2026-09-23T10:00:00+10:00"),
        game(seconds=75, moves=40),
    ]
    fastest = records.records(lines)["klondike"].fastest
    # the first to get there keeps it
    assert fastest == best(lines[3])
    assert (fastest.seconds, fastest.moves, fastest.deal) == (60, 65, 13)
    assert fastest.at == "2026-09-22T10:00:00+10:00"


def test_the_fewest_moves_is_the_win_in_fewest_with_the_faster_breaking_a_tie():
    lines = [
        game(seconds=60, moves=90),
        game(result="lost", seconds=300, moves=3),
        game(seconds=200, moves=41, deal=21),
        game(seconds=150, moves=41, deal=22),
        game(seconds=150, moves=41, deal=23),
    ]
    fewest = records.records(lines)["klondike"].fewest
    assert fewest == best(lines[3])
    assert (fewest.moves, fewest.seconds, fewest.deal) == (41, 150, 22)


def test_a_record_says_which_deal_with_which_options_and_when():
    e = game(
        options={"draw": 3, "redeals": "unlimited"},
        deal=20260924,
        daily="2026-09-24",
        seconds=141,
        moves=98,
        score=52,
        at="2026-09-24T22:17:03+10:00",
    )
    fastest = records.records([e])["klondike"].fastest
    assert fastest == Best(
        at="2026-09-24T22:17:03+10:00",
        deal=20260924,
        options={"draw": 3, "redeals": "unlimited"},
        daily="2026-09-24",
        won=True,
        seconds=141,
        moves=98,
        score=52,
    )


@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_game_says_whether_its_wins_all_score_the_same(key):
    # a new game has to say, or it gets no best score
    assert key in records.WIN_SCORE


def test_the_table_of_scores_has_only_the_games():
    assert list(records.WIN_SCORE) == GAME_ORDER


def whole_suits(g):
    """Every card of g face up, a whole suit to each column, King at the bottom."""
    clear_board(g)
    decks = EXPECTED_CARDS[g.gamedef.key] // 52
    for col, suit in zip(g.ids_of("tableau"), "SHDC" * decks):
        g.slots[col].cards = [Card(r, suit, True) for r in range(13, 0, -1)]
    return g


@pytest.mark.parametrize(
    "key", ["klondike", "freecell", "eightoff", "yukon", "bakersdozen", "fortythieves", "canfield"]
)
def test_a_win_of_a_game_with_foundations_scores_what_the_table_says(key):
    g = whole_suits(deal(key, 1))
    g.base_val = 1  # Canfield's foundations start from a dealt rank
    g.score = 0  # as nothing is on the foundations
    assert g.finish() and g.is_won()
    assert g.score == records.WIN_SCORE[key]


@pytest.mark.parametrize("key", ["spider", "spiderette", "scorpion"])
def test_a_win_of_a_game_that_scores_its_runs_scores_what_the_table_says(key):
    g = whole_suits(deal(key, 1))
    g.gamedef.post_move(g)  # Spider sends the runs up, and both score the board
    assert g.is_won()
    assert g.score == records.WIN_SCORE[key]


def test_a_win_of_golf_scores_a_point_for_each_card_the_table_says_it_clears():
    g = deal("golf", 1)
    assert sum(len(g.cards(t)) for t in g.ids_of("tableau")) == records.WIN_SCORE["golf"]
    clear_board(g)
    (waste,), (col, *_) = g.ids_of("waste"), g.ids_of("tableau")
    g.slots[waste].cards = [Card(5, "S", True)]
    g.slots[col].cards = [Card(3, "D", True), Card(4, "H", True)]
    assert g.click(col) and g.attempt_move(col, waste)
    assert g.is_won() and g.score == 2


def test_a_game_not_won_yet_keeps_how_close_it_came():
    draw3 = {"draw": 3, "redeals": "standard"}
    lines = [
        game("canfield", "lost", score=12),
        game("canfield", "lost", score=31, deal=8),
        game("canfield", "lost", score=31, deal=9),
        game(options=draw3, result="lost", score=40),
        game(result="lost", score=30),
        game(score=52, deal=10),
        game(result="lost", score=44),
    ]
    found = records.records(lines)
    assert found["canfield"].best_scores == (best(lines[1]),)
    # drawing one first, as the options list it, and a win scores the lot
    assert found["klondike"].best_scores == (best(lines[5]), best(lines[3]))
    assert found["golf"].best_scores == ()


def test_triple_peaks_keeps_a_best_score_for_each_way_of_scoring():
    lines = [
        game("triplepeaks", options=MULTIPLIER, score=900),
        game("triplepeaks", score=120),
        # a game that clears two peaks and gets stuck can beat a win
        game("triplepeaks", "lost", options=STANDARD, score=226, deal=31),
        game("triplepeaks", score=226, deal=32),
        game("triplepeaks", options=MULTIPLIER, score=1320, deal=33),
        game("triplepeaks", score=None),
    ]
    scores = records.records(lines)["triplepeaks"].best_scores
    # standard first, as the options list it, and a tie goes to the first
    assert scores == (best(lines[2]), best(lines[4]))
    assert [(b.score, b.won, b.options) for b in scores] == [
        (226, False, STANDARD),
        (1320, True, MULTIPLIER),
    ]


def test_the_longest_streak_is_the_one_the_history_has():
    for key, won in [("klondike", True), ("klondike", True), ("golf", True), ("klondike", False)]:
        history.record(deal(key, 2), won, 60)
    history.record(deal("klondike", 2), True, 60)
    found = records.records(history.games())
    assert found["klondike"].streak == history.streaks()["klondike"] == Streak(1, 2)
    assert found["golf"].streak == Streak(1, 1)
    assert found["spider"].streak == Streak(0, 0)


def test_a_game_only_a_newer_version_knows_is_left_out():
    newer = [game(), {**game(), "game": "pyramid"}, {**game(result="lost"), "game": "chess"}]
    found = records.records(newer)
    assert list(found) == GAME_ORDER
    assert found["klondike"][:2] == (1, 1)


@pytest.mark.parametrize(
    "bad",
    [
        {"deal": None},
        {"deal": "7"},
        {"deal": True},
        {"options": None},
        {"options": ["scoring", "standard"]},
        {"options": {"scoring": ["standard"]}},
        {"score": "52"},
        {"score": -3},
        {"daily": "2026-02-30"},
        {"daily": 20260924},
    ],
)
@pytest.mark.parametrize("missing", [False, True], ids=["bad", "missing"])
def test_a_line_with_a_field_it_cant_go_by_still_counts(bad, missing):
    e = {**game("triplepeaks", daily="2026-09-24"), **bad}
    if missing:
        del e[next(iter(bad))]
    found = records.records([e])["triplepeaks"]
    assert found[:2] == (1, 1)
    b = found.fastest
    assert b.deal in (7, None)
    assert b.options == (e["options"] if isinstance(e.get("options"), dict) else {})
    assert b.daily in ("2026-09-24", None)
    assert b.score in (0, None)


def test_the_records_of_20000_games_take_well_under_100_ms():
    lines = [
        game(key, "won" if n % 3 else "lost", seconds=n % 900 + 1, moves=n % 300, score=n % 400)
        for n in range(20000)
        for key in [GAME_ORDER[n % len(GAME_ORDER)]]
    ]
    start = time.perf_counter()
    found = records.records(lines)
    took = time.perf_counter() - start
    assert sum(r.played for r in found.values()) == 20000
    assert took < 1.0  # generous, for a slow machine: it takes a few ms


# -- your best on this deal -------------------------------------------------------------


def test_the_first_win_of_a_deal_has_nothing_to_beat():
    e = game()
    assert records.on_this_deal(e, [game(result="lost"), game(deal=8), e]) is None
    assert records.on_this_deal(e, []) is None


def test_a_faster_win_is_a_new_best_on_the_deal():
    was = game(seconds=190, moves=60)
    e = game(seconds=161, moves=98)
    assert records.on_this_deal(e, [game(seconds=250), was, e]) == DealBest(best(was), True)


def test_a_slower_win_gives_the_best_to_beat():
    was = game(seconds=161, moves=98)
    e = game(seconds=190, moves=60)
    assert records.on_this_deal(e, [was, game(seconds=170), e]) == DealBest(best(was), False)


def test_moves_break_a_tie_on_time():
    was = game(seconds=161, moves=98)
    for moves, beaten in [(97, True), (98, False), (99, False)]:
        e = game(seconds=161, moves=moves, at="2026-09-25T09:00:00+10:00")
        assert records.on_this_deal(e, [was, e]) == DealBest(best(was), beaten)


def test_a_loss_beats_nothing():
    was = game(seconds=161)
    assert records.on_this_deal(game(result="lost", seconds=5), [was]) == DealBest(best(was), False)


def test_only_the_same_game_deal_and_options_count():
    e = game(seconds=300)
    lines = [
        game(seconds=100, deal=8),
        game(seconds=100, options={"draw": 3, "redeals": "standard"}),
        game("yukon", seconds=100),
        {**game(seconds=100), "deal": True},
        game(seconds=200, at="2026-09-23T10:00:00+10:00"),
    ]
    assert records.on_this_deal(e, lines) == DealBest(best(lines[-1]), False)


def test_a_daily_and_the_plain_deal_of_its_number_are_one_deal():
    # history.record writes a daily's number and the standard options, and
    # the day besides
    g = deal("klondike", 20260924)
    g.daily = "2026-09-24"
    history.record(g, True, 200)
    history.record(deal("klondike", 20260924), True, 150)
    daily, plain = history.games()
    assert (daily["deal"], daily["options"]) == (plain["deal"], plain["options"])
    assert records.on_this_deal(plain) == DealBest(best(daily), True)
    history.record(g, True, 170)
    assert records.on_this_deal(history.games()[-1]) == DealBest(best(plain), False)


def test_games_after_the_one_just_played_are_left_out():
    e = game(seconds=150)
    assert records.on_this_deal(e, [game(seconds=200), e, game(seconds=100)]) == DealBest(
        best(game(seconds=200)), True
    )


def test_a_game_whose_line_isnt_there_goes_against_them_all():
    # as when its line couldn't be written
    e = game(seconds=150, at="2026-09-25T09:00:00+10:00")
    lines = [game(seconds=200), game(seconds=120)]
    assert records.on_this_deal(e, lines) == DealBest(best(lines[1]), False)


@pytest.mark.parametrize("bad", [{"deal": None}, {"deal": "7"}, {"options": None}])
def test_a_game_with_no_deal_to_go_by_has_no_best(bad):
    assert records.on_this_deal({**game(), **bad}, [game(seconds=50)]) is None


def test_the_best_on_a_deal_comes_from_the_history_by_default():
    history.record(deal("golf", 5), True, 60)
    history.record(deal("golf", 5), True, 50)
    first, last = history.games()
    assert records.on_this_deal(last) == DealBest(best(first), True)


# -- the dailies ------------------------------------------------------------------------

TODAY = date(2026, 9, 30)
NOT_PLAYED = DayResult(None, None)


def daily(day, key="klondike", result="won", at=None, **more):
    """A daily's line, finished that evening in Sydney unless `at` says."""
    return game(
        key,
        result,
        deal=int(day.replace("-", "")),
        daily=day,
        at=at or f"{day}T20:00:00+10:00",
        **more,
    )


def won_on(*days):
    return [daily(day) for day in days]


def test_a_history_with_no_dailies_has_every_game_not_played_and_no_streak():
    # the plain deal of today's number isn't today's daily: tomorrow's can
    # be played today that way
    plain = [game(deal=20260930, at="2026-09-30T09:00:00+10:00"), game(deal=20261001)]
    for lines in [], plain:
        found = records.dailies(lines, TODAY)
        assert list(found) == GAME_ORDER
        assert all(d == NOT_PLAYED for d in found.values())
        assert records.daily_streak(lines, TODAY) == Streak(0, 0)


def test_a_daily_won_says_the_best_of_that_days_wins():
    lines = [
        daily("2026-09-30", seconds=200, moves=60),
        daily("2026-09-30", seconds=150, moves=90, at="2026-09-30T20:10:00+10:00"),
        daily("2026-09-30", seconds=150, moves=80, at="2026-09-30T20:20:00+10:00"),
        daily("2026-09-30", seconds=150, moves=80, at="2026-09-30T20:30:00+10:00"),
        daily("2026-09-30", result="lost", seconds=40, moves=10),
        daily("2026-09-29", seconds=20, moves=5),
    ]
    found = records.dailies(lines, TODAY)
    # on time, then moves, and the first to get there keeps it
    assert found["klondike"] == DayResult("won", best(lines[2]))
    assert found["klondike"].best.at == "2026-09-30T20:20:00+10:00"
    assert found["golf"] == NOT_PLAYED


def test_a_daily_played_and_not_won_is_lost_until_its_won():
    lines = [daily("2026-09-30", result="lost"), daily("2026-09-30", "golf", "lost")]
    found = records.dailies(lines, TODAY)
    assert found["klondike"] == found["golf"] == DayResult("lost", None)
    lines.append(daily("2026-09-30", seconds=300))
    found = records.dailies(lines, TODAY)
    assert found["klondike"] == DayResult("won", best(lines[-1]))
    assert found["golf"] == DayResult("lost", None)


def test_two_dailies_won_on_a_day_are_both_won():
    lines = [daily("2026-09-30"), daily("2026-09-30", "spider", seconds=500)]
    found = records.dailies(lines, TODAY)
    assert (found["klondike"].result, found["spider"].result) == ("won", "won")
    assert found["spider"].best.seconds == 500


def test_a_daily_belongs_to_its_deals_day_not_the_day_it_was_finished():
    # started before midnight, won after it
    late = daily("2026-09-29", at="2026-09-30T00:20:00+10:00")
    assert records.dailies([late], date(2026, 9, 29))["klondike"] == DayResult("won", best(late))
    assert records.dailies([late], TODAY)["klondike"] == NOT_PLAYED


def test_another_days_daily_is_left_out():
    lines = [daily("2026-09-29"), daily("2026-10-01", at="2026-09-30T21:00:00+10:00")]
    assert all(d == NOT_PLAYED for d in records.dailies(lines, TODAY).values())


@pytest.mark.parametrize("bad", [20260930, "20260930", "2026-9-30", "2026-09-31", None, ""])
def test_a_line_whose_day_it_cant_go_by_is_no_daily(bad):
    lines = [{**daily("2026-09-30"), "daily": bad}]
    assert records.dailies(lines, TODAY)["klondike"] == NOT_PLAYED
    assert records.daily_streak(lines, TODAY) == Streak(0, 0)


def test_a_newer_versions_game_is_left_out_of_the_dailies():
    lines = [{**daily("2026-09-30"), "game": "pyramid"}]
    assert list(records.dailies(lines, TODAY)) == GAME_ORDER


def test_the_dailies_are_todays_from_the_history_by_default(monkeypatch):
    monkeypatch.setattr(deals, "today", lambda: TODAY)
    g = deal("golf", 20260930)
    g.daily = "2026-09-30"
    history.record(g, False, 90)
    assert records.dailies()["golf"] == DayResult("lost", None)
    history.record(g, True, 80)
    assert records.dailies()["golf"] == DayResult("won", best(history.games()[-1]))
    assert records.daily_streak() == Streak(1, 1)
    monkeypatch.setattr(deals, "today", lambda: date(2026, 10, 1))
    assert records.dailies()["golf"] == NOT_PLAYED
    assert records.daily_streak() == Streak(1, 1)


# -- a streak of days -------------------------------------------------------------------


def test_the_streak_is_the_days_in_a_row_with_a_daily_won():
    lines = won_on("2026-09-28", "2026-09-29", "2026-09-30")
    assert records.daily_streak(lines, TODAY) == Streak(3, 3)


def test_today_not_won_yet_leaves_the_streak_running_to_yesterday():
    lines = won_on("2026-09-28", "2026-09-29")
    assert records.daily_streak(lines, TODAY) == Streak(2, 2)
    lines.append(daily("2026-09-30", result="lost"))
    assert records.daily_streak(lines, TODAY) == Streak(2, 2)


def test_a_missed_day_ends_the_streak():
    lines = won_on("2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28", "2026-09-29")
    assert records.daily_streak(lines, TODAY) == Streak(2, 3)
    # yesterday missed as well as today not won yet
    assert records.daily_streak(lines[:3], TODAY) == Streak(0, 3)
    assert records.daily_streak(lines, date(2026, 10, 1)) == Streak(0, 3)


def test_a_day_with_only_losses_ends_the_streak():
    lines = [
        *won_on("2026-09-27", "2026-09-28"),
        daily("2026-09-29", result="lost"),
        daily("2026-09-29", "golf", "lost"),
        daily("2026-09-30"),
    ]
    assert records.daily_streak(lines, TODAY) == Streak(1, 2)


def test_two_dailies_won_on_a_day_count_it_once():
    lines = [
        daily("2026-09-29"),
        daily("2026-09-29", "golf"),
        daily("2026-09-29"),
        daily("2026-09-30"),
    ]
    assert records.daily_streak(lines, TODAY) == Streak(2, 2)


def test_a_daily_won_in_any_game_counts_the_day():
    lines = [
        daily("2026-09-27", "spider"),
        daily("2026-09-28", "golf"),
        daily("2026-09-29", "klondike", "lost"),
        daily("2026-09-29", "freecell"),
        # a daily won in a game a newer version has is still a day won
        {**daily("2026-09-30"), "game": "pyramid"},
    ]
    assert records.daily_streak(lines, TODAY) == Streak(4, 4)


def test_days_recorded_out_of_order_still_run_in_a_row():
    # a daily resumed from a save is recorded when it's finished
    lines = [
        daily("2026-09-29", at="2026-09-29T08:00:00+10:00"),
        daily("2026-09-27", at="2026-09-29T09:00:00+10:00"),
        daily("2026-09-24", at="2026-09-29T09:30:00+10:00"),
        daily("2026-09-28", at="2026-09-29T10:00:00+10:00"),
        daily("2026-09-25", at="2026-09-29T11:00:00+10:00"),
    ]
    assert records.daily_streak(lines, TODAY) == Streak(3, 3)
    assert records.daily_streak(lines, date(2026, 9, 26)) == Streak(2, 3)


def test_a_streak_counts_the_days_of_the_deals_across_midnight():
    lines = [
        daily("2026-09-28", at="2026-09-28T23:10:00+10:00"),
        # the 29th's, finished after midnight, and the 30th's, started and
        # won on the 30th before it
        daily("2026-09-30", at="2026-09-30T00:05:00+10:00"),
        daily("2026-09-29", at="2026-09-30T00:20:00+10:00"),
    ]
    assert records.daily_streak(lines, TODAY) == Streak(3, 3)
    assert records.daily_streak(lines[:2], TODAY) == Streak(1, 1)


@pytest.mark.parametrize(
    "ats",
    [
        # London, as the clocks go back at 2 in the morning of 2026-10-25,
        # which has 25 hours, and forward at 1 on 2027-03-28, with 23
        [
            ("2026-10-24", "2026-10-24T23:59:00+01:00"),
            ("2026-10-25", "2026-10-25T00:30:00+01:00"),  # the 24th, going by UTC
            ("2026-10-26", "2026-10-26T23:30:00+00:00"),
        ],
        [
            ("2026-10-24", "2026-10-24T00:10:00+01:00"),
            ("2026-10-25", "2026-10-25T23:50:00+00:00"),  # 48 hours and 40 minutes on
            ("2026-10-26", "2026-10-26T00:10:00+00:00"),
        ],
        [
            ("2027-03-27", "2027-03-27T23:50:00+00:00"),
            ("2027-03-28", "2027-03-28T23:50:00+01:00"),
            ("2027-03-29", "2027-03-29T00:10:00+01:00"),  # the 28th, going by UTC
        ],
        [
            ("2027-03-27", "2027-03-27T00:10:00+00:00"),
            ("2027-03-28", "2027-03-28T23:50:00+01:00"),  # 46 hours and 40 minutes on
            ("2027-03-29", "2027-03-29T23:50:00+01:00"),
        ],
        # Sydney, forward at 2 on 2026-10-04 and back at 3 on 2027-04-04
        [
            ("2026-10-03", "2026-10-03T00:30:00+10:00"),  # the 2nd, going by UTC
            ("2026-10-04", "2026-10-04T23:30:00+11:00"),
            ("2026-10-05", "2026-10-05T00:30:00+11:00"),  # the 4th, going by UTC
        ],
        [
            ("2027-04-03", "2027-04-03T23:30:00+11:00"),
            ("2027-04-04", "2027-04-04T00:30:00+11:00"),
            ("2027-04-05", "2027-04-05T23:30:00+10:00"),
        ],
    ],
    ids=[
        "london-back",
        "london-back-far",
        "london-forward",
        "london-forward-far",
        "sydney-forward",
        "sydney-back",
    ],
)
def test_a_streak_runs_through_a_change_of_the_clocks(ats):
    lines = [daily(day, at=at) for day, at in ats]
    today = date.fromisoformat(ats[-1][0])
    assert records.daily_streak(lines, today) == Streak(3, 3)
    assert records.daily_streak(lines, today + timedelta(days=1)) == Streak(3, 3)
    for day, _ in ats:
        assert records.dailies(lines, date.fromisoformat(day))["klondike"].result == "won"


@pytest.mark.parametrize(
    "ats",
    [
        # a day between, missed, though the two are under 26 hours apart
        [("2026-10-24", "2026-10-24T23:59:00+01:00"), ("2026-10-26", "2026-10-26T00:01:00+00:00")],
        [("2027-03-27", "2027-03-27T23:59:00+00:00"), ("2027-03-29", "2027-03-29T00:01:00+01:00")],
        [("2026-10-03", "2026-10-03T23:59:00+10:00"), ("2026-10-05", "2026-10-05T00:01:00+11:00")],
        [("2027-04-03", "2027-04-03T23:59:00+11:00"), ("2027-04-05", "2027-04-05T00:01:00+10:00")],
    ],
    ids=["london-back", "london-forward", "sydney-forward", "sydney-back"],
)
def test_a_day_missed_over_a_change_of_the_clocks_ends_the_streak(ats):
    lines = [daily(day, at=at) for day, at in ats]
    today = date.fromisoformat(ats[-1][0])
    assert records.daily_streak(lines, today) == Streak(1, 1)


def test_a_streak_reaches_the_first_and_last_days_there_are():
    lines = won_on("0001-01-01", "0001-01-02", "9999-12-30", "9999-12-31")
    assert records.daily_streak(lines, TODAY) == Streak(0, 2)


def test_the_dailies_and_the_streak_of_20000_games_take_well_under_100_ms():
    first = date(2000, 1, 1)
    lines = [
        daily((first + timedelta(days=n // 3)).isoformat(), GAME_ORDER[n % len(GAME_ORDER)])
        for n in range(20000)
    ]
    last = first + timedelta(days=6666)
    start = time.perf_counter()
    found = records.dailies(lines, last)
    streak = records.daily_streak(lines, last)
    took = time.perf_counter() - start
    assert {key for key, d in found.items() if d.result == "won"} == {"triplepeaks", "yukon"}
    assert streak == Streak(6667, 6667)
    assert took < 1.0  # generous, for a slow machine
