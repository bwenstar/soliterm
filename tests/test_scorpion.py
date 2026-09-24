"""Scorpion: build down in suit, move any face-up group, and no foundations."""

import random

import pytest

from soliterm.engine import Card

from helpers import card_multiset, clear_board, deal, legal_walk, random_op

STOCK, COLUMNS = 0, list(range(1, 8))
DEAD_END = "the only moves left slide a whole column into an empty one - undo to try another line"


def up(rank, suit):
    return Card(rank, suit, True)


def down(rank, suit):
    return Card(rank, suit, False)


def suit(s):
    """A whole suit from King down to Ace, face up."""
    return [up(r, s) for r in range(13, 0, -1)]


@pytest.fixture
def table():
    g = deal("scorpion", 1)
    clear_board(g)
    return g


@pytest.mark.parametrize("seed", range(3))
def test_the_deal_hides_three_cards_under_the_first_four_columns(seed):
    g = deal("scorpion", seed)
    assert [g.kind(sid) for sid in range(8)] == ["stock"] + ["tableau"] * 7
    assert g.ids_of("tableau") == COLUMNS
    for i, t in enumerate(COLUMNS):
        faces = [c.face_up for c in g.cards(t)]
        assert faces == ([False] * 3 + [True] * 4 if i < 4 else [True] * 7)
    assert len(g.cards(STOCK)) == 3
    assert not any(c.face_up for c in g.cards(STOCK))
    assert not g.ids_of("foundation")
    assert g.status == "Stock: 3  Done: 0/4"


def test_any_face_up_group_goes_on_the_next_card_up_in_suit(table):
    g = table
    g.slots[COLUMNS[0]].cards = [up(13, "C"), up(7, "H"), up(2, "S"), up(9, "D")]
    g.slots[COLUMNS[1]].cards = [up(8, "S")]
    g.slots[COLUMNS[2]].cards = [up(8, "H")]
    assert g.attempt_move(COLUMNS[0], COLUMNS[1], 3) is False
    assert g.attempt_move(COLUMNS[0], COLUMNS[2], 3)
    assert g.cards(COLUMNS[2]) == [up(8, "H"), up(7, "H"), up(2, "S"), up(9, "D")]
    assert g.cards(COLUMNS[0]) == [up(13, "C")]


def test_a_face_down_card_never_moves(table):
    g = table
    g.slots[COLUMNS[0]].cards = [down(7, "H"), up(2, "S")]
    g.slots[COLUMNS[1]].cards = [up(8, "H")]
    assert not g.can_pickup(COLUMNS[0], 2)
    assert g.attempt_move(COLUMNS[0], COLUMNS[1], 2) is False


def test_only_a_king_or_a_group_under_a_king_fills_an_empty_column(table):
    g = table
    g.slots[COLUMNS[0]].cards = [up(5, "C"), up(12, "H")]
    g.slots[COLUMNS[1]].cards = [up(2, "D"), up(13, "S"), up(4, "H")]
    assert g.attempt_move(COLUMNS[0], COLUMNS[2], 1) is False
    assert g.attempt_move(COLUMNS[1], COLUMNS[2], 1) is False
    assert g.attempt_move(COLUMNS[1], COLUMNS[2], 2)
    assert g.cards(COLUMNS[2]) == [up(13, "S"), up(4, "H")]


def test_the_stock_deals_onto_the_first_three_columns_at_any_time(table):
    g = table
    g.slots[STOCK].cards = [down(2, "C"), down(3, "C"), down(4, "C")]
    g.slots[COLUMNS[1]].cards = [up(9, "D")]
    g.slots[COLUMNS[3]].cards = [up(6, "S")]
    assert g.can_deal()  # the first column is empty, and that doesn't matter
    assert g.deal()
    assert [g.cards(t) for t in COLUMNS[:4]] == [
        [up(4, "C")],
        [up(9, "D"), up(3, "C")],
        [up(2, "C")],
        [up(6, "S")],
    ]
    assert not g.cards(STOCK)
    assert not g.can_deal()
    assert g.deal_blocked_reason() == "the stock is empty - nothing left to deal"


def test_turning_a_card_up_scores_three(table):
    g = table
    g.slots[COLUMNS[0]].cards = [down(2, "S"), up(13, "H")]
    before = g.gamedef._score(g)
    assert g.attempt_move(COLUMNS[0], COLUMNS[1])
    assert g.cards(COLUMNS[0]) == [up(2, "S")]
    assert g.score == before + 3


@pytest.mark.parametrize("seed", range(4))
def test_the_score_is_what_the_board_is_worth(seed):
    g = deal("scorpion", seed)
    assert g.score == g.gamedef._score(g)
    cards = card_multiset(g)
    rng = random.Random(seed)
    for _ in range(200):
        random_op(g, rng)
        assert g.score == g.gamedef._score(g)
    for _ in legal_walk(g, rng, 200):
        assert g.score == g.gamedef._score(g)
        assert card_multiset(g) == cards


def test_four_whole_suits_in_their_own_columns_win_and_score_100(table):
    g = table
    for t, s in zip(COLUMNS, "SHD"):
        g.slots[t].cards = suit(s)
    g.slots[COLUMNS[3]].cards = suit("C")[:-1]
    g.slots[COLUMNS[6]].cards = [up(1, "C")]
    assert not g.is_won()
    assert g.attempt_move(COLUMNS[6], COLUMNS[3])
    assert g.is_won() and not g.is_stuck()
    assert g.score == 100
    assert g.status == "Stock: 0  Done: 4/4"


def test_a_whole_suit_on_top_of_other_cards_is_not_done(table):
    g = table
    g.slots[COLUMNS[0]].cards = [up(5, "D")] + suit("S")
    g.slots[COLUMNS[1]].cards = suit("H")
    g.update_status()
    assert g.status == "Stock: 0  Done: 1/4"
    # a pair for each card in suit on the one above, and 4 for the hearts
    assert g.gamedef._score(g) == 12 + 12 + 4 + 3 * 12
    assert not g.is_won()


def kings_and_nothing_else(g):
    """Two Kings at the bottom of their columns, each under a card that has
    nowhere to go, and five empty columns."""
    g.slots[COLUMNS[0]].cards = [up(13, "H"), up(2, "C")]
    g.slots[COLUMNS[1]].cards = [up(13, "S"), up(3, "D")]


def test_sliding_a_king_column_between_empty_columns_is_a_dead_end(table):
    g = table
    kings_and_nothing_else(g)
    moves = g.legal_moves()
    assert moves and all(n == len(g.cards(src)) and not g.cards(dst) for src, dst, n in moves)
    assert g.is_stuck()
    assert g.hint() is None
    assert g.no_hint_reason() == DEAD_END


def test_a_dead_end_needs_the_stock_dealt(table):
    g = table
    kings_and_nothing_else(g)
    g.slots[STOCK].cards = [down(4, "D"), down(5, "D"), down(6, "D")]
    assert not g.is_stuck()
    assert g.hint() == (STOCK, STOCK, "Deal from the stock")
