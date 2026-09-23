"""Spider: the two-deck deal, dealing rows, same-suit runs and clearing a suit.

Every test passes suits= itself rather than leaning on the default.
"""

import random

import pytest

from soliterm.engine import Card, Spider
from helpers import board_state, card_multiset, clear_board, deal, legal_walk

SUITS = {1: "S", 2: "SH", 4: "SHDC"}


def up(rank, suit):
    return Card(rank, suit, True)


def names(g, sid):
    return [str(c) for c in g.cards(sid)]


def columns(g):
    return g.ids_of("tableau")


@pytest.mark.parametrize("suits", SUITS)
def test_the_deck_is_two_decks_worth_of_the_chosen_suits(suits):
    g = deal("spider", 1, suits=suits)
    cards = card_multiset(g)
    copies = 8 // suits
    assert cards == {(r, s): copies for s in SUITS[suits] for r in range(1, 14)}
    assert sum(cards.values()) == 104


@pytest.mark.parametrize("suits", SUITS)
@pytest.mark.parametrize("seed", range(3))
def test_the_deal(seed, suits):
    g = deal("spider", seed, suits=suits)
    lengths = [len(g.cards(t)) for t in columns(g)]
    assert sorted(lengths) == [5] * 6 + [6] * 4
    assert sum(lengths) == 54
    stock = g.ids_of("stock")[0]
    assert len(g.cards(stock)) == 50
    assert not any(c.face_up for c in g.cards(stock))
    for t in columns(g):
        assert [c.face_up for c in g.cards(t)] == [False] * (len(g.cards(t)) - 1) + [True]
    assert all(not g.cards(f) for f in g.ids_of("foundation"))
    assert not g.is_won()


@pytest.mark.parametrize("suits", SUITS)
def test_each_deal_puts_a_face_up_card_on_every_column(suits):
    g = deal("spider", 2, suits=suits)
    cards = card_multiset(g)
    stock = g.ids_of("stock")[0]
    for i in range(5):
        before = {t: list(g.cards(t)) for t in columns(g)}
        coming = list(reversed(g.cards(stock)[-10:]))
        assert g.can_deal()
        assert g.deal()
        assert len(g.cards(stock)) == 40 - 10 * i
        for t, c in zip(columns(g), coming):
            assert g.cards(t)[:-1] == before[t]
            assert g.cards(t)[-1] == c.up(True)
        assert card_multiset(g) == cards
    assert not g.can_deal()
    assert g.deal() is False


def test_an_empty_column_blocks_the_deal():
    g = deal("spider", 1, suits=4)
    g.slots[columns(g)[3]].cards = []
    before = g.serialize()
    assert not g.can_deal()
    assert g.deal() is False
    assert g.serialize() == before
    assert not g.can_undo()


@pytest.fixture
def table():
    """A four-suit game with everything cleared off."""
    g = deal("spider", 1, suits=4)
    clear_board(g)
    return g, columns(g)


def test_any_suit_builds_on_the_next_rank_up(table):
    g, t = table
    g.slots[t[0]].cards = [up(6, "S")]
    g.slots[t[1]].cards = [up(8, "H")]
    g.slots[t[2]].cards = [Card(7, "H", False)]
    assert g.attempt_move(t[0], t[1]) is False       # skips a rank
    assert g.attempt_move(t[0], t[2]) is False       # onto a face-down card
    g.slots[t[3]].cards = [up(7, "H")]
    assert g.attempt_move(t[0], t[3]) is True
    assert names(g, t[3]) == ["7H", "6S"]


def test_anything_goes_on_an_empty_column(table):
    g, t = table
    g.slots[t[0]].cards = [up(9, "D"), up(4, "C")]
    assert g.attempt_move(t[0], t[5], 1) is True
    assert names(g, t[5]) == ["4C"]


def test_only_a_same_suit_run_lifts_as_a_group(table):
    g, t = table
    g.slots[t[0]].cards = [up(9, "H"), up(8, "S"), up(7, "S")]
    g.slots[t[1]].cards = [up(9, "D")]
    assert g.default_pickup(t[0]) == 2
    assert g.can_pickup(t[0], 2)
    assert not g.can_pickup(t[0], 3)
    assert g.attempt_move(t[0], t[1], 3) is False
    assert g.attempt_move(t[0], t[1]) is True
    assert names(g, t[1]) == ["9D", "8S", "7S"]
    assert names(g, t[0]) == ["9H"]
    assert g.score == 1                              # 8S-7S is still in suit


def test_the_one_line_summary_gets_the_building_rule_right():
    # it shows in --list, the menu and over the board, and any suit builds
    # down (see the tests above); only moving a group needs one suit
    assert "in suit" not in Spider.blurb
    assert "any suit" in Spider.blurb


def test_a_face_down_card_is_never_part_of_a_run(table):
    g, t = table
    g.slots[t[0]].cards = [Card(8, "S", False), up(7, "S")]
    assert g.default_pickup(t[0]) == 1
    assert not g.can_pickup(t[0], 2)


def test_moving_off_a_column_turns_the_next_card_up(table):
    g, t = table
    g.slots[t[0]].cards = [Card(2, "C", False), up(6, "S")]
    g.slots[t[1]].cards = [up(7, "H")]
    assert g.attempt_move(t[0], t[1])
    assert g.cards(t[0]) == [up(2, "C")]


def test_a_full_suit_goes_to_a_foundation(table):
    g, t = table
    g.slots[t[0]].cards = [Card(12, "H", False)] + [up(r, "S") for r in range(13, 1, -1)]
    g.slots[t[1]].cards = [up(1, "S")]
    before, score = board_state(g), g.score
    assert g.attempt_move(t[1], t[0]) is True
    done = [f for f in g.ids_of("foundation") if g.cards(f)]
    assert len(done) == 1
    assert names(g, done[0]) == [str(up(r, "S")) for r in range(13, 0, -1)]
    assert g.cards(t[0]) == [up(12, "H")]            # uncovered and turned up
    assert not g.cards(t[1])
    assert g.score == 12
    assert not g.is_won()
    assert g.undo()
    assert board_state(g) == before and g.score == score
    assert g.redo()
    assert g.score == 12 and len(g.cards(done[0])) == 13


def test_a_deal_can_be_undone_and_redone():
    g = deal("spider", 3, suits=2)
    start = g.serialize()
    assert g.deal()
    dealt = g.serialize()
    assert g.undo() and g.serialize() == start
    assert g.redo() and g.serialize() == dealt


# -- the hint when an empty column blocks the deal --------------------------------

def blocked_deal(g, t, first):
    """Ten cards in the stock, first in column 0, a card nothing builds on in
    each of the next eight, and the last column empty."""
    g.slots[g.ids_of("stock")[0]].cards = [Card(r, "C", False) for r in range(1, 11)]
    g.slots[t[0]].cards = first
    loose = [up(13, "S"), up(13, "H"), up(11, "S"), up(11, "H"),
             up(7, "S"), up(7, "H"), up(2, "S"), up(2, "H")]
    for sid, card in zip(t[1:9], loose):
        g.slots[sid].cards = [card]
    assert not g.can_deal() and g.best_move() is None


def test_the_hint_fills_an_empty_column_so_you_can_deal(table):
    g, t = table
    blocked_deal(g, t, [up(9, "S"), up(4, "H")])
    assert g.hint() == (t[0], t[9], "Move 4♥ to the empty column")
    assert g.attempt_move(t[0], t[9], 1)
    stock = g.ids_of("stock")[0]
    assert g.hint() == (stock, stock, "Deal from the stock")


def test_the_hint_wont_split_a_run_to_fill_a_column(table):
    # splitting 5H-4H would only be undone by the next hint, round and round
    g, t = table
    blocked_deal(g, t, [up(5, "H"), up(4, "H")])
    assert g.hint() is None
    reason = g.no_hint_reason()
    assert "empty column" in reason and "run" in reason
    assert reason != g.deal_blocked_reason()


@pytest.mark.parametrize("suits", SUITS)
def test_following_the_hint_never_comes_back_to_a_position(suits):
    g = deal("spider", 3, suits=suits)
    seen = set()
    for _ in range(400):
        mv = g.hint_move()
        if mv is None:
            break
        if mv[0] == mv[1]:
            assert g.deal()
            continue
        state = board_state(g)
        assert state not in seen, "the hint revisited a position"
        seen.add(state)
        assert g.attempt_move(*mv), f"hinted move {mv} was illegal"


@pytest.mark.parametrize("suits", SUITS)
@pytest.mark.parametrize("seed", range(6))
def test_random_play_keeps_every_card(seed, suits):
    g = deal("spider", seed, suits=suits)
    cards = card_multiset(g)
    rng = random.Random(seed * 31 + suits)
    for _ in legal_walk(g, rng, 200):
        assert card_multiset(g) == cards
        for t in columns(g):
            pile = g.cards(t)
            if pile:
                assert pile[-1].face_up
        for f in g.ids_of("foundation"):
            assert len(g.cards(f)) in (0, 13)
