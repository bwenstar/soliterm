"""Pyramid, AisleRiot's Thirteen: take the pyramid apart in pairs making 13."""

import io

import pytest

from soliterm import aisleriot as ar
from soliterm import engine, saves, store, textmode
from soliterm.engine import Card
from soliterm.engine.games.pyramid import COVERS, SPOTS

from helpers import board_state, clear_board, deal

STOCK, WASTE, PYRAMID, DISCARD = 0, 1, list(range(2, 30)), 30


def up(rank, suit):
    return Card(rank, suit, True)


def down(rank, suit):
    return Card(rank, suit, False)


def board(cards, waste=(), stock=()):
    """A game with the pyramid cards given as {index: card}, `waste` on the
    waste (the top last) and `stock` face down on the stock, and every
    other card taken off already."""
    g = deal("pyramid", 1)
    clear_board(g)
    g.symbols = False
    for i, card in cards.items():
        g.slots[PYRAMID[i]].cards = [card]
    g.slots[WASTE].cards = list(waste)
    g.slots[STOCK].cards = [down(r, s) for r, s in stock]
    g.update_status()
    return g


def names(g, sid):
    return [str(c) for c in g.cards(sid)]


def play(g, commands):
    """Type text-mode commands, each of which has to work."""
    for cmd in commands.split(", "):
        ok, said = textmode.apply_text_command(g, cmd)
        assert ok, f"{cmd}: {said}"


# -- the layout and the deal ----------------------------------------------------------


def test_each_card_is_covered_by_the_two_cards_below_it():
    assert [len(c) for c in COVERS] == [2] * 21 + [0] * 7
    assert COVERS[0] == [1, 2]
    assert COVERS[1] == [3, 4]
    assert COVERS[20] == [26, 27]
    # the peak half way across the bottom row, each row a half card wider
    assert SPOTS[0] == (0, 6)
    assert SPOTS[21:] == [(6, x) for x in range(0, 13, 2)]


@pytest.mark.parametrize("seed", range(3))
def test_the_deal_turns_up_only_the_bottom_row(seed):
    g = deal("pyramid", seed)
    kinds = ["stock", "waste"] + ["tableau"] * 28 + ["foundation"]
    assert [g.kind(sid) for sid in range(31)] == kinds
    assert all(len(g.cards(p)) == 1 for p in PYRAMID)
    assert [g.top(p).face_up for p in PYRAMID] == [False] * 21 + [True] * 7
    assert len(g.cards(STOCK)) == 24
    assert not any(c.face_up for c in g.cards(STOCK))
    assert g.empty(WASTE) and g.empty(DISCARD)
    assert g.score == 0
    assert g.status == "Stock: 24 left"


def test_there_are_no_options():
    rules = engine.GAMES["pyramid"]
    assert rules.option_spec() == [] and rules.default_options() == {}


# -- pairs and kings ---------------------------------------------------------------


@pytest.mark.parametrize(
    "first, second, ok",
    [
        (1, 12, True),  # an Ace and a Queen
        (2, 11, True),  # a Jack counts 11
        (3, 10, True),
        (4, 9, True),
        (5, 8, True),
        (6, 7, True),
        (6, 6, False),
        (7, 7, False),
        (12, 2, False),
        (1, 13, False),  # a King goes alone
        (10, 4, False),
    ],
)
def test_two_free_cards_making_13_go_as_a_pair(first, second, ok):
    g = board({26: up(first, "S"), 27: up(second, "H")}, stock=[(9, "D")])
    assert g.attempt_move(PYRAMID[26], PYRAMID[27]) is ok
    if ok:
        assert g.empty(PYRAMID[26]) and g.empty(PYRAMID[27])
        # the one dropped on top
        assert g.cards(DISCARD) == [up(second, "H"), up(first, "S")]
        assert (g.score, g.moves) == (2, 1)
    g = board({26: up(first, "S"), 27: up(second, "H")}, stock=[(9, "D")])
    assert g.attempt_move(PYRAMID[27], PYRAMID[26]) is ok


def test_a_card_is_played_on_its_own_and_not_lifted_with_others():
    g = board({27: up(5, "S")}, waste=[up(8, "H")], stock=[(9, "D")])
    assert g.can_pickup(PYRAMID[27], 1)
    assert not g.can_pickup(PYRAMID[27], 2)
    assert not g.can_pickup(STOCK, 1)
    assert not g.can_pickup(DISCARD, 1)


@pytest.mark.parametrize("where", ["pyramid", "waste"])
@pytest.mark.parametrize("how", ["double-click", "drop"])
def test_a_free_king_goes_on_its_own(where, how):
    king = up(13, "S")
    g = board({27: up(5, "H")}, stock=[(9, "D")])
    sid = PYRAMID[26] if where == "pyramid" else WASTE
    g.slots[sid].cards = [king]
    if how == "drop":
        assert g.attempt_move(sid, DISCARD)
    else:
        assert g.double_click(sid)
    assert g.empty(sid)
    assert g.cards(DISCARD) == [king]
    assert (g.score, g.moves) == (1, 1)


@pytest.mark.parametrize("rank", [1, 5, 12])
def test_any_other_card_does_not_go_alone(rank):
    g = board({27: up(rank, "H")}, stock=[(9, "D")])
    assert not g.double_click(PYRAMID[27])
    assert not g.attempt_move(PYRAMID[27], DISCARD)
    assert not g.click(PYRAMID[27])
    assert g.cards(PYRAMID[27]) == [up(rank, "H")]
    assert g.moves == 0


def test_a_click_on_a_king_leaves_it_to_f_or_a_double_click():
    # AisleRiot takes one off with a click; here a click picks it up
    g = board({27: up(13, "H")}, stock=[(9, "D")])
    assert not g.click(PYRAMID[27])
    assert g.cards(PYRAMID[27]) == [up(13, "H")]


def test_a_covered_card_stays_down_and_cannot_be_played():
    g = board({20: down(13, "D"), 26: up(8, "H"), 27: up(5, "S")}, stock=[(9, "D")])
    assert not g.can_pickup(PYRAMID[20], 1)
    assert not g.double_click(PYRAMID[20])  # a King, but not free
    assert not g.attempt_move(PYRAMID[20], DISCARD)
    g.slots[PYRAMID[20]].cards = [down(8, "D")]
    assert not g.attempt_move(PYRAMID[27], PYRAMID[20])  # 5 and 8, face down
    assert not g.attempt_move(PYRAMID[20], PYRAMID[27])


def test_clearing_both_cards_below_turns_a_card_up():
    cards = {20: down(3, "S"), 26: up(8, "H"), 27: up(13, "C")}
    g = board(cards, waste=[up(5, "S")], stock=[(9, "D")])
    assert g.attempt_move(WASTE, PYRAMID[26])
    assert not g.top(PYRAMID[20]).face_up
    assert g.double_click(PYRAMID[27])
    assert g.top(PYRAMID[20]).face_up
    assert g.can_pickup(PYRAMID[20], 1)


def test_a_pyramid_card_pairs_with_the_waste_top_either_way():
    for src, dst in ((WASTE, PYRAMID[27]), (PYRAMID[27], WASTE)):
        g = board({27: up(8, "H")}, waste=[up(2, "C"), up(5, "S")], stock=[(9, "D")])
        assert g.attempt_move(src, dst)
        assert names(g, WASTE) == ["2C"]  # the card under it is on top again
        assert g.empty(PYRAMID[27])
        assert g.score == 2


def test_only_the_waste_top_plays_on_the_pyramid():
    # the 5S makes 13 with the 8H, but the 9C is on it
    g = board({27: up(8, "H")}, waste=[up(5, "S"), up(9, "C")], stock=[(9, "D")])
    assert not g.attempt_move(PYRAMID[27], WASTE)
    assert not g.can_pickup(WASTE, 2)
    assert names(g, WASTE) == ["5S", "9C"]


@pytest.mark.parametrize("how", ["double-click", "drop"])
def test_the_waste_top_pairs_with_the_card_under_it(how):
    g = board({27: up(9, "H")}, waste=[up(2, "C"), up(8, "H"), up(5, "S")], stock=[(9, "D")])
    assert g.double_click(WASTE) if how == "double-click" else g.attempt_move(WASTE, DISCARD)
    assert names(g, WASTE) == ["2C"]
    assert names(g, DISCARD) == ["5S", "8H"]
    assert (g.score, g.moves) == (2, 1)


def test_the_top_two_of_the_waste_have_to_make_13():
    g = board({27: up(9, "H")}, waste=[up(8, "H"), up(4, "S")], stock=[(9, "D")])
    assert not g.double_click(WASTE)
    assert not g.attempt_move(WASTE, DISCARD)
    g.slots[WASTE].cards = [up(8, "H")]
    assert not g.double_click(WASTE)  # a lone card has nothing under it


def test_the_stock_turns_one_card_at_a_time_and_is_never_redealt():
    g = board({27: up(9, "H")}, stock=[(2, "D"), (9, "S")])
    assert g.deal()
    assert g.cards(WASTE) == [up(9, "S")]
    assert g.status == "Stock: 1 left"
    assert g.click(STOCK)
    assert g.cards(WASTE) == [up(9, "S"), up(2, "D")]
    assert (g.score, g.moves) == (0, 2)
    assert not g.deal() and not g.click(STOCK)
    assert g.deal_blocked_reason() == "the stock is empty - nothing left to deal"
    assert not g.click(WASTE)
    assert g.cards(WASTE) == [up(9, "S"), up(2, "D")]


def test_a_pair_is_one_move_to_undo_and_redo():
    cards = {20: down(3, "S"), 26: up(8, "H"), 27: up(5, "C")}
    g = board(cards, stock=[(9, "D")])
    start = board_state(g)
    assert g.attempt_move(PYRAMID[27], PYRAMID[26])
    paired = board_state(g)
    assert g.top(PYRAMID[20]).face_up
    assert (g.score, g.moves) == (2, 1)
    assert g.undo()
    assert board_state(g) == start
    assert not g.top(PYRAMID[20]).face_up
    assert (g.score, g.moves) == (0, 0)
    assert not g.can_undo()
    assert g.redo()
    assert board_state(g) == paired
    assert (g.score, g.moves) == (2, 1)


def test_the_score_is_a_point_a_card_taken_off():
    cards = {25: up(13, "S"), 26: up(8, "H"), 27: up(5, "C")}
    g = board(cards, waste=[up(1, "D"), up(12, "S")], stock=[(9, "D")])
    scores = []
    for move in ((PYRAMID[25], DISCARD), (PYRAMID[26], PYRAMID[27]), (WASTE, DISCARD)):
        assert g.attempt_move(*move)
        scores.append(g.score)
    assert scores == [1, 3, 5]
    assert g.undo() and g.score == 3


# -- winning ----------------------------------------------------------------------

# deal 8 cleared card by card, as a search found it
CLEARED = (
    "f 27, 25 28, 21 23, d, d, 1 26, d, 1 20, 15 19, 14 24, 10 29, 1 18, d, d, d, 1 22, "
    "d, d, f 1, d, 1 30, d, d, d, d, 1 13, 9 17, 6 12, 8 16, d, f 1, d, 1 30, 1 5, d, d, "
    "1 11, d, 1 30, 1 7, d, 1 30, 1 3, d, f 1, d, 1 4, d, d, 1 30, d, 1 2"
)

# deal 0 won as AisleRiot counts it, with two cards down the right edge left
RIGHT_EDGE_LEFT = (
    "23 27, d, d, d, 1 24, d, d, d, d, 1 17, d, d, d, d, d, 1 29, d, 1 30, d, 1 30, d, d, "
    "1 26, 20 25, d, 1 28, f 21, d, 1 30, 1 18, 1 19, f 14, 13 22, f 16, 1 9, 1 12, 8 15, "
    "1 5, d, d, 1 11, d, f 1, d, 1 10, d, 1 30, 1 7, 1 6, d, 1 3"
)


def test_a_deal_played_through_clears_every_card():
    g = deal("pyramid", 8)
    moves = CLEARED.split(", ")
    play(g, ", ".join(moves[:-1]))
    assert not g.is_won()
    play(g, moves[-1])
    assert g.is_won() and not g.is_stuck()
    assert all(g.empty(sid) for sid in range(DISCARD))
    assert len(g.cards(DISCARD)) == 52
    assert (g.score, g.moves) == (52, 52)


def test_the_game_is_won_once_the_stock_the_waste_and_the_second_rows_left_card_go():
    # as AisleRiot has it: that card goes only once the 20 under it have, so
    # what's left can only be the peak and the cards down the right edge
    g = deal("pyramid", 0)
    moves = RIGHT_EDGE_LEFT.split(", ")
    play(g, ", ".join(moves[:-1]))
    assert not g.is_won()
    play(g, moves[-1])
    assert g.is_won() and not g.is_stuck()
    left = {i: str(g.top(p)) for i, p in enumerate(PYRAMID) if g.cards(p)}
    assert left == {0: "4H", 2: "9D"}
    assert (g.score, g.moves) == (50, 51)


def test_a_card_left_on_the_waste_or_the_stock_is_not_a_win():
    cards = {0: down(4, "H"), 1: up(13, "S"), 2: up(9, "D")}
    g = board(cards, waste=[up(9, "C")])
    assert g.double_click(PYRAMID[1])
    assert not g.is_won()
    g = board(cards, stock=[(9, "C")])
    assert g.double_click(PYRAMID[1])
    assert not g.is_won()
    g = board(cards)
    assert g.double_click(PYRAMID[1])
    assert g.is_won()


def test_a_won_game_counts_in_aisleriots_thirteen_record(keyfile, capsys):
    path = keyfile("[thirteen.scm]\nStatistic=2;5;300;400;\n")
    assert store.get_stat("pyramid") == {"wins": 2, "total": 5, "best": 300, "worst": 400}
    g = deal("pyramid", 8)
    commands = "\n".join(CLEARED.split(", ")) + "\nq\n"
    textmode.run_text(g, False, "pyramid", stream=io.StringIO(commands))
    assert "you won" in capsys.readouterr().out
    stat = ar.read_stat("thirteen.scm")
    assert (stat["wins"], stat["total"]) == (3, 6)
    assert "[thirteen.scm]" in path.read_text()


# -- stuck ------------------------------------------------------------------------


def test_nothing_to_take_off_and_an_empty_stock_is_stuck():
    g = board({26: up(9, "S"), 27: up(5, "H")}, waste=[up(3, "C")], stock=[(2, "D")])
    assert not g.is_stuck()
    assert g.hint()[:2] == (STOCK, STOCK)
    assert g.deal()
    assert g.is_stuck() and not g.is_won()
    assert g.hint() is None
    assert g.no_hint_reason() == "no moves left - undo to try another line"


def test_a_pair_on_the_waste_keeps_the_game_going():
    g = board({26: up(9, "S"), 27: up(5, "H")}, waste=[up(3, "C"), up(10, "D")])
    assert not g.is_stuck()
    assert g.hint()[:2] == (WASTE, DISCARD)


# -- the hint ---------------------------------------------------------------------


def test_the_hint_says_what_it_takes_off():
    g = board({27: up(5, "S")}, waste=[up(8, "H")], stock=[(9, "D")])
    assert g.hint()[2] == "Match 8H with 5S"
    g = board({27: up(13, "S")}, stock=[(9, "D")])
    assert g.hint()[2] == "Remove KS"
    g = board({27: up(9, "S")}, waste=[up(8, "H"), up(5, "C")], stock=[(9, "D")])
    assert g.hint()[2] == "Match 5C with the 8H under it"
    g.symbols = True
    assert g.hint()[2] == "Match 5♣ with the 8♥ under it"


def test_the_hint_takes_a_king_off_first():
    # the pair turns a card up, but the King pairs with nothing, so taking
    # it can't cost a thing
    cards = {20: down(3, "S"), 25: up(13, "H"), 26: up(8, "H"), 27: up(5, "C")}
    g = board(cards, stock=[(9, "D")])
    assert g.hint()[:2] == (PYRAMID[25], DISCARD)


def test_the_hint_takes_the_pair_that_turns_up_the_most_cards():
    # the 4S and 9H turn nothing up; the 8H and 5C turn up the 3S
    cards = {20: down(3, "S"), 23: up(4, "S"), 24: up(9, "H"), 26: up(8, "H"), 27: up(5, "C")}
    g = board(cards, stock=[(9, "D")])
    src, dst, _desc = g.hint()
    assert {src, dst} == {PYRAMID[26], PYRAMID[27]}


def test_the_hint_takes_pyramid_cards_before_the_wastes():
    # both pairs turn up nothing; the waste's cards come back as the ones
    # on them go, the pyramid's don't
    cards = {23: up(4, "S"), 24: up(9, "H"), 27: up(5, "C")}
    g = board(cards, waste=[up(8, "D")], stock=[(9, "D")])
    src, dst, _desc = g.hint()
    assert {src, dst} == {PYRAMID[23], PYRAMID[24]}


@pytest.mark.parametrize("seed", range(0, 60, 3))
def test_the_hint_only_ever_names_a_move_that_works(seed):
    g = deal("pyramid", seed)
    for _ in range(80):
        mv = g.hint_move()
        if mv is None:
            break
        src, dst, n = mv
        assert g.deal() if src == dst else g.attempt_move(src, dst, n), f"{mv} didn't work"
    assert g.hint_move() is None
    assert g.is_won() or g.is_stuck()


def test_autoplay_has_nothing_to_play():
    g = board({27: up(13, "S")}, waste=[up(8, "H"), up(5, "C")], stock=[(9, "D")])
    assert g.autoplay() == 0
    assert textmode.apply_text_command(g, "a") == (False, "nothing to autoplay")


def test_a_finishes_once_kings_and_the_waste_pairs_are_all_that_win_needs():
    # as in any game, once the stock is out and every card left is face up
    cards = {0: up(4, "H"), 1: up(13, "S"), 2: up(9, "D")}
    g = board(cards, waste=[up(8, "H"), up(5, "C")])
    assert g.finish_moves() == [(WASTE, DISCARD), (PYRAMID[1], DISCARD)]
    assert textmode.apply_text_command(g, "a") == (True, "autoplayed 3")
    assert g.is_won()
    assert (g.score, g.moves) == (3, 1)
    assert g.undo() and names(g, WASTE) == ["8H", "5C"]
    # a pair left in the pyramid isn't sent up, so there's no finish
    g = board({1: up(4, "H"), 5: up(9, "D")})
    assert g.finish_moves() is None and g.hint()[:2] == (PYRAMID[1], PYRAMID[5])


# -- saving it --------------------------------------------------------------------


def test_a_game_saved_part_way_resumes_where_it_was():
    g = deal("pyramid", 8)
    play(g, "f 27, 25 28, 21 23, d, d, 1 26")
    assert g.undo()
    assert saves.keep(g, 30)
    h, _seconds = saves.take("pyramid")
    assert board_state(h) == board_state(g)
    assert (h.score, h.moves) == (g.score, g.moves) == (5, 5)
    assert h.redo()
    assert h.score == 7 and len(h.cards(DISCARD)) == 7
    assert h.undo() and h.undo()
    assert len(h.cards(WASTE)) == 1
    assert h.score == 5
    # and it goes on from there as the game it was
    play(h, "d, 1 26")
    assert h.score == 7


# -- text mode --------------------------------------------------------------------


def test_text_mode_takes_off_pairs_and_kings_and_turns_the_stock():
    g = board({26: up(13, "S"), 27: up(8, "H")}, waste=[up(5, "C")], stock=[(9, "D")])
    assert textmode.apply_text_command(g, "f 28") == (True, "")
    assert textmode.apply_text_command(g, "1 29") == (True, "")
    assert textmode.apply_text_command(g, "d") == (True, "")
    assert names(g, WASTE) == ["9D"]
    assert (g.score, g.moves) == (3, 3)


@pytest.mark.parametrize(
    "cards, waste, stock, sid, says",
    [
        ({27: up(5, "H")}, [up(9, "S")], [], 29, "5H only goes in a pair making 13"),
        ({27: up(5, "H")}, [up(3, "D"), up(9, "S")], [], 1, "9S and 3D don't make 13"),
        ({27: up(5, "H")}, [up(9, "S")], [], 1, "9S only goes in a pair making 13"),
        (
            {20: down(13, "H"), 27: up(5, "H")},
            [],
            [],
            22,
            "the face-down card on #22 isn't free yet",
        ),
        ({27: up(5, "H")}, [up(9, "S")], [], 28, "nothing on #28 to take off"),
        ({27: up(5, "H")}, [], [(9, "S")], 1, "nothing on wst#1 to take off"),
        ({27: up(5, "H")}, [up(9, "S")], [], 30, "nothing on fnd#30 to take off"),
        ({27: up(5, "H")}, [up(9, "S")], [], 0, "nothing on stk#0 to take off"),
        (
            {27: up(5, "H")},
            [up(9, "S")],
            [(4, "D")],
            0,
            "a card on the stock plays once it's turned onto the waste",
        ),
    ],
)
def test_an_f_that_takes_nothing_off_says_why(cards, waste, stock, sid, says):
    g = board(cards, waste=waste, stock=stock)
    before = g.serialize()
    assert textmode.apply_text_command(g, f"f {sid}") == (False, says)
    assert g.serialize() == before


BOARD = """\
=== Pyramid ===
stk#0       wst#1    #2            fnd#30
[###] [ 6S] [10C] [###]             [ KS]
 (21)

                  #3    #4
               [###] [###]

               #5    #6    #7
            [###] [###] [###]

            #8    #9   #10   #11
         [###] [###] [###] [###]

        #12   #13   #14   #15   #16
      [###] [###] [###] [###] [###]

     #17   #18   #19   #20   #21   #22
   [###] [###] [###] [###] [###] [###]

  #23   #24   #25   #26         #28   #29
[ QC] [ 2D] [10D] [ 7C]       [ 5S] [ 8S]

score=1 moves=4 | Stock: 21 left"""


def test_text_mode_draws_the_pyramid_as_the_board_does():
    # the stock and the waste's top two top left, the cards taken off top
    # right with the stock's count under it, and a card gone from the
    # pyramid leaving a gap
    g = deal("pyramid", 1)
    assert textmode.apply_text_command(g, "?") == (
        True,
        "Hint: Remove K♠  (#27 -> fnd#30, type: 27 30)",
    )
    play(g, "f 27, d, d, d")
    assert textmode.render_text(g, symbols=False) == BOARD
    board = textmode.render_text(deal("pyramid", 1), symbols=False)
    assert board.splitlines()[1:5] == [
        "stk#0 wst#1          #2            fnd#30",
        "[###] [   ]       [###]             [   ]",
        " (24)",
        "",
    ]
