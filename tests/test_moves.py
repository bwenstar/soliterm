"""Moves the engine must refuse, and stuck detection checked by brute force."""

import random

import pytest

from soliterm import textmode
from soliterm.engine import GAME_ORDER, Card

from helpers import board_state, clear_board, deal, legal_walk


def untouched(g, before):
    return g.serialize() == before and not g.can_undo()


# -- bad slot ids and pickup sizes -------------------------------------------------------

@pytest.mark.parametrize("key", GAME_ORDER)
def test_moves_between_slots_that_do_not_exist_are_refused(key):
    g = deal(key, 3)
    before = g.serialize()
    ns = len(g.slots)
    for src, dst in [(-1, 0), (0, -1), (ns, 0), (0, ns), (99, 0), (0, 99)]:
        for n in (None, 1):
            assert g.attempt_move(src, dst, n) is False
    for sid in (-1, ns, 99):
        assert g.click(sid) is False
        assert g.double_click(sid) is False
    assert untouched(g, before)


@pytest.mark.parametrize("key", GAME_ORDER)
def test_silly_pickup_sizes_are_refused(key):
    g = deal(key, 3)
    before = g.serialize()
    for src in range(len(g.slots)):
        for dst in range(len(g.slots)):
            for n in (0, -3, len(g.cards(src)) + 1, 99):
                assert g.attempt_move(src, dst, n) is False
    assert untouched(g, before)


@pytest.mark.parametrize("key", GAME_ORDER)
def test_a_slot_cannot_move_onto_itself(key):
    g = deal(key, 3)
    before = g.serialize()
    for sid in range(len(g.slots)):
        assert g.attempt_move(sid, sid) is False
    assert untouched(g, before)


@pytest.mark.parametrize("key", GAME_ORDER)
def test_moving_from_an_empty_slot_is_refused(key):
    g = deal(key, 3)
    src = next(s.sid for s in g.slots if not s.cards)
    before = g.serialize()
    for dst in range(len(g.slots)):
        assert g.attempt_move(src, dst) is False
    assert untouched(g, before)


# -- foundation rules -------------------------------------------------------------------------

@pytest.fixture
def klondike():
    g = deal("klondike", 3)
    clear_board(g)
    return g, g.ids_of("waste")[0], g.ids_of("foundation"), g.ids_of("tableau")


def test_only_an_ace_starts_a_foundation(klondike):
    g, w, f, t = klondike
    g.slots[w].cards = [Card(2, "S", True)]
    g.slots[t[0]].cards = [Card(13, "H", True)]
    assert g.attempt_move(w, f[1]) is False
    assert g.attempt_move(t[0], f[1]) is False
    assert g.double_click(w) is False


def test_a_foundation_only_takes_the_next_card_of_its_suit(klondike):
    g, w, f, _t = klondike
    g.slots[f[0]].cards = [Card(1, "S", True)]
    g.slots[w].cards = [Card(1, "H", True)]
    assert g.attempt_move(w, f[0]) is False          # another ace
    g.slots[w].cards = [Card(2, "H", True)]
    assert g.attempt_move(w, f[0]) is False          # right rank, wrong suit
    g.slots[w].cards = [Card(3, "S", True)]
    assert g.attempt_move(w, f[0]) is False          # right suit, skips a rank
    g.slots[w].cards = [Card(2, "S", True)]
    assert g.attempt_move(w, f[0]) is True


@pytest.mark.parametrize("key", ["klondike", "freecell", "eightoff", "bakersdozen"])
def test_a_card_cannot_go_from_one_foundation_to_another(key):
    g = deal(key, 3)
    clear_board(g)
    f = g.ids_of("foundation")
    g.slots[f[0]].cards = [Card(1, "S", True)]
    g.score = 1
    for i in range(6):
        assert g.attempt_move(f[i % 2], f[1 - i % 2], 1) is False
    assert g.cards(f[0]) == [Card(1, "S", True)]
    assert g.score == 1
    assert not any(g.kind(dst) == "foundation" for _, dst, _ in g.legal_moves())


def test_klondike_with_only_an_ace_to_shuffle_between_foundations_is_stuck():
    g = deal("klondike", 3)
    clear_board(g)
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [Card(1, "S", True)]
    g.slots[t[0]].cards = [Card(5, "H", False), Card(5, "D", True)]
    g.slots[t[1]].cards = [Card(9, "C", False), Card(5, "S", True)]
    g.moves = 5
    assert g.legal_moves() == []
    assert g.is_stuck()


def test_canfield_foundation_cards_can_come_back_down():
    # all but the base card a foundation starts from, as in AisleRiot
    g = deal("canfield", 3)
    clear_board(g)
    g.base_val = 5
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [Card(5, "S", True), Card(6, "S", True)]
    g.slots[f[1]].cards = [Card(5, "H", True)]
    g.slots[t[0]].cards = [Card(7, "H", True)]
    g.slots[t[1]].cards = [Card(6, "C", True)]
    g.score = 3
    assert not g.can_pickup(f[1], 1)
    assert g.attempt_move(f[1], t[1], 1) is False
    assert (f[0], t[0], 1) in g.legal_moves()
    assert g.attempt_move(f[0], t[0], 1)
    assert [str(c) for c in g.cards(t[0])] == ["7H", "6S"]
    assert g.cards(f[0]) == [Card(5, "S", True)]
    assert g.score == 2


def test_bakers_dozen_foundation_cards_can_come_back_down():
    g = deal("bakersdozen", 3)
    clear_board(g)
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [Card(1, "S", True), Card(2, "S", True)]
    g.slots[t[0]].cards = [Card(3, "H", True)]
    g.score = 2
    assert g.can_pickup(f[0], 1)
    assert g.attempt_move(f[0], t[1], 1) is False     # an empty column stays empty
    assert (f[0], t[0], 1) in g.legal_moves()
    assert g.attempt_move(f[0], t[0], 1)
    assert [str(c) for c in g.cards(t[0])] == ["3H", "2S"]
    assert [str(c) for c in g.cards(f[0])] == ["AS"]
    assert g.score == 1


def test_a_card_can_only_be_moved_once(klondike):
    g, w, f, _t = klondike
    g.slots[w].cards = [Card(1, "S", True)]
    assert g.attempt_move(w, f[0]) is True
    assert g.attempt_move(w, f[0]) is False
    assert [str(c) for s in g.slots for c in s.cards] == ["AS"]


def test_a_rejected_move_changes_nothing(klondike):
    g, _w, _f, t = klondike
    g.slots[t[0]].cards = [Card(9, "C", False), Card(6, "S", True)]
    g.slots[t[1]].cards = [Card(7, "S", True)]
    before = g.serialize()
    assert g.attempt_move(t[0], t[1]) is False       # same colour
    assert g.attempt_move(t[0], t[2]) is False       # a 6 on an empty column
    assert g.attempt_move(t[0], t[1], 2) is False    # lifting a face-down card
    assert untouched(g, before)


# -- the text command parser ------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["80", "08", "wf9", "t7t0", "9f", "1 2 3 4"])
def test_malformed_text_commands_are_rejected(cmd):
    g = deal("klondike", 3)
    before = g.serialize()
    ok, msg = textmode.apply_text_command(g, cmd)
    assert ok is False
    assert msg.startswith("bad command")
    assert untouched(g, before)


@pytest.mark.parametrize("cmd", ["99 0", "0 99", "6 6", "6 7 0", "6 7 99",
                                 "c 99", "cc 99", "f 99"])
def test_text_moves_on_missing_slots_or_counts_do_nothing(cmd):
    g = deal("klondike", 3)
    before = g.serialize()
    ok, _msg = textmode.apply_text_command(g, cmd)
    assert ok is False
    assert untouched(g, before)


# -- stuck detection against brute force ---------------------------------------------------

def board_changing_actions(g):
    """Every move, click and double click that changes the board, found by
    trying them all on copies of the game."""
    before = board_state(g)
    found = []
    sim = g.clone()
    ns = len(g.slots)
    for src in range(ns):
        for n in range(1, len(g.cards(src)) + 1):
            for dst in range(ns):
                if sim.attempt_move(src, dst, n):
                    if board_state(sim) != before:
                        found.append(("move", src, dst, n))
                    sim = g.clone()
    for sid in range(ns):
        for action in ("click", "double_click"):
            sim = g.clone()
            if getattr(sim, action)(sid) and board_state(sim) != before:
                found.append((action, sid))
    return found


def check_against_brute_force(g):
    found = board_changing_actions(g)
    if not found:
        assert not g.has_any_move(), "claims a move where none exists"
        assert g.is_won() or g.is_stuck()
    else:
        assert g.has_any_move(), f"says no moves but {found[0]} works"
        assert not g.is_stuck()


def test_a_dead_klondike_board_is_stuck():
    g = deal("klondike", 0)
    clear_board(g)
    t = g.ids_of("tableau")
    tops = [(2, "C", 13, "S"), (2, "D", 13, "H"), (2, "H", 13, "D"), (2, "S", 13, "C"),
            (1, "S", 5, "C"), (1, "H", 5, "D"), (1, "D", 5, "H")]
    used = set()
    for col, (r1, s1, r2, s2) in zip(t, tops):
        g.slots[col].cards = [Card(r1, s1, True), Card(r2, s2, True)]
        used |= {(r1, s1), (r2, s2)}
    rest = [(r, s) for s in "SHDC" for r in range(1, 14) if (r, s) not in used]
    for i, (r, s) in enumerate(rest):
        g.slots[t[i % 7]].cards.insert(0, Card(r, s, False))
    assert sum(len(s.cards) for s in g.slots) == 52
    assert g.deal() is False
    assert g.is_stuck()
    assert board_changing_actions(g) == []


def test_an_ace_on_top_means_not_stuck():
    g = deal("klondike", 0)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [Card(1, "S", True)]
    rest = [(r, s) for s in "SHDC" for r in range(1, 14) if (r, s) != (1, "S")]
    for i, (r, s) in enumerate(rest):
        g.slots[t[1 + i % 6]].cards.append(Card(r, s, False))
    assert g.has_any_move()
    check_against_brute_force(g)


def positions(key, seed):
    """A fresh deal, some positions from random play, and wherever following
    the hint runs out."""
    g = deal(key, seed)
    yield g
    rng = random.Random(seed)
    for i, _ in enumerate(legal_walk(g, rng, 60)):
        if i % 20 == 19:
            yield g
    g = deal(key, seed)
    for _ in range(400):
        mv = g.best_move()
        if mv is not None:
            g.attempt_move(*mv)
        elif g.deal_is_productive() and g.redeals_done < 3:
            g.deal()
        else:
            break
    yield g


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("key", GAME_ORDER)
def test_has_any_move_agrees_with_brute_force(key, seed):
    for g in positions(key, seed):
        check_against_brute_force(g)
