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
