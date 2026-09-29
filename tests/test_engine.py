"""Engine basics shared by every game: dealing, card conservation, undo
and redo, win detection, the score clamp and end-of-game detection."""

import random

import pytest

from soliterm import engine
from soliterm.engine import GAME_ORDER, Card, core

from helpers import (
    EXPECTED_CARDS,
    card_count,
    card_multiset,
    clear_board,
    deal,
    random_op,
    stalled_klondike,
)


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


def played_a_little(key):
    """A deal a few good moves in, with nothing to redo."""
    g = deal(key, 11)
    for _ in range(12):
        mv = g.best_move()
        if mv is not None:
            g.attempt_move(*mv)
        elif not g.deal():
            break
    return g


@pytest.mark.parametrize("key", GAME_ORDER)
def test_undo_all_goes_back_to_the_deal_and_redo_all_replays_it(key):
    start = deal(key, 11).serialize()
    g = played_a_little(key)
    end, steps = g.serialize(), len(g._undo)
    assert steps > 0
    assert g.undo_all() == steps
    assert g.serialize() == start
    assert not g.can_undo()
    assert g.redo_all() == steps
    assert g.serialize() == end
    assert not g.can_redo()


def test_undo_all_leaves_the_moves_to_redo_one_at_a_time():
    g = deal("klondike", 42)
    g.deal()
    first = g.serialize()
    g.deal()
    assert g.undo_all() == 2
    assert g.redo()
    assert g.serialize() == first


def test_undo_all_and_redo_all_with_nothing_to_do_return_0():
    g = deal("klondike", 42)
    assert (g.undo_all(), g.redo_all()) == (0, 0)


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


@pytest.mark.parametrize(
    "action",
    [
        lambda g, res: g.double_click(res),
        lambda g, res: g.autoplay(),
        _refill_after_emptying_a_column,
    ],
    ids=["double_click", "autoplay", "refill"],
)
def test_canfield_reserve_top_stays_face_up(action):
    g = deal("canfield", 7)
    res = g.ids_of("reserve")[0]
    # a base-rank card on top of the reserve can always go to a foundation
    g.slots[res].cards[-1] = Card(g.base_val, "C", True)
    action(g, res)
    top = g.top(res)
    assert top is None or top.face_up


@pytest.mark.parametrize("seed", [1, 3, 7])
def test_canfield_scores_the_base_card_it_deals(seed):
    # a point for each card on the foundations, so a win is worth 52
    g = deal("canfield", seed)
    assert sum(len(g.cards(f)) for f in g.ids_of("foundation")) == 1
    assert g.score == 1
    g.restart()
    assert g.score == 1
    g.new_game()
    assert g.score == 1


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
    g.slots[t[1]].cards = [up(9, "S"), up(2, "D")]  # the other deck's 2D
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
    g.slots[t[0]].cards = [up(7, "D")]  # a black six still wants it
    g.slots[t[1]].cards = [up(10, "H"), up(6, "C")]
    g.slots[t[2]].cards = [up(5, "S")]  # a base card always goes
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


# -- finishing ----------------------------------------------------------------------


def near_won():
    """Klondike with A-Q home in every suit and the four kings on the tableau."""
    g = deal("klondike", 1)
    fids, tids = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    for i, suit in enumerate("SHDC"):
        g.slots[fids[i]].cards = [up(r, suit) for r in range(1, 13)]
        g.slots[tids[i]].cards = [up(13, suit)]
    return g


def test_finish_moves_on_near_won():
    assert near_won().finish_moves() == [(6, 2), (7, 3), (8, 4), (9, 5)]


def test_finish_moves_sends_up_what_safe_autoplay_leaves():
    g = stalled_klondike()
    before = g.serialize()
    moves = g.finish_moves()
    assert len(moves) == 37
    assert moves[:2] == [(6, 3), (6, 5)]
    assert g.serialize() == before


def with_a_card_face_down():
    g = near_won()
    g.slots[6].cards = [g.cards(6)[0].up(False)]
    return g


def with_cards_in_the_stock():
    g = near_won()
    g.slots[0].cards, g.slots[9].cards = g.slots[9].cards, []
    return g


def won():
    g = near_won()
    g.autoplay()
    return g


@pytest.mark.parametrize(
    "position",
    [with_a_card_face_down, with_cards_in_the_stock, lambda: stalled_klondike(blocked=True), won],
    ids=["a card face down", "cards in the stock", "a blocked card", "a won game"],
)
def test_finish_moves_is_none(position):
    g = position()
    before = g.serialize()
    assert g.finish_moves() is None
    assert g.serialize() == before


def test_finish_is_one_undo_step():
    g = stalled_klondike()
    assert g.autoplay() == 1
    assert g.undo()
    before, score = g.serialize(), g.score
    assert g.finish() == 37
    assert g.is_won()
    assert (g.moves, g.score) == (1, score + 37)
    assert not g.can_redo()
    assert g.undo()
    assert not g.can_undo()
    assert g.serialize() == before


def test_finish_says_where_each_card_lands_as_it_goes():
    g = stalled_klondike()
    moves = g.finish_moves()
    landed = []
    g.finish(lambda src, dst: landed.append((src, dst, len(g.cards(dst)))))
    assert [(src, dst) for src, dst, _ in landed] == moves
    assert landed[0][2] == 5  # the 5H is already on the hearts


def test_the_finish_counts_one_move_and_calls_the_game_after_every_card(monkeypatch):
    g = stalled_klondike()
    rules, calls = g.gamedef, []
    after_move, post_move = rules.after_move, rules.post_move

    def after(on, src, cards, dst):
        if on is g:  # not the copy finish_moves() plans on
            calls.append(("after_move", g.moves))
        after_move(on, src, cards, dst)

    def post(on):
        if on is g:
            calls.append(("post_move", g.moves))
        post_move(on)

    monkeypatch.setattr(rules, "after_move", after)
    monkeypatch.setattr(rules, "post_move", post)
    sent = g.finish()
    assert calls == [("after_move", 1), ("post_move", 1)] * sent
    assert g.moves == 1


def test_nothing_to_finish_adds_no_undo_step():
    g = stalled_klondike(blocked=True)
    assert g.finish() == 0
    assert not g.can_undo()


# -- double click -------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, blocker, score",
    [("klondike", up(2, "C"), 4), ("fortythieves", up(2, "D"), 20)],
    ids=["klondike", "fortythieves"],
)
def test_double_clicking_a_foundation_sends_up_all_it_can(key, blocker, score):
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
    assert g.score == score
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
    assert labels(g, f[0]) == ["AS"] and g.score == 5
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
    assert g.attempt_move(fids[0], tids[0])  # taking AC back would be -1
    assert g.score == 0
    g.score = 3
    g.score -= 10
    assert g.score == 0


# -- restart and new deals ------------------------------------------------------


def test_a_game_knows_its_deal_number():
    g = deal("klondike", 5)
    assert g.deal_number == 5
    g.new_game(8)
    assert g.deal_number == 8
    g.deal()
    g.restart()
    assert g.deal_number == 8
    assert g.clone().deal_number == 8


def test_restart_replays_the_same_hand():
    g = engine.new_solitaire("klondike")  # no fixed seed
    snap, seed = board(g), g.deal_number
    g.deal()
    g.deal()
    assert board(g) != snap
    g.restart()
    assert board(g) == snap
    assert g.deal_number == seed


def test_restart_keeps_the_daily_and_n_drops_it():
    g = deal("klondike", 20260924)
    assert g.daily is None
    g.daily = "2026-09-24"
    g.deal()
    assert g.clone().daily == "2026-09-24"
    g.restart()
    assert g.daily == "2026-09-24"
    g.new_game()
    assert g.daily is None
    g.daily = "2026-09-24"
    g.new_game(options={"draw": 3})  # the options screen deals on too
    assert g.daily is None


def test_unseeded_new_games_differ():
    g = engine.new_solitaire("klondike")
    seeds = set()
    for _ in range(6):
        g.new_game()
        seeds.add(g.deal_number)
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
        assert a.deal_number == b.deal_number


def test_restart_replays_a_new_deal_made_under_a_fixed_seed():
    g = deal("klondike", 5)
    g.new_game()
    hand = board(g)
    g.deal()
    g.restart()
    assert board(g) == hand


@pytest.mark.parametrize("key", GAME_ORDER)
def test_dealing_a_number_does_not_use_pythons_random(key, monkeypatch):
    # random's shuffle has changed between Python versions, so a deal number
    # that went through it could deal another hand on another Python
    g, want = deal(key, 3), board(deal(key, 7))
    monkeypatch.setattr(core, "random", None)
    g.new_game(7)
    assert board(g) == want
    g.deal()
    g.restart()
    assert board(g) == want
    assert board(g.clone()) == want


def test_deal_0_and_the_last_deal_both_deal():
    for number in (0, 2147483647):
        g = deal("golf", number)
        assert g.deal_number == number
        assert board(g) == board(deal("golf", number))
    assert board(deal("golf", 0)) != board(deal("golf", 2147483647))


@pytest.mark.parametrize("number", [-1, 2147483648])
def test_a_deal_number_out_of_range_is_refused(number):
    message = f"deal numbers run from 0 to 2147483647, not {number}"
    with pytest.raises(ValueError, match=message):
        deal("golf", number)
    g = deal("golf", 5)
    with pytest.raises(ValueError, match=message):
        g.new_game(number)
    assert board(g) == board(deal("golf", 5))


def test_n_after_a_chosen_deal_deals_the_next_number():
    g = deal("klondike", 5)
    g.new_game()
    assert g.deal_number == 6
    assert board(g) == board(deal("klondike", 6))
    g.new_game()
    assert g.deal_number == 7


def test_the_last_deal_wraps_to_0():
    g = deal("klondike", 2147483647)
    g.new_game()
    assert g.deal_number == 0
    assert board(g) == board(deal("klondike", 0))


def test_a_random_deal_is_one_of_the_first_million():
    g = engine.new_solitaire("klondike")
    numbers = set()
    for _ in range(50):
        g.new_game()
        numbers.add(g.deal_number)
    assert all(1 <= n <= 1_000_000 for n in numbers)
    assert len(numbers) > 1


def test_new_game_can_change_the_options():
    g = deal("klondike", 5)
    g.new_game(options={"draw": 3})
    assert g.options == {"draw": 3, "redeals": "standard"}
    assert g.deal_number == 6
    assert board(g) == board(deal("klondike", 6, draw=3))
    # and a bad value falls back to the default, as it does from the config
    g.new_game(options={"draw": "3"})
    assert g.options["draw"] == 1


# -- saving a position ----------------------------------------------------------


@pytest.mark.parametrize("key", GAME_ORDER)
def test_serialize_leaves_the_session_seed_out(key):
    # a position is the same whether or not the session began on a chosen deal
    g = engine.new_solitaire(key)
    g.new_game(4)
    assert g.serialize() == deal(key, 4).serialize()
    assert "seed=" not in g.serialize()


def test_undo_steps_with_an_old_seed_line_still_restore():
    g = deal("klondike", 4)
    g.deal()
    lines = g.serialize().splitlines()
    old = "\n".join([lines[0], "seed=4", *lines[1:]])
    h = deal("klondike", 4)
    h._restore(old)
    assert h.serialize() == g.serialize()


def swap_line(text, start, new):
    """text with its line beginning `start` replaced by `new` (None drops it)."""
    lines = [new if line.startswith(start) else line for line in text.splitlines()]
    return "\n".join(line for line in lines if line is not None)


@pytest.mark.parametrize(
    "start, new",
    [
        ("moves=", "moves=x"),
        ("moves=", None),
        ("s0|", "s0|stock|none|0|14SU"),
        ("s0|", "s0|stock|none|0|5XU"),
        ("s0|", "s0|stock|none|0|5S"),
        ("s0|", "s0|stock"),
        ("moves=", "junk"),
    ],
    ids=[
        "moves=x",
        "missing moves=",
        "s0|stock|none|0|14SU",
        "s0|stock|none|0|5XU",
        "s0|stock|none|0|5S",
        "s0|stock",
        "junk",
    ],
)
def test_parse_refuses(start, new):
    g = deal("klondike", 4)
    with pytest.raises(ValueError, match="position"):
        g._parse(swap_line(g.serialize(), start, new))


def test_parse_reads_back_what_serialize_writes():
    g = deal("klondike", 4)
    g.deal()
    key, counters, slots = g._parse(g.serialize())
    assert key == "klondike"
    assert counters == {"score": g.score, "base": 0, "moves": 1, "redeals": 0}
    assert slots == g.slots


@pytest.mark.parametrize(
    "start, new",
    [
        ("game=", "game=spider"),
        ("moves=", "moves=-1"),
        ("base=", "base=14"),
        ("s0|", None),
        ("s1|", "s1|reserve|none|0|"),
        ("s6|", "s6|tableau|down|1|3SU"),
    ],
    ids=[
        "another game",
        "negative moves",
        "base past a king",
        "a slot dropped",
        "a slot renamed",
        "a card changed",
    ],
)
def test_check_position_refuses_what_does_not_fit(start, new):
    g = deal("klondike", 4)
    text = g.serialize()
    g._check_position(text)  # the position itself fits
    with pytest.raises(ValueError, match="fit"):
        g._check_position(swap_line(text, start, new))


@pytest.mark.parametrize("steps", [0, 1, 500])
def test_snapshot_keeps_the_newest_steps(steps):
    g = deal("klondike", 4)
    for _ in range(6):
        g.deal()
    g.undo()
    g.undo()
    undo = [t.decode() for t in g._undo]
    redo = [t.decode() for t in g._redo]
    want = {0: ([], []), 1: (undo[-1:], redo[-1:]), 500: (undo, redo)}[steps]
    snap = g.snapshot(steps)
    assert (snap["undo"], snap["redo"]) == want
    assert snap["game"] == "klondike" and snap["deal"] == 4 and snap["daily"] is None
    assert snap["chosen"] is True
    assert snap["options"] == g.options and snap["options"] is not g.options
    assert (snap["moves"], snap["score"]) == (4, g.score)
    assert snap["position"] == g.serialize()


@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_game_resumes_where_it_was(key):
    g = deal(key, 1)
    start = g.serialize()
    for _ in range(5):
        src, dst, n = g.hint_move() or g.legal_moves()[0]
        assert g.deal() if src == dst else g.attempt_move(src, dst, n)
    last = g.serialize()
    assert g.undo()
    h = engine.resume_solitaire(g.snapshot(500))
    assert h.serialize() == g.serialize()
    assert h.redo()
    assert h.serialize() == last
    for _ in range(5):
        assert h.undo()
    assert h.serialize() == start
    assert not h.can_undo()


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(game="nosuchgame"),
        lambda s: s.update(game="spider", options={}),
        lambda s: s.update(position=swap_line(s["position"], "s6|", "s6|tableau|down|1|3SU")),
        lambda s: s.update(options={"draw": 2}),
        lambda s: s.update(options={"draw": True}),
        lambda s: s.update(deal=-1),
        lambda s: s.update(deal=2**31),
        lambda s: s.update(deal=True),
        lambda s: s.update(undo=s["position"]),
        lambda s: s.update(daily="24/09/2026"),
        lambda s: s.update(daily="2026-02-30"),
        lambda s: s.update(daily="20260924"),
        lambda s: s.update(daily=20260924),
        lambda s: s.update(chosen=1),
        lambda s: s.update(hints=-1),
        lambda s: s.update(hints="2"),
        lambda s: s.update(undos=True),
    ],
    ids=[
        "an unknown game",
        "another game",
        "a changed card",
        "an unknown option value",
        "an option of the wrong type",
        "a negative deal",
        "a deal past the last",
        "a bool deal",
        "undo not a list",
        "a daily that isn't a date",
        "a daily on a day there wasn't",
        "a daily without its dashes",
        "a daily as a number",
        "chosen as a number",
        "hints below 0",
        "hints as text",
        "undos as true",
    ],
)
def test_resume_refuses(change):
    snap = deal("klondike", 4).snapshot(500)
    engine.resume_solitaire(dict(snap))  # as it was, it resumes
    change(snap)
    with pytest.raises(ValueError, match="fit"):
        engine.resume_solitaire(snap)


def test_a_daily_resumes_as_a_daily():
    g = deal("klondike", 20260924)
    g.daily = "2026-09-24"
    g.deal()
    snap = g.snapshot(500)
    assert snap["daily"] == "2026-09-24"
    assert engine.resume_solitaire(snap).daily == "2026-09-24"
    del snap["daily"]  # a save from before there were dailies
    assert engine.resume_solitaire(snap).daily is None
    assert engine.resume_solitaire({**snap, "daily": None}).daily is None


def deals_after(g):
    """The numbers of the next three deals n would deal."""
    after = []
    for _ in range(3):
        g.new_game()
        after.append(g.deal_number)
    return after


def test_a_resumed_chosen_deal_goes_on_to_the_next_number():
    g = deal("klondike", 5)
    g.deal()
    h = engine.resume_solitaire(g.snapshot(500))
    assert h.deal_number == 5
    h.restart()
    assert board(h) == board(deal("klondike", 5))
    assert deals_after(h) == [6, 7, 8]


def test_a_resumed_random_deal_deals_at_random_after():
    g = engine.new_solitaire("klondike")
    g.deal()
    h = engine.resume_solitaire(g.snapshot(500))
    assert h.seed is None
    number = h.deal_number
    assert deals_after(h) != [number + 1, number + 2, number + 3]


def test_a_save_from_before_the_mark_deals_at_random_after():
    snap = deal("klondike", 5).snapshot(500)
    del snap["chosen"]
    assert engine.resume_solitaire(snap).seed is None


# -- hints and undos ------------------------------------------------------------------


def test_the_hints_asked_for_and_the_moves_undone_are_counted():
    g = deal("klondike", 4)
    assert (g.hints, g.undos) == (0, 0)
    g.hint()
    for _ in range(3):
        g.deal()
    g.hint()
    assert g.undo()
    assert g.redo()  # which takes none off
    assert g.undo_all() == 3  # each move taken back
    assert not g.undo()  # nothing to take back
    # back at the deal, and still counted: undo doesn't take them back
    assert (g.moves, g.hints, g.undos) == (0, 2, 4)


@pytest.mark.parametrize("again", ["new_game", "restart"])
def test_a_new_deal_or_the_same_one_again_counts_from_nothing(again):
    g = deal("klondike", 4)
    g.deal()
    g.hint()
    assert g.undo()
    g.hints = None  # as for a game from a save too old to have it
    getattr(g, again)()
    assert (g.hints, g.undos) == (0, 0)


def test_counts_not_known_stay_unknown():
    g = deal("klondike", 4)
    g.hints = g.undos = None
    g.deal()
    g.hint()
    assert g.undo()
    assert (g.hints, g.undos) == (None, None)


def test_the_counts_go_with_the_game_and_carry_on_from_there():
    g = deal("klondike", 4)
    g.deal()
    g.hint()
    g.hint()
    assert g.undo()
    snap = g.snapshot(500)
    assert (snap["hints"], snap["undos"]) == (2, 1)
    h = engine.resume_solitaire(snap)
    assert (h.hints, h.undos) == (2, 1)
    h.hint()
    assert (h.hints, h.undos) == (3, 1)


def test_a_save_from_before_the_counts_has_them_unknown():
    snap = deal("klondike", 4).snapshot(500)
    del snap["hints"], snap["undos"]
    g = engine.resume_solitaire(snap)
    assert (g.hints, g.undos) == (None, None)
    # and a snapshot leaves out what isn't known, as the save did
    assert not {"hints", "undos"} & set(g.snapshot(500))
    h = engine.resume_solitaire({**snap, "hints": None, "undos": 2})
    assert (h.hints, h.undos) == (None, 2)


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
