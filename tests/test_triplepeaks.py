"""Triple Peaks: clear three overlapping peaks onto the waste, a rank up or down."""

import pytest

from soliterm.engine import Card
from soliterm.engine.games.triplepeaks import COVERS

from helpers import clear_board, deal

STOCK, WASTE, PEAKS = 0, 1, list(range(2, 30))


def up(rank, suit):
    return Card(rank, suit, True)


def down(rank, suit):
    return Card(rank, suit, False)


def board(waste, cards, stock=(), score=0, **options):
    """A game with just `waste` on the waste, the peak cards given as
    {index: card} and the cards in `stock`, everything else played."""
    g = deal("triplepeaks", 1, **options)
    clear_board(g)
    g.slots[WASTE].cards = [waste]
    for i, card in cards.items():
        g.slots[PEAKS[i]].cards = [card]
    g.slots[STOCK].cards = [down(r, s) for r, s in stock]
    g.score = score
    g.update_status()
    return g


def play(g, *indexes):
    for i in indexes:
        assert g.attempt_move(PEAKS[i], WASTE), f"peak card {i} didn't play"


def test_the_peaks_are_covered_by_the_two_cards_below():
    assert [len(c) for c in COVERS] == [2] * 18 + [0] * 10
    assert COVERS[0] == [3, 4]
    # where two peaks meet, one bottom card covers a card in each
    assert COVERS[11] == [20, 21]
    assert COVERS[12] == [21, 22]


@pytest.mark.parametrize("seed", range(3))
def test_the_deal_turns_the_first_waste_card_up_for_free(seed):
    g = deal("triplepeaks", seed)
    assert [g.kind(sid) for sid in range(30)] == ["stock", "waste"] + ["tableau"] * 28
    assert all(len(g.cards(p)) == 1 for p in PEAKS)
    assert [g.top(p).face_up for p in PEAKS] == [False] * 18 + [True] * 10
    assert [c.face_up for c in g.cards(WASTE)] == [True]
    assert len(g.cards(STOCK)) == 23
    assert not any(c.face_up for c in g.cards(STOCK))
    assert g.score == 0
    assert g.status == "Stock: 23 left  Run: 0"


@pytest.mark.parametrize(
    "waste, card, ok",
    [
        (9, 10, True),
        (9, 8, True),
        (9, 9, False),
        (9, 11, False),
        (13, 1, True),  # an Ace on a King
        (13, 12, True),
        (1, 13, True),  # a King on an Ace
        (1, 2, True),
        (1, 3, False),
        (13, 2, False),
    ],
)
def test_a_card_goes_one_rank_up_or_down_and_kings_meet_aces(waste, card, ok):
    g = board(up(waste, "C"), {27: up(card, "H"), 26: up(5, "S")})
    assert g.attempt_move(PEAKS[27], WASTE) is ok
    assert g.click(PEAKS[27]) is False  # played already, or never could be
    g = board(up(waste, "C"), {27: up(card, "H"), 26: up(5, "S")})
    assert g.double_click(PEAKS[27]) is ok


def test_a_covered_card_stays_down_and_cannot_be_played():
    g = board(up(5, "C"), {9: down(4, "D"), 18: up(6, "H"), 19: up(9, "S")})
    play(g, 18)
    assert g.cards(PEAKS[9]) == [down(4, "D")]  # 19 still covers it
    assert not g.can_pickup(PEAKS[9], 1)
    assert g.attempt_move(PEAKS[9], WASTE) is False
    assert g.click(PEAKS[9]) is False


def test_clearing_both_covering_cards_turns_a_card_up():
    # 21 covers a card in the left peak and one in the middle one
    cards = {11: down(3, "S"), 12: down(4, "S"), 20: up(6, "H"), 21: up(7, "S"), 22: up(8, "D")}
    g = board(up(5, "C"), cards)
    play(g, 20)
    assert not g.top(PEAKS[11]).face_up
    play(g, 21)
    assert g.top(PEAKS[11]).face_up and not g.top(PEAKS[12]).face_up
    play(g, 22)
    assert g.top(PEAKS[12]).face_up


def test_a_run_scores_one_two_three():
    g = board(up(5, "C"), {18: up(6, "H"), 19: up(7, "S"), 20: up(8, "D"), 27: up(13, "S")})
    scores = []
    for i in (18, 19, 20):
        play(g, i)
        scores.append(g.score)
    assert scores == [1, 3, 6]
    assert g.status == "Stock: 0 left  Run: 3"


def test_turning_the_stock_costs_five_and_starts_a_new_run():
    g = board(up(5, "C"), {18: up(6, "H"), 27: up(13, "S")}, stock=[(2, "D"), (9, "S")], score=20)
    play(g, 18)
    assert g.score == 21
    assert g.deal()
    assert g.cards(WASTE) == [down(5, "C"), down(6, "H"), up(9, "S")]
    assert g.score == 16
    assert g.status == "Stock: 1 left  Run: 0"


def test_the_score_never_goes_below_zero():
    g = board(up(5, "C"), {27: up(13, "S")}, stock=[(2, "D"), (9, "S")], score=3)
    assert g.deal() and g.score == 0
    assert g.deal() and g.score == 0
    assert g.undo() and g.score == 0
    assert g.undo() and g.score == 3


def test_a_perfect_game_scores_466():
    # each card a rank above the last, Kings wrapping to Aces, played from
    # the bottom row up so every card turns up just in time
    order = list(range(18, 28)) + list(range(9, 18)) + list(range(3, 9)) + list(range(3))
    cards = {}
    for k, i in enumerate(order):
        rank, suit = (k + 1) % 13 + 1, "SHDC"[k % 4]
        cards[i] = Card(rank, suit, i >= 18)
    g = board(up(1, "C"), cards)
    play(g, *order)
    assert g.is_won()
    # 1 + 2 + ... + 28, 15 for each peak's top and 15 for the lot
    assert g.score == 406 + 3 * 15 + 15 == 466


def test_multiplier_scoring_doubles_and_turning_is_free():
    cards = {i: up(r, "H") for i, r in zip(range(18, 23), range(6, 11))}
    cards.update({0: up(3, "S"), 27: up(13, "S")})
    g = board(up(5, "C"), cards, stock=[(2, "D")], scoring="multiplier")
    play(g, 18, 19, 20, 21, 22)
    assert g.score == 1 + 2 + 4 + 8 + 16 == 31
    assert g.deal() and g.score == 31
    play(g, 0)  # a peak's top card
    assert g.score == 31 + 1 + 25


def test_undo_after_a_turn_brings_the_run_back():
    cards = {18: up(6, "H"), 19: up(7, "S"), 20: up(8, "D"), 27: up(13, "S")}
    g = board(up(5, "C"), cards, stock=[(2, "D")], score=10)
    play(g, 18, 19)
    assert g.deal() and g.status == "Stock: 0 left  Run: 0"
    assert g.undo()
    assert g.status == "Stock: 1 left  Run: 2"
    assert g.score == 13
    assert [c.face_up for c in g.cards(WASTE)] == [True, True, True]
    play(g, 20)
    assert g.score == 16  # the third card of the run


def test_the_game_is_won_with_cards_left_in_the_stock():
    g = board(up(5, "C"), {18: up(6, "H")}, stock=[(2, "D"), (9, "S"), (11, "C")])
    play(g, 18)
    assert g.is_won() and not g.is_stuck()
    assert len(g.cards(STOCK)) == 3
    assert g.score == 1 + 15  # the card, and clearing the lot


def test_no_play_and_an_empty_stock_is_stuck():
    g = board(up(5, "C"), {18: up(6, "H"), 27: up(13, "S")})
    play(g, 18)
    assert not g.is_won() and g.is_stuck()
    assert g.hint() is None
    assert g.no_hint_reason() == "no moves left - undo to try another line"
