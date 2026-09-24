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
