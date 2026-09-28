"""The hint suggests a move that makes progress when there is one, and
following it never loops."""

import pytest

from soliterm.engine import GAME_ORDER, Card
from soliterm.textmode import apply_text_command

from helpers import board_state, clear_board, deal


@pytest.fixture
def klondike():
    """An empty Klondike board and its tableau ids."""
    g = deal("klondike", 1)
    clear_board(g)
    return g, g.ids_of("tableau")


def test_a_pointless_shuffle_is_not_a_hint(klondike):
    g, t = klondike
    g.slots[t[0]].cards = [Card(8, "H", True), Card(7, "S", True)]
    g.slots[t[1]].cards = [Card(8, "D", True)]  # 7S could go here too, for nothing
    assert g.best_move() is None
    assert g.hint() is None  # and there is no stock to deal


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


@pytest.mark.parametrize("key", GAME_ORDER)
def test_following_the_hint_never_comes_back_to_a_position(key):
    # the moves that only set up the next one included
    g = deal(key, 7)
    seen = set()
    deals = 0
    for _ in range(400):
        mv = g.hint_move()
        if mv is None:
            break
        if mv[0] == mv[1]:  # a deal
            if deals == 80:
                break
            assert g.deal()
            deals += 1
            continue
        state = board_state(g)
        assert state not in seen, "the hint revisited a position"
        seen.add(state)
        assert g.attempt_move(*mv), f"hinted move {mv} was illegal"


def follow_the_hint(g, steps):
    """Do what the hint says, deals and all, for up to `steps` steps."""
    for _ in range(steps):
        mv = g.hint_move()
        if mv is None or g.is_won():
            break
        if mv[0] == mv[1]:
            assert g.deal()
        else:
            assert g.attempt_move(*mv), f"hinted move {mv} was illegal"


@pytest.mark.parametrize(
    "key, number, options",
    [("canfield", 59, {}), ("klondike", 12, {"draw": 3})],
    ids=["canfield:59", "klondike:d3:12"],
)
def test_the_hint_stops_dealing_when_dealing_only_goes_round(key, number, options):
    # the waste goes back to the stock as often as you like here, and a
    # full pass of the stock brings the same cards back round with nothing
    # to play, while a move that sets one up leads on to a win
    g = deal(key, number, **options)
    follow_the_hint(g, 1000)
    assert g.is_won(), f"the hint still says {g.hint()}"


@pytest.mark.parametrize(
    "key, options",
    [
        ("spider", {}),
        ("spiderette", {}),
        ("golf", {}),
        ("triplepeaks", {}),
        ("klondike", {"redeals": "none"}),
    ],
)
def test_the_hint_deals_first_where_the_stock_runs_out(key, options):
    # dealing on here can't bring the same cards round, so a deal that
    # changes the board still comes before a move that only sets one up
    g = deal(key, 7, **options)
    for _ in range(300):
        mv = g.hint_move()
        if mv is None or g.is_won():
            break
        if g.best_move() is None and g.deal_is_productive():
            assert mv[0] == mv[1], f"the hint said {g.hint()} where it could deal"
        if mv[0] == mv[1]:
            assert g.deal()
        else:
            assert g.attempt_move(*mv), f"hinted move {mv} was illegal"


# -- a move that sets up the next one ------------------------------------------


def test_a_card_is_parked_when_that_frees_a_foundation_play():
    g = deal("freecell", 1)
    clear_board(g)
    f, t = g.ids_of("foundation"), g.ids_of("tableau")
    g.slots[f[0]].cards = [Card(r, "S", True) for r in range(1, 5)]
    g.slots[t[0]].cards = [Card(5, "S", True), Card(9, "H", True)]
    # nothing else on the board can build or go up
    others = [Card(13, s, True) for s in "SHDC"] + [Card(7, s, True) for s in "SHD"]
    for sid, card in zip(t[1:], others):
        g.slots[sid].cards = [card]
    assert g.best_move() is None
    src, dst, desc = g.hint()
    assert (src, g.kind(dst)) == (t[0], "freecell")
    assert desc == "Move 9♥ to a free cell"
    assert g.attempt_move(src, dst, 1)
    mv = g.best_move()
    assert mv is not None and mv[:2] == (t[0], f[0])


def test_a_king_is_moved_aside_to_free_the_ace_under_it():
    # Yukon moves any face-up group, and only a king opens an empty column
    g = deal("yukon", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [Card(1, "C", True), Card(13, "D", True), Card(5, "S", True)]
    assert g.best_move() is None
    src, dst, desc = g.hint()
    assert src == t[0] and g.kind(dst) == "tableau"
    assert desc == "Move K♦ to the empty column"
    assert g.attempt_move(src, dst, 2)
    mv = g.best_move()
    assert mv is not None and mv[0] == t[0] and g.kind(mv[1]) == "foundation"


# -- a move when nothing gains ------------------------------------------------


def test_with_nothing_that_gains_the_hint_still_names_a_move():
    # FreeCell deal 1 opens with nothing to build on or send up
    g = deal("freecell", 1)
    assert g.best_move() is None and g.setup_move() is None
    assert g.hint()[2] == "Move 6♠ to a free cell"
    assert apply_text_command(g, "hint") == (
        True,
        "Hint: Move 6♠ to a free cell  (#8 -> cel#0, type: 8 0)",
    )


def test_the_hint_names_no_move_that_just_goes_back_and_forth():
    # 7♠ could slide to 8♦ and back, and 8♦ alone only moves its gap along
    g = deal("freecell", 1)
    clear_board(g)
    t = g.ids_of("tableau")
    g.slots[t[0]].cards = [Card(8, "H", True), Card(7, "S", True)]
    g.slots[t[1]].cards = [Card(8, "D", True)]
    g.slots[t[2]].cards = [Card(13, "C", True), Card(2, "D", True)]
    src, _, desc = g.hint()
    assert src == t[2] and desc == "Move 2♦ to the empty column"


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
    assert g.attempt_move(t[0], t[2], 1)  # slide a king along, for nothing
    assert g.hint() is None
    assert "undo" in g.no_hint_reason()


def test_a_board_with_no_moves_says_so():
    g = deal("bakersdozen", 1)
    clear_board(g)
    for i, t in enumerate(g.ids_of("tableau")):
        g.slots[t].cards = [Card(5, "S", True), Card(13, "SHDC"[i % 4], True)]
    assert not g.legal_moves()
    assert g.no_hint_reason() == "no moves left"
