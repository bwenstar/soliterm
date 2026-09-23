"""Klondike: the deal, drawing one or three, scoring and the face-up rule."""

import random

import pytest

from soliterm.engine import Card
from helpers import card_multiset, clear_board, deal, legal_walk

DRAWS = [1, 3]


def foundation_cards(g):
    return sum(len(g.cards(f)) for f in g.ids_of("foundation"))


def not_between_foundations(g, move):
    src, dst, n = move
    return not (g.kind(src) == "foundation" and g.kind(dst) == "foundation")


def check_faces(g):
    """Stock face down, waste and foundations face up, and every tableau
    column is face-down cards under a face-up top."""
    for sid in g.ids_of("stock"):
        assert not any(c.face_up for c in g.cards(sid))
    for sid in g.ids_of("waste") + g.ids_of("foundation"):
        assert all(c.face_up for c in g.cards(sid))
    for sid in g.ids_of("tableau"):
        faces = [c.face_up for c in g.cards(sid)]
        if faces:
            assert faces[-1], f"column {sid} has a face-down top"
            assert faces == sorted(faces), f"column {sid} has a card face down above one face up"


@pytest.mark.parametrize("draw", DRAWS)
@pytest.mark.parametrize("seed", range(5))
def test_the_deal(seed, draw):
    g = deal("klondike", seed, draw=draw)
    assert [len(g.cards(t)) for t in g.ids_of("tableau")] == [1, 2, 3, 4, 5, 6, 7]
    assert len(g.cards(g.ids_of("stock")[0])) == 24
    assert not g.cards(g.ids_of("waste")[0])
    assert foundation_cards(g) == 0
    assert len(card_multiset(g)) == 52
    check_faces(g)


@pytest.mark.parametrize("draw", DRAWS)
def test_dealing_turns_over_draw_cards(draw):
    g = deal("klondike", 1, draw=draw)
    stock, waste = g.ids_of("stock")[0], g.ids_of("waste")[0]
    top = g.cards(stock)[-draw:]
    assert g.deal()
    assert len(g.cards(stock)) == 24 - draw
    assert [c.up(False) for c in g.cards(waste)] == list(reversed(top))
    assert all(c.face_up for c in g.cards(waste))


@pytest.mark.parametrize("draw", DRAWS)
def test_an_empty_stock_turns_the_waste_back_over(draw):
    g = deal("klondike", 1, draw=draw)
    stock, waste = g.ids_of("stock")[0], g.ids_of("waste")[0]
    order = list(g.cards(stock))
    while g.cards(stock):
        g.deal()
    assert len(g.cards(waste)) == 24
    assert g.deal()
    assert not g.cards(waste)
    assert g.cards(stock) == order
    assert g.redeals_done == 1


def turn_over(g):
    """Deal the stock out, then click it once more to turn the waste back
    over. Returns what that last click did."""
    stock = g.ids_of("stock")[0]
    while g.cards(stock):
        assert g.deal()
    return g.deal()


def test_drawing_one_turns_the_stock_over_twice_at_most():
    # AisleRiot's single card deals: three times through the deck
    g = deal("klondike", 1, draw=1)
    assert "Redeals left: 2" in g.status
    assert turn_over(g) and turn_over(g)
    assert "Redeals left: 0" in g.status
    assert turn_over(g) is False
    assert g.redeals_done == 2
    assert g.cards(g.ids_of("waste")[0])
    assert not g.can_deal()
    assert not g.deal_is_productive()
    assert "redeal" in g.deal_blocked_reason()


def test_drawing_three_redeals_as_often_as_you_like():
    g = deal("klondike", 1, draw=3)
    for _ in range(5):
        assert turn_over(g)
    assert g.redeals_done == 5
    assert "Redeals" not in g.status


@pytest.mark.parametrize("draw", DRAWS)
def test_no_redeals_means_one_pass_through_the_stock(draw):
    g = deal("klondike", 1, draw=draw, redeals="none")
    assert "Redeals left: 0" in g.status
    assert turn_over(g) is False
    assert g.redeals_done == 0
    assert not g.can_deal()


def test_unlimited_redeals_drawing_one():
    g = deal("klondike", 1, draw=1, redeals="unlimited")
    for _ in range(4):
        assert turn_over(g)
    assert g.can_deal()
    assert "Redeals" not in g.status


def test_the_waste_left_over_can_be_turned_over_while_redeals_remain():
    g = deal("klondike", 1)
    stock = g.ids_of("stock")[0]
    while g.cards(stock):
        g.deal()
    assert g.can_deal()


def exhausted(redeals_done):
    """Nothing moves, the stock is used up and two dead cards sit in the
    waste."""
    g = deal("klondike", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[g.ids_of("waste")[0]].cards = [Card(5, "C", True), Card(9, "D", True)]
    g.slots[t[0]].cards = [Card(3, "H", False), Card(7, "S", True)]
    g.slots[t[1]].cards = [Card(6, "C", True)]
    g.redeals_done = redeals_done
    g.moves = 10
    return g


def test_a_used_up_stock_with_nothing_to_move_is_stuck():
    g = exhausted(2)
    assert g.legal_moves() == []
    assert g.is_stuck()
    assert g.hint() is None


def test_a_stock_that_can_still_be_turned_over_is_not_stuck():
    g = exhausted(1)
    assert not g.is_stuck()
    assert g.hint()[2] == "Deal from the stock"


@pytest.mark.parametrize("draw", DRAWS)
@pytest.mark.parametrize("seed", range(10))
def test_random_play_keeps_the_cards_faces_and_score_straight(seed, draw):
    g = deal("klondike", seed, draw=draw)
    cards = card_multiset(g)
    rng = random.Random(seed * 7919 + 13)
    for _ in legal_walk(g, rng, 200, allow=not_between_foundations):
        assert card_multiset(g) == cards
        check_faces(g)
        # one point per card on the foundations
        assert g.score == foundation_cards(g)


@pytest.mark.parametrize("draw", DRAWS)
@pytest.mark.parametrize("seed", range(20))
def test_autoplay_and_dealing_keep_every_card(seed, draw):
    # the naive strategy: send everything up, deal, repeat
    g = deal("klondike", seed, draw=draw)
    cards = card_multiset(g)
    for _ in range(200):
        g.autoplay()
        assert card_multiset(g) == cards
        g.deal()
        assert card_multiset(g) == cards
        check_faces(g)
    assert g.score == foundation_cards(g)


def test_scoring_on_and_off_the_foundations():
    g = deal("klondike", 1)
    clear_board(g)
    w = g.ids_of("waste")[0]
    f = g.ids_of("foundation")
    t = g.ids_of("tableau")
    g.slots[w].cards = [Card(1, "S", True)]
    assert g.attempt_move(w, f[0]) and g.score == 1
    g.slots[t[0]].cards = [Card(3, "H", True)]
    g.slots[w].cards = [Card(2, "S", True)]
    assert g.double_click(w) and g.score == 2
    assert g.attempt_move(f[0], t[0]) and g.score == 1        # 2S back down
    assert [str(c) for c in g.cards(t[0])] == ["3H", "2S"]


def test_moving_a_card_off_a_column_turns_the_next_one_up():
    g = deal("klondike", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [Card(9, "C", False), Card(6, "S", True)]
    g.slots[t[1]].cards = [Card(7, "H", True)]
    assert g.attempt_move(t[0], t[1])
    assert g.cards(t[0]) == [Card(9, "C", True)]


def test_only_a_king_goes_on_an_empty_column():
    g = deal("klondike", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [Card(12, "H", True)]
    g.slots[t[1]].cards = [Card(13, "S", True), Card(12, "H", True)]
    assert g.attempt_move(t[0], t[2]) is False
    assert g.attempt_move(t[1], t[2], 1) is False
    assert g.attempt_move(t[1], t[2], 2) is True
