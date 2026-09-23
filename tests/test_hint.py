"""The hint only suggests moves that make progress, so following it can
never loop."""

import pytest

from soliterm.engine import GAME_ORDER, Card
from soliterm.textmode import apply_text_command
from helpers import clear_board, deal


@pytest.fixture
def klondike():
    """An empty Klondike board and its tableau ids."""
    g = deal("klondike", 1)
    clear_board(g)
    return g, g.ids_of("tableau")


def test_a_pointless_shuffle_is_not_a_hint(klondike):
    g, t = klondike
    g.slots[t[0]].cards = [Card(8, "H", True), Card(7, "S", True)]
    g.slots[t[1]].cards = [Card(8, "D", True)]     # 7S could go here too, for nothing
    assert g.best_move() is None
    assert g.hint() is None                        # and there is no stock to deal


def test_uncovering_a_face_down_card_is_suggested(klondike):
    g, t = klondike
    g.slots[t[0]].cards = [Card(9, "C", False), Card(6, "S", True)]
    g.slots[t[1]].cards = [Card(7, "H", True)]
    mv = g.best_move()
    assert mv is not None and mv[:2] == (t[0], t[1])


def test_a_real_build_beats_telling_you_to_deal(klondike):
    g, t = klondike
    g.slots[t[0]].cards = [Card(6, "S", True)]
    g.slots[t[1]].cards = [Card(7, "H", True)]
    g.slots[g.ids_of("stock")[0]].cards = [Card(r, "C", False) for r in range(9, 14)]
    mv = g.best_move()
    assert mv is not None and mv[:2] == (t[0], t[1])


def test_a_lone_king_to_an_empty_column_is_not_suggested(klondike):
    g, t = klondike
    g.slots[t[0]].cards = [Card(13, "S", True)]
    assert g.best_move() is None


def test_the_hint_names_cards_the_way_the_board_draws_them(klondike):
    g, t = klondike
    g.slots[t[0]].cards = [Card(9, "C", False), Card(2, "H", True)]
    g.slots[t[1]].cards = [Card(3, "C", True)]
    assert g.hint()[2] == "Move 2♥ onto 3♣"
    g.symbols = False
    assert g.hint()[2] == "Move 2H onto 3C"


def test_a_foundation_play_is_suggested(klondike):
    g, t = klondike
    g.slots[t[0]].cards = [Card(5, "H", True), Card(1, "S", True)]
    mv = g.best_move()
    assert mv is not None and g.kind(mv[1]) == "foundation"


@pytest.mark.parametrize("key", GAME_ORDER)
def test_following_best_move_always_progresses_and_never_loops(key):
    g = deal(key, 7)
    seen = set()
    deals = 0
    for _ in range(900):
        mv = g.best_move()
        if mv is None:
            if g.deal_is_productive() and deals < 80:
                g.deal()
                deals += 1
                continue
            break
        state = g.serialize()
        assert state not in seen, "best_move revisited a position"
        seen.add(state)
        before = g.progress()
        assert g.attempt_move(*mv), f"best_move {mv} was illegal"
        assert g.progress() > before


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("key", GAME_ORDER)
def test_best_move_is_legal_with_its_pickup_size(key, seed):
    g = deal(key, seed)
    mv = g.best_move()
    if mv is not None:
        assert g.clone().attempt_move(*mv)


# -- when there is nothing to hint ------------------------------------------------

def two_kings(key):
    """A board with just two kings in play: they can move, but it gets you nowhere."""
    g = deal(key, 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [Card(13, "S", True)]
    g.slots[t[1]].cards = [Card(13, "H", True)]
    return g


@pytest.mark.parametrize("key", ["freecell", "yukon", "klondike"])
def test_no_hint_never_sends_you_to_deal_or_says_nothing_can_move(key):
    g = two_kings(key)
    assert g.hint() is None and g.legal_moves()
    ok, msg = apply_text_command(g, "hint")
    assert ok and msg.startswith("Hint: ")
    assert "deal" not in msg and "no move available" not in msg
    assert msg == f"Hint: {g.no_hint_reason()}."


def test_no_hint_offers_undo_only_when_there_is_something_to_undo():
    g = two_kings("freecell")
    assert "undo" not in g.no_hint_reason()
    t = g.ids_of("tableau")
    assert g.attempt_move(t[0], t[2], 1)         # slide a king along, for nothing
    assert g.hint() is None
    assert "undo" in g.no_hint_reason()


def test_a_board_with_no_moves_says_so():
    g = deal("bakersdozen", 1)
    clear_board(g)
    for i, t in enumerate(g.ids_of("tableau")):
        g.slots[t].cards = [Card(5, "S", True), Card(13, "SHDC"[i % 4], True)]
    assert not g.legal_moves()
    assert g.no_hint_reason() == "no moves left"
