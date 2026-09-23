"""Rules every game has to follow, run over every game and option setting."""

import hashlib
import itertools
import random

import pytest

from aisle import GAME_ORDER, GAMES
from helpers import EXPECTED_CARDS, board_state, card_multiset, deal, legal_walk, random_op


def variants():
    """(key, options) for every game crossed with every option value."""
    for key in GAME_ORDER:
        spec = GAMES[key].option_spec()
        names = [name for name, _, _ in spec]
        for values in itertools.product(*(vals for _, _, vals in spec)):
            opts = dict(zip(names, values))
            label = key + "".join(f"-{n}{v}" for n, v in opts.items())
            yield pytest.param(key, opts, id=label)


VARIANTS = list(variants())
parametrize_variants = pytest.mark.parametrize("key, opts", VARIANTS)


@parametrize_variants
def test_the_deal_has_every_card_the_right_number_of_times(key, opts):
    g = deal(key, 1, **opts)
    counts = card_multiset(g)
    assert sum(counts.values()) == EXPECTED_CARDS[key]
    assert len(set(counts.values())) == 1          # no card doubled up or missing
    for suit in {s for _, s in counts}:
        assert {r for r, s in counts if s == suit} == set(range(1, 14))


@parametrize_variants
def test_the_same_seed_deals_the_same_game(key, opts):
    assert deal(key, 5, **opts).serialize() == deal(key, 5, **opts).serialize()
    assert board_state(deal(key, 5, **opts)) != board_state(deal(key, 6, **opts))


@parametrize_variants
@pytest.mark.parametrize("seed", range(3))
def test_random_play_never_crashes_or_loses_a_card(key, opts, seed):
    g = deal(key, seed, **opts)
    cards = card_multiset(g)
    rng = random.Random(seed * 1009 + 17)
    for _ in range(300):
        random_op(g, rng)
        assert card_multiset(g) == cards
        assert g.score >= 0


@parametrize_variants
def test_serialize_and_restore_round_trip(key, opts):
    g = deal(key, 4, **opts)
    rng = random.Random(4)
    for i, _ in enumerate(legal_walk(g, rng, 100)):
        if i % 10:
            continue
        text = g.serialize()
        h = deal(key, 4, **opts)
        h._restore(text)
        assert h.serialize() == text
        assert board_state(h) == board_state(g)
        assert h.legal_moves() == g.legal_moves()
        assert h.is_won() == g.is_won()
        assert g.clone().serialize() == text


@parametrize_variants
def test_undo_goes_back_to_the_deal_and_redo_replays_exactly(key, opts):
    g = deal(key, 8, **opts)
    start = g.serialize()
    for _ in legal_walk(g, random.Random(8), 120):
        pass
    # leave two steps on the redo stack; a full undo and redo has to keep them
    last = g.serialize()
    assert g.undo() and g.undo()
    seen = [g.serialize()]
    while g.undo():
        seen.append(g.serialize())
    assert seen[-1] == start
    assert not g.can_undo()
    for want in reversed(seen[:-1]):
        assert g.redo()
        assert g.serialize() == want
    assert g.redo() and g.redo()
    assert g.serialize() == last
    assert not g.can_redo()


@parametrize_variants
def test_every_hint_is_a_legal_move(key, opts):
    g = deal(key, 6, **opts)
    rng = random.Random(6)
    for _ in legal_walk(g, rng, 80):
        before = g.serialize()
        hint = g.hint()
        mv = g.best_move()
        assert g.serialize() == before           # asking changes nothing
        if hint is None:
            continue
        src, dst, desc = hint
        assert isinstance(desc, str) and desc
        if src == dst:                           # "deal from the stock"
            assert mv is None
            assert g.kind(src) == "stock"
            assert g.clone().deal()
        else:
            assert (src, dst) == mv[:2]
            assert mv in g.legal_moves()
            assert g.clone().attempt_move(*mv)


# -- the deals themselves --------------------------------------------------------------

def deal_digest(g):
    lines = [f"s{s.sid}|{s.kind}|"
             + ",".join(f"{c.rank}{c.suit}{'U' if c.face_up else 'D'}" for c in s.cards)
             for s in g.slots]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


# The first 16 hex digits of a hash of each slot's cards for seeds 1 and 2. A
# change here means a seed no longer deals the hand it used to. Spider and Golf
# are left out on purpose: their opening layouts do not match AisleRiot yet.
DEALS = {
    "klondike": ("19ad3b4a4c41a6ee", "108d2b831ab0e22a"),
    "freecell": ("1c20857ef5b1da0b", "a97f37a4def2dac8"),
    "eightoff": ("76b6e3434d3cf673", "c64edf29999d5d51"),
    "yukon": ("6f4d644c6334eee0", "5c1db43f8409f0c3"),
    "bakersdozen": ("ab88db458092bed9", "68206629a1145791"),
    "fortythieves": ("515b7ec5f1f3676a", "96fabcc0b0aab129"),
    "canfield": ("9672abf40f13f3e6", "261302ffa7680263"),
}


@pytest.mark.parametrize("key", sorted(DEALS))
def test_a_seed_still_deals_the_same_hand(key):
    assert tuple(deal_digest(deal(key, seed)) for seed in (1, 2)) == DEALS[key]


def test_the_draw_option_does_not_change_the_deal():
    assert deal_digest(deal("klondike", 1, draw=3)) == DEALS["klondike"][0]
