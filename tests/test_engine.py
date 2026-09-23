"""Engine basics shared by all nine games: dealing, card conservation, undo
and redo, win detection, the score clamp and end-of-game detection."""

import random

import pytest

import aisle
from aisle import GAME_ORDER, Card
from helpers import EXPECTED_CARDS, card_count, card_multiset, clear_board, deal, random_op


def board(g):
    return [[(c.rank, c.suit, c.face_up) for c in s.cards] for s in g.slots]


# -- dealing ------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("key", GAME_ORDER)
def test_fresh_deal_has_every_card_and_is_not_won(key, seed):
    g = deal(key, seed)
    assert card_count(g) == EXPECTED_CARDS[key]
    assert not g.is_won()


# -- random play ----------------------------------------------------------------

@pytest.mark.parametrize("seed", range(15))
@pytest.mark.parametrize("key", GAME_ORDER)
def test_random_play_never_loses_or_duplicates_a_card(key, seed):
    rng = random.Random(seed * 977 + 5)
    g = deal(key, seed)
    cards = card_multiset(g)
    for op in range(200):
        random_op(g, rng)
        assert card_multiset(g) == cards, f"op {op}"


# -- undo / redo ----------------------------------------------------------------

@pytest.mark.parametrize("key", GAME_ORDER)
def test_undo_all_returns_to_the_deal(key):
    # autoplay counts as a single undoable step
    g = deal(key, 11)
    initial = g.serialize()
    for _ in range(8):
        if g.can_deal():
            g.deal()
        else:
            g.autoplay()
    while g.can_undo():
        g.undo()
    assert g.serialize() == initial


def test_a_failed_click_keeps_the_redo_stack():
    g = deal("klondike", 42)
    g.deal()
    g.undo()
    assert g.can_redo()
    f = g.ids_of("foundation")[0]
    assert g.click(f) is False
    assert g.double_click(f) is False
    assert g.can_redo()
    assert g.redo()


def test_autoplay_that_moves_nothing_adds_no_undo_step():
    g = deal("klondike", 1)
    for s in g.slots:
        if s.kind in ("tableau", "waste"):
            s.cards = []
    before = len(g._undo)
    assert g.autoplay() == 0
    assert len(g._undo) == before


# -- Canfield reserve -------------------------------------------------------------

def _refill_after_emptying_a_column(g, res):
    g.slots[g.ids_of("tableau")[0]].cards = []
    g.gamedef._refill(g)


@pytest.mark.parametrize("action", [
    lambda g, res: g.double_click(res),
    lambda g, res: g.autoplay(),
    _refill_after_emptying_a_column,
], ids=["double_click", "autoplay", "refill"])
def test_canfield_reserve_top_stays_face_up(action):
    g = deal("canfield", 7)
    res = g.ids_of("reserve")[0]
    # a base-rank card on top of the reserve can always go to a foundation
    g.slots[res].cards[-1] = Card(g.base_val, "C", True)
    action(g, res)
    top = g.top(res)
    assert top is None or top.face_up


# -- winning ------------------------------------------------------------------------

def test_klondike_autoplay_finishes_a_won_game():
    g = deal("klondike", 1)
    fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    for i, suit in enumerate("SHDC"):
        g.slots[fids[i]].cards = [Card(r, suit, True) for r in range(1, 13)]
        g.slots[tids[i]].cards = [Card(13, suit, True)]
    assert g.autoplay() == 4
    assert g.is_won()


def test_spider_with_eight_complete_suits_is_won_for_96():
    g = deal("spider", 0)
    clear_board(g)
    for f in g.ids_of("foundation"):
        g.slots[f].cards = [Card(r, "S", True) for r in range(13, 0, -1)]
    g.gamedef.post_move(g)
    assert g.is_won()
    assert g.score == 96


# -- score clamp --------------------------------------------------------------------

def test_score_never_goes_below_zero():
    g = deal("klondike", 1)
    fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    g.slots[fids[0]].cards = [Card(1, "C", True)]
    g.slots[tids[0]].cards = [Card(2, "H", True)]
    g.score = 0
    assert g.attempt_move(fids[0], tids[0])      # taking AC back would be -1
    assert g.score == 0
    g.score = 3
    g.score -= 10
    assert g.score == 0


# -- restart and new deals ------------------------------------------------------

def test_restart_replays_the_same_hand():
    g = aisle.new_solitaire("klondike")          # no fixed seed
    snap, seed = board(g), g.current_seed
    g.deal()
    g.deal()
    assert board(g) != snap
    g.restart()
    assert board(g) == snap
    assert g.current_seed == seed


def test_unseeded_new_games_differ():
    g = aisle.new_solitaire("klondike")
    seeds = set()
    for _ in range(6):
        g.new_game()
        seeds.add(g.current_seed)
    assert len(seeds) >= 2


# -- stuck detection ------------------------------------------------------------------

@pytest.mark.parametrize("key", GAME_ORDER)
def test_a_fresh_deal_is_not_stuck(key):
    g = deal(key, 1)
    assert g.has_any_move()
    assert not g.is_stuck()


def test_a_dead_board_is_stuck_until_a_move_appears():
    g = deal("bakersdozen", 1)
    clear_board(g)
    for i, t in enumerate(g.ids_of("tableau")):
        g.slots[t].cards = [Card(5, "S", True), Card(13, "SHDC"[i % 4], True)]
    assert g.is_stuck()
    g.slots[g.ids_of("tableau")[0]].cards = [Card(1, "S", True)]
    assert not g.is_stuck()
