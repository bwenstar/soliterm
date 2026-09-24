"""Spiderette: Spider's rules on one deck and seven columns, dealt like Klondike."""

import pytest

from soliterm.engine import Card, Spiderette

from helpers import board_state, clear_board, deal

STOCK, FOUNDATIONS, COLUMNS = 0, [1, 2, 3, 4], list(range(5, 12))


def up(rank, suit):
    return Card(rank, suit, True)


def suit(s):
    """A whole suit from King down to Ace, face up."""
    return [up(r, s) for r in range(13, 0, -1)]


@pytest.mark.parametrize("seed", range(3))
def test_the_deal_is_one_to_seven_with_the_tops_up(seed):
    g = deal("spiderette", seed)
    assert [g.kind(sid) for sid in range(12)] == ["stock"] + ["foundation"] * 4 + ["tableau"] * 7
    assert g.ids_of("tableau") == COLUMNS
    assert [len(g.cards(t)) for t in COLUMNS] == [1, 2, 3, 4, 5, 6, 7]
    for t in COLUMNS:
        assert [c.face_up for c in g.cards(t)] == [False] * (len(g.cards(t)) - 1) + [True]
    assert len(g.cards(STOCK)) == 24
    assert not any(c.face_up for c in g.cards(STOCK))
    assert all(not g.cards(f) for f in FOUNDATIONS)
    assert not g.is_won()


def test_the_stock_deals_seven_three_times_then_three():
    g = deal("spiderette", 1)
    for left in (17, 10, 3):
        assert g.deal()
        assert len(g.cards(STOCK)) == left
    before = {t: list(g.cards(t)) for t in COLUMNS}
    coming = list(reversed(g.cards(STOCK)))
    assert g.deal()
    assert not g.cards(STOCK)
    for t, c in zip(COLUMNS[:3], coming):
        assert g.cards(t) == before[t] + [c.up(True)]
    for t in COLUMNS[3:]:
        assert g.cards(t) == before[t]
    assert not g.can_deal()


def test_an_empty_column_blocks_the_deal():
    g = deal("spiderette", 1)
    g.slots[COLUMNS[0]].cards = []
    before = g.serialize()
    assert not g.can_deal()
    assert g.deal() is False
    assert g.serialize() == before
    assert g.deal_blocked_reason() == (
        "fill the 1 empty column before dealing - Spiderette won't deal onto an empty column"
    )


def test_a_full_suit_goes_to_one_of_four_foundations():
    g = deal("spiderette", 1)
    clear_board(g)
    g.slots[COLUMNS[0]].cards = [Card(5, "C", False)] + suit("H")[:-1]
    g.slots[COLUMNS[1]].cards = [up(1, "H")]
    g.slots[STOCK].cards = [Card(r, "S", False) for r in (2, 3, 4)]
    assert g.attempt_move(COLUMNS[1], COLUMNS[0])
    assert [g.cards(f) for f in FOUNDATIONS] == [suit("H"), [], [], []]
    assert g.cards(COLUMNS[0]) == [up(5, "C")]
    assert g.score == 12
    assert g.status == "Stock: 3 (1 deal)  Done: 1/4"


def test_a_won_game_scores_48():
    g = deal("spiderette", 1)
    clear_board(g)
    for f, s in zip(FOUNDATIONS, "HDC"):
        g.slots[f].cards = suit(s)
    g.slots[COLUMNS[0]].cards = suit("S")[:-1]
    g.slots[COLUMNS[1]].cards = [up(1, "S")]
    assert not g.is_won()
    assert g.attempt_move(COLUMNS[1], COLUMNS[0])
    assert g.is_won()
    assert g.score == 48
    assert all(not g.cards(t) for t in COLUMNS)


def test_the_status_counts_the_short_last_deal():
    g = deal("spiderette", 1)
    assert g.status == "Stock: 24 (4 deals)  Done: 0/4"
    for _ in range(3):
        assert g.deal()
    assert g.status == "Stock: 3 (1 deal)  Done: 0/4"


def test_spiderette_has_no_options():
    # AisleRiot always deals it in four suits
    assert Spiderette.option_spec() == []
    assert Spiderette.default_options() == {}
    g = deal("spiderette", 1, suits=2)
    assert g.options == {}
    assert board_state(g) == board_state(deal("spiderette", 1))
    assert {c.suit for s in g.slots for c in s.cards} == set("SHDC")
