"""The history: one line per game counted here, and the win streaks it
gives."""

import json
import os
import stat

import pytest

from soliterm import history, store
from soliterm.history import Streak

from helpers import deal

AT = "2026-09-24T14:05:11+10:00"


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr(history, "now", lambda: AT)


def lines():
    with open(history.history_path(), encoding="utf-8") as fh:
        return fh.read().splitlines()


def write(text):
    path = history.history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def played(key="klondike", seed=4, deals=3):
    g = deal(key, seed)
    for _ in range(deals):
        g.deal()
    return g


def test_record_appends_one_line():
    stat = history.record(played(), True, 141.6)
    assert stat == store.get_stat("klondike")
    assert (stat["wins"], stat["total"], stat["best"]) == (1, 1, 142)
    assert [json.loads(line) for line in lines()] == [
        {
            "at": AT,
            "game": "klondike",
            "options": {"draw": 1, "redeals": "standard"},
            "deal": 4,
            "result": "won",
            "seconds": 142,
            "moves": 3,
            "score": 0,
            "hints": 0,
            "undos": 0,
        }
    ]
    history.record(played("golf", deals=1), False, 7.4)
    assert len(lines()) == 2
    assert history.games()[1]["result"] == "lost"


def test_a_daily_says_so_in_its_line():
    g = played()
    g.daily = "2026-09-24"
    history.record(g, False, 543)
    history.record(played(), False, 60)
    daily, other = history.games()
    assert daily["daily"] == "2026-09-24"
    assert "daily" not in other
    assert history.line(daily) == "2026-09-24 14:05  Klondike        lost    9:03    3 moves  daily"
    assert history.line(other).endswith("3 moves")


@pytest.mark.parametrize("won,secs,kept", [(True, 0.2, 1), (False, 0.2, 0), (False, 9.6, 10)])
def test_a_loss_keeps_its_time_and_a_win_is_at_least_a_second(won, secs, kept):
    history.record(played(), won, secs)
    assert history.games()[0]["seconds"] == kept


def test_bad_lines_are_skipped():
    good = {"at": AT, "game": "golf", "result": "won", "seconds": 5, "moves": 2}
    bad = [
        [1, 2],
        {**good, "game": 5},
        {**good, "result": "drew"},
        {**good, "seconds": -1},
        {**good, "moves": True},
        {**good, "at": None},
    ]
    text = "\n".join([json.dumps(good), *map(json.dumps, bad), "", "not json", '{"at": "2026-'])
    write(text)  # the last line cut short, with no newline after it
    history.record(played(), False, 3)
    assert [e["game"] for e in history.games()] == ["golf", "klondike"]
    assert json.loads(lines()[-1])["game"] == "klondike"
    assert store.notices() == []


@pytest.mark.parametrize(
    "bad",
    [
        {"game": "\x1b]0;pwned\x07\x1b[2J"},
        {"at": "\x1b[2J" + AT},
        {"at": "\ud800"},
        {"game": "golf\ud800"},
        {"game": ""},
    ],
    ids=[
        "escapes in the game",
        "escapes in the time",
        "a surrogate",
        "a surrogate game",
        "no game",
    ],
)
def test_a_line_whose_time_or_game_is_not_one_is_skipped(bad):
    # a hand-edited or damaged history mustn't have --stats print escapes
    good = {"at": AT, "game": "golf", "result": "won", "seconds": 5, "moves": 2}
    write("".join(json.dumps(e) + "\n" for e in [good, {**good, **bad}]))
    assert history.games() == [good]


@pytest.mark.parametrize(
    "newer", [{"game": "pyramid"}, {"game": "forty_thieves-2"}, {"at": "2031-01-02T03:04:05.5Z"}]
)
def test_a_line_a_newer_version_could_write_is_kept(newer):
    e = {"at": AT, "game": "golf", "result": "lost", "seconds": 5, "moves": 2, **newer}
    write(json.dumps(e) + "\n")
    assert history.games() == [e]


def test_a_line_has_the_hints_asked_for_and_the_moves_undone():
    g = played()
    g.hint()
    assert g.undo()
    history.record(g, False, 60)
    (e,) = history.games()
    assert (e["hints"], e["undos"]) == (1, 1)
    assert history.counts(e) == (1, 1)


def test_counts_not_known_are_left_out_of_the_line():
    g = played()
    g.hints = None  # as for a game resumed from a save older than the counts
    history.record(g, False, 60)
    e = json.loads(lines()[0])
    assert "hints" not in e and e["undos"] == 0
    assert history.counts(e) == (None, 0)


@pytest.mark.parametrize(
    "counts",
    [{}, {"hints": None, "undos": -1}, {"hints": "2", "undos": 1.0}, {"hints": True}],
    ids=["from before them", "null and below 0", "text and a float", "true"],
)
def test_a_line_without_counts_to_go_by_is_a_game_with_them_unknown(counts):
    e = {"at": AT, "game": "golf", "result": "won", "seconds": 5, "moves": 2, **counts}
    write(json.dumps(e) + "\n")
    assert history.games() == [e]
    assert history.counts(e) == (None, None)


def test_a_line_with_the_counts_is_one_1_0_reads():
    # 1.0 takes a line for a game by its time, game, result, seconds and
    # moves, and reads nothing else but the options, deal, score and daily
    g = played()
    g.hint()
    history.record(g, True, 60)
    e = json.loads(lines()[0])
    assert set(e) - {"at", "game", "options", "deal", "result", "seconds", "moves", "score"} == {
        "hints",
        "undos",
    }


def test_streaks_count_wins_in_a_row_per_game():
    assert history.streaks() == {}
    for won in [True, True, False, True]:
        history.record(played(), won, 60)
    for won in [True, True]:
        history.record(played("golf", deals=1), won, 60)
    assert history.streaks() == {"klondike": Streak(1, 2), "golf": Streak(2, 2)}


def test_recent_games_come_newest_first():
    assert not history.any_games()
    for key in ["klondike", "golf", "spider"]:
        history.record(played(key, deals=1), False, 60)
    assert history.any_games()
    assert [e["game"] for e in history.recent(2)] == ["spider", "golf"]
    assert len(history.recent(10)) == 3


def test_a_line_shows_a_game_the_way_stats_lists_it():
    e = {"at": AT, "game": "golf", "result": "won", "seconds": 48, "moves": 1}
    assert history.line(e) == "2026-09-24 14:05  Golf            won     0:48    1 move"
    # a game only a newer version knows goes by its key
    e = {**e, "game": "chess", "result": "lost", "moves": 212}
    assert history.line(e) == "2026-09-24 14:05  chess           lost    0:48  212 moves"


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX file modes, not root"
)
def test_an_unwritable_history_still_counts_the_game_and_says_so():
    write("")
    path = history.history_path()
    os.chmod(path, 0o400)
    history.record(played(), False, 3)
    assert store.get_stat("klondike")["total"] == 1
    assert lines() == []
    assert store.notices() == [
        f"can't write {path} (Permission denied), so that game is missing from the history"
    ]


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.mark.skipif(os.name != "posix", reason="needs POSIX file modes")
def test_a_new_history_and_its_copy_are_for_the_player_only():
    umask = os.umask(0o022)
    try:
        history.record(played(), False, 3)
        kept = history.backup()
    finally:
        os.umask(umask)
    assert mode(history.history_path()) == 0o600
    assert mode(kept) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="needs POSIX file modes")
def test_a_history_there_already_keeps_its_mode():
    write("")
    os.chmod(history.history_path(), 0o644)
    history.record(played(), False, 3)
    assert mode(history.history_path()) == 0o644
