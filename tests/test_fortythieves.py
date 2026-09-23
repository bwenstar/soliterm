"""Forty Thieves: how many cards move at once, the foundations and the score."""

import pytest

from soliterm.engine import Card
from helpers import clear_board, deal


def up(rank, suit):
    return Card(rank, suit, True)


def labels(g, sid):
    return [str(c) for c in g.cards(sid)]


@pytest.fixture
def table():
    g = deal("fortythieves", 1)
    clear_board(g)
    return g, g.ids_of("foundation"), g.ids_of("tableau")


def run_to_move(g, t, size, free):
    """A run of `size` spades from the 10 down on t[0], the JS on t[1] and
    `free` empty columns from t[2] on. Every other column holds a card."""
    for x in t:
        g.slots[x].cards = [up(12, "D")]
    g.slots[t[0]].cards += [up(10 - i, "S") for i in range(size)]
    g.slots[t[1]].cards += [up(11, "S")]
    for x in t[2:2 + free]:
        g.slots[x].cards = []


@pytest.mark.parametrize("free, most", [(0, 1), (1, 2), (2, 4), (3, 8)])
def test_every_free_column_doubles_the_group_that_can_move(table, free, most):
    g, f, t = table
    run_to_move(g, t, most + 1, free)
    assert g.attempt_move(t[0], t[1], most + 1) is False
    assert (t[0], t[1], most + 1) not in g.legal_moves()
    run_to_move(g, t, most, free)
    assert (t[0], t[1], most) in g.legal_moves()
    assert g.attempt_move(t[0], t[1], most)
    assert labels(g, t[1]) == ["QD", "JS"] + [f"{10 - i}S" for i in range(most)]


def test_without_a_free_column_cards_move_one_at_a_time(table):
    g, f, t = table
    run_to_move(g, t, 3, 0)
    g.slots[t[2]].cards += [up(9, "S")]
    assert all(n == 1 for _, _, n in g.legal_moves())
    assert g.attempt_move(t[0], t[2], 1)          # the 8S alone can go on the 9S
    assert labels(g, t[2]) == ["QD", "9S", "8S"]


def test_the_empty_column_a_group_goes_to_is_not_free(table):
    g, f, t = table
    run_to_move(g, t, 2, 1)
    assert g.attempt_move(t[0], t[2], 2) is False
    run_to_move(g, t, 2, 2)
    assert g.attempt_move(t[0], t[2], 2)
    assert labels(g, t[2]) == ["10S", "9S"]


def test_the_column_a_group_leaves_is_not_free(table):
    g, f, t = table
    run_to_move(g, t, 2, 0)
    g.slots[t[0]].cards = [up(10, "S"), up(9, "S")]     # the whole column
    assert g.attempt_move(t[0], t[1], 2) is False


# -- the score ----------------------------------------------------------------------

def test_a_card_up_scores_five_and_a_finished_suit_sixty_more(table):
    g, f, t = table
    g.slots[t[0]].cards = [up(r, "S") for r in range(13, 0, -1)]
    for i in range(12):
        assert g.attempt_move(t[0], f[0], 1)
        assert g.score == 5 * (i + 1)
    assert g.attempt_move(t[0], f[0], 1)
    assert g.score == 5 * 13 + 60
    assert g.undo() and g.score == 60


def test_double_click_and_autoplay_score_the_same_way(table):
    g, f, t = table
    g.slots[t[0]].cards = [up(2, "H"), up(1, "H")]
    assert g.double_click(t[0])
    assert g.score == 5
    g.slots[f[1]].cards = [up(1, "H")]
    assert g.autoplay() == 1
    assert g.score == 15


def test_a_won_game_scores_a_thousand(table):
    g, f, t = table
    for i, fid in enumerate(f):
        g.slots[fid].cards = [up(r, "SHDC"[i % 4]) for r in range(1, 14)]
    g.slots[f[0]].cards.pop()
    g.slots[t[0]].cards = [up(13, "S")]
    assert g.attempt_move(t[0], f[0], 1)
    assert g.is_won()
    assert g.score == 1000
