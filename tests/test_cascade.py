"""The cascade after a win does only the sums, so a whole one runs here
without a terminal: where each card goes, frame by frame, and when it ends."""

from soliterm.engine import Card
from soliterm.tui import cascade
from soliterm.tui.cascade import MAX_FRAMES, Cascade

# four Klondike foundations on a 40x120 screen, with cards 7 wide and 4 high
TOPS = [(4, 20), (4, 29), (4, 38), (4, 47)]


def suit(s, top=13):
    return [Card(r, s, True) for r in range(1, top + 1)]


def four_suits(seed=1, h=40, w=120):
    piles = [(y, x, suit(s)) for (y, x), s in zip(TOPS, "SHDC")]
    return Cascade(piles, h, w, 4, 7, seed=seed)


def run(c):
    """Every frame's draws until the cascade is done."""
    frames = []
    while not c.done:
        frames.append(c.step())
    return frames


def test_a_deal_bounces_the_same_way_every_time():
    assert run(four_suits(seed=7)) == run(four_suits(seed=7))
    assert run(four_suits(seed=7)) != run(four_suits(seed=8))


def test_cards_leave_the_piles_in_turn():
    c = Cascade([(4, 20, suit("S")), (4, 29, suit("H"))], 40, 120, 4, 7, seed=1)
    run(c)
    assert [str(card) for card in c.launched[:4]] == ["KS", "KH", "QS", "QH"]


def test_a_card_leaving_shows_the_one_under_it():
    c = four_suits()
    assert c.step()[0] == (4, 20, Card(12, "S", True))


def test_a_pile_left_empty_draws_an_empty_slot():
    c = Cascade([(4, 20, [Card(13, "S", True)])], 40, 120, 4, 7, seed=1)
    assert c.step()[0] == (4, 20, None)


def test_no_card_falls_through_the_floor():
    for h, w in [(40, 120), (24, 80)]:
        c = four_suits(h=h, w=w)
        draws = [d for frame in run(c) for d in frame]
        assert draws and all(y <= c.floor == h - 4 for y, _, _ in draws)


def test_cascade_frames_are_bounded():
    c = four_suits()
    frames = run(c)
    assert len(frames) == MAX_FRAMES
    # and the cards take turns in the air, so a frame never draws many
    assert max(len(frame) for frame in frames) <= cascade.AT_ONCE + 1


def test_a_small_board_stops_when_the_cards_are_gone():
    c = Cascade([(4, 20, [Card(13, "S", True)]), (4, 29, [Card(13, "H", True)])], 40, 120, 4, 7)
    frames = run(c)
    assert len(frames) < MAX_FRAMES
    assert not c.flying and len(c.launched) == 2


def test_nothing_is_drawn_where_a_card_already_is():
    last = {}
    for frame in run(four_suits()):
        for y, x, card in frame:
            if card is not None:
                assert last.get(card) != (y, x)
                last[card] = (y, x)
