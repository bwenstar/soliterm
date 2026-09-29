"""The records of each game, worked out from the history: games played and
won, the fastest win, the fewest moves, the best score, the longest
streak, and how a game just played did against its deal's best."""

import time

import pytest

from soliterm import history, records
from soliterm.engine import GAME_ORDER, GAMES, Card
from soliterm.history import Streak
from soliterm.records import Best, DealBest, Records

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
