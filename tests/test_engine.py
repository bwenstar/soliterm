"""Engine basics shared by all nine games: dealing, card conservation, undo
and redo, win detection, the score clamp and end-of-game detection."""

import random

import pytest

from soliterm import engine
from soliterm.engine import GAME_ORDER, Card
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


def test_golf_waits_for_the_stock_to_start_the_waste():
    g = deal("golf", 1)
    stock, waste = g.ids_of("stock")[0], g.ids_of("waste")[0]
    assert [len(g.cards(t)) for t in g.ids_of("tableau")] == [5] * 7
    assert len(g.cards(stock)) == 17 and not g.cards(waste)
    assert g.legal_moves() == []
    assert not g.is_stuck()
    assert g.hint()[2] == "Deal from the stock"
    assert g.deal()
    assert len(g.cards(stock)) == 16 and g.top(waste).face_up


# -- options --------------------------------------------------------------------

# Values a hand-edited or out-of-date config.json could hold.
@pytest.mark.parametrize("bad", [3, "2", None, 2.0, True, [4]])
def test_a_bad_spider_suits_option_falls_back_to_the_default(bad):
    g = deal("spider", 1, suits=bad)
    assert g.options == engine.Spider.default_options()
    assert card_count(g) == 104


@pytest.mark.parametrize("bad", [0, -1, 7, "3", 3.0, None])
def test_a_bad_klondike_draw_option_falls_back_to_the_default(bad):
    g = deal("klondike", 1, draw=bad)
    assert g.options == engine.Klondike.default_options()
    stock = g.ids_of("stock")[0]
    before = len(g.cards(stock))
    assert g.deal()
    assert len(g.cards(stock)) == before - g.options["draw"]


def test_good_options_are_kept_and_unknown_ones_dropped():
    g = deal("spider", 1, suits=2, colour="blue")
    assert g.options == {"suits": 2}
    assert deal("freecell", 1, draw=3).options == {}


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


@pytest.mark.parametrize("key", GAME_ORDER)
def test_undo_and_redo_bring_the_status_line_along(key):
    g = deal(key, 1)
    rng = random.Random(1)
    statuses = [g.status]
    for _ in range(6):
        if g.can_deal():
            g.deal()
        else:
            g.attempt_move(*rng.choice(g.legal_moves()))
        statuses.append(g.status)
    for want in reversed(statuses[:-1]):
        assert g.undo()
        assert g.status == want == g.gamedef.status(g)
    for want in statuses[1:]:
        assert g.redo()
        assert g.status == want == g.gamedef.status(g)


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


# -- autoplay -----------------------------------------------------------------------

def up(rank, suit):
    return Card(rank, suit, True)


def labels(g, sid):
    return [str(c) for c in g.cards(sid)]


@pytest.mark.parametrize("key", ["klondike", "freecell", "yukon", "bakersdozen"])
def test_autoplay_leaves_a_card_the_twos_still_want(key):
    # 3D could go up, but a black two still out could want to go on it
    g = deal(key, 1)
    clear_board(g)
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [up(1, "D"), up(2, "D")]
    g.slots[t[0]].cards = [up(3, "D")]
    g.slots[t[1]].cards = [up(9, "H"), up(2, "C")]
    g.slots[t[2]].cards = [up(2, "S")]
    assert g.autoplay() == 0
    assert labels(g, t[0]) == ["3D"]
    # with both black twos home it is safe
    g.slots[t[1]].cards = [up(9, "H")]
    g.slots[t[2]].cards = []
    g.slots[f[1]].cards = [up(1, "C"), up(2, "C")]
    g.slots[f[2]].cards = [up(1, "S"), up(2, "S")]
    assert g.autoplay() == 1
    assert labels(g, f[0]) == ["AD", "2D", "3D"]


@pytest.mark.parametrize("key", ["klondike", "freecell"])
def test_autoplay_sends_aces_and_twos_up_whatever_is_left(key):
    g = deal(key, 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [up(8, "C"), up(2, "H")]
    g.slots[t[1]].cards = [up(13, "S"), up(1, "H")]
    assert g.autoplay() == 2
    assert labels(g, t[0]) == ["8C"] and labels(g, t[1]) == ["KS"]


def test_eightoff_autoplay_sends_up_everything_that_goes():
    # building by suit, nothing can want a card once the one below it is home
    g = deal("eightoff", 1)
    clear_board(g)
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [up(1, "D"), up(2, "D")]
    g.slots[t[0]].cards = [up(3, "D")]
    g.slots[t[1]].cards = [up(2, "C")]
    assert g.autoplay() == 1


def test_forty_thieves_autoplay_waits_for_the_other_deck():
    g = deal("fortythieves", 1)
    clear_board(g)
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [up(1, "D"), up(2, "D")]
    g.slots[t[0]].cards = [up(3, "D")]
    g.slots[t[1]].cards = [up(9, "S"), up(2, "D")]    # the other deck's 2D
    assert g.autoplay() == 0
    g.slots[t[1]].cards = [up(9, "S")]
    g.slots[f[1]].cards = [up(1, "D"), up(2, "D")]
    assert g.autoplay() == 1


def test_canfield_autoplay_counts_from_the_base_card():
    g = deal("canfield", 1)
    clear_board(g)
    g.base_val = 5
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [up(5, "D"), up(6, "D")]
    g.slots[t[0]].cards = [up(7, "D")]            # a black six still wants it
    g.slots[t[1]].cards = [up(10, "H"), up(6, "C")]
    g.slots[t[2]].cards = [up(5, "S")]            # a base card always goes
    assert g.autoplay() == 1
    assert labels(g, t[0]) == ["7D"] and not g.cards(t[2])


@pytest.mark.parametrize("key", ["klondike", "freecell", "yukon", "bakersdozen"])
def test_autoplay_finishes_a_board_with_every_column_in_order(key):
    g = deal(key, 1)
    clear_board(g)
    t = g.ids_of("tableau")
    for col, (odd, even) in zip(t, ["SH", "HS", "CD", "DC"]):
        g.slots[col].cards = [up(r, odd if r % 2 else even) for r in range(13, 0, -1)]
    assert g.autoplay() == 52
    assert g.is_won()


# -- double click -------------------------------------------------------------------

@pytest.mark.parametrize("key, blocker", [("klondike", up(2, "C")),
                                          ("fortythieves", up(2, "D"))],
                         ids=["klondike", "fortythieves"])
def test_double_clicking_a_foundation_sends_up_all_it_can(key, blocker):
    # unlike autoplay it doesn't wait for the two that could want the 3D
    g = deal(key, 1)
    clear_board(g)
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [up(1, "D"), up(2, "D")]
    g.slots[t[0]].cards = [up(4, "D"), up(3, "D")]
    g.slots[t[1]].cards = [up(13, "H"), blocker]
    g.score = 2
    assert g.autoplay() == 0
    assert g.double_click(f[1])
    assert labels(g, f[0]) == ["AD", "2D", "3D", "4D"]
    assert not g.cards(t[0])
    assert g.score == 4
    assert g.undo() and labels(g, t[0]) == ["4D", "3D"]
    g.slots[t[0]].cards = [up(9, "S")]
    assert g.double_click(f[0]) is False


def test_forty_thieves_double_click_falls_back_to_the_tableau():
    g = deal("fortythieves", 1)
    clear_board(g)
    f, t, w = g.ids_of("foundation"), g.ids_of("tableau"), g.ids_of("waste")[0]
    g.slots[t[0]].cards = [up(5, "C"), up(9, "H")]
    g.slots[t[2]].cards = [up(10, "H")]
    # a column to build on comes before the empty one
    assert g.double_click(t[0])
    assert labels(g, t[2]) == ["10H", "9H"] and labels(g, t[0]) == ["5C"]
    assert g.score == 0
    g.slots[w].cards = [up(8, "H")]
    assert g.double_click(w)
    assert labels(g, t[2]) == ["10H", "9H", "8H"]
    g.slots[w].cards = [up(4, "S")]
    assert g.double_click(w)
    assert labels(g, t[1]) == ["4S"]
    # a foundation still comes first
    g.slots[w].cards = [up(1, "S")]
    assert g.double_click(w)
    assert labels(g, f[0]) == ["AS"] and g.score == 1
    # and with no room anywhere nothing moves
    for x in t:
        g.slots[x].cards = g.cards(x) or [up(13, "D")]
    before = g.serialize()
    assert g.double_click(t[0]) is False
    assert g.serialize() == before


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
    g = engine.new_solitaire("klondike")          # no fixed seed
    snap, seed = board(g), g.current_seed
    g.deal()
    g.deal()
    assert board(g) != snap
    g.restart()
    assert board(g) == snap
    assert g.current_seed == seed


def test_unseeded_new_games_differ():
    g = engine.new_solitaire("klondike")
    seeds = set()
    for _ in range(6):
        g.new_game()
        seeds.add(g.current_seed)
    assert len(seeds) >= 2


def test_a_fixed_seed_only_fixes_the_first_deal():
    g = deal("klondike", 5)
    hands = [board(g)]
    for _ in range(3):
        g.new_game()
        hands.append(board(g))
    assert len({str(h) for h in hands}) == 4
    assert hands[0] == board(deal("klondike", 5))


def test_the_deals_after_a_fixed_seed_are_reproducible():
    a, b = deal("klondike", 5), deal("klondike", 5)
    for _ in range(3):
        a.new_game()
        b.new_game()
        assert board(a) == board(b)
        assert a.current_seed == b.current_seed


def test_restart_replays_a_new_deal_made_under_a_fixed_seed():
    g = deal("klondike", 5)
    g.new_game()
    hand = board(g)
    g.deal()
    g.restart()
    assert board(g) == hand


def test_a_negative_seed_is_refused():
    # random.Random(-5) shuffles exactly like Random(5), so -5 would be a
    # second name for seed 5's deal
    with pytest.raises(ValueError):
        deal("golf", -5)
    g = deal("golf", 5)
    with pytest.raises(ValueError):
        g.new_game(seed=-1)
    assert board(g) == board(deal("golf", 5))


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
