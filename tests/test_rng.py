"""The shuffle behind every deal, checked against published reference output
so a deal number deals the same hand on any Python."""

import pytest

from soliterm.engine import GAME_ORDER, make_deck
from soliterm.engine.rng import Pcg32, fisher_yates, microsoft_deal, stream_of


def test_pcg32_matches_the_reference_output():
    # round 1 of pcg32-demo in pcg-c-basic
    gen = Pcg32(42, 54)
    assert [gen.next32() for _ in range(6)] == [
        0xA15C02B7,
        0x7B47F409,
        0xBA1D3330,
        0x83D2F293,
        0xBFA4784B,
        0xCBED606E,
    ]


def test_below_matches_the_reference_coins_and_dice():
    # the same demo goes on to flip coins and roll dice with the same generator
    gen = Pcg32(42, 54)
    for _ in range(6):
        gen.next32()
    coins = "".join("H" if gen.below(2) else "T" for _ in range(65))
    assert coins == "HHTTTHTHHHTHTTTHHHHHTTTHHHTHTHTHTTHTTTHHHHHHTTTTHHTTTTTHTTTTTTTHT"
    dice = " ".join(str(gen.below(6) + 1) for _ in range(33))
    assert dice == "3 4 1 1 2 2 3 2 4 3 2 4 3 3 5 2 3 1 3 1 5 1 4 1 5 6 4 6 6 2 6 3 3"


@pytest.mark.parametrize("bound", [0, -1, 2**32 + 1])
def test_below_refuses_a_bound_it_cannot_give(bound):
    with pytest.raises(ValueError, match="bound must be 1 to 2\\*\\*32"):
        Pcg32(1).below(bound)


def test_below_1_and_below_2_to_the_32():
    gen = Pcg32(7, 3)
    assert all(gen.below(1) == 0 for _ in range(20))
    twin = Pcg32(7, 3)
    for _ in range(20):
        twin.next32()
    assert gen.below(2**32) == twin.next32()


def test_below_has_no_bias_at_a_small_bound():
    gen = Pcg32(2024, 9)
    counts = [0] * 3
    for _ in range(30000):
        counts[gen.below(3)] += 1
    assert all(9700 < c < 10300 for c in counts), counts


def test_fisher_yates_matches_its_vector():
    items = list(range(10))
    fisher_yates(items, Pcg32(1, 2))
    assert items == [3, 5, 4, 0, 1, 2, 6, 9, 8, 7]


def test_fisher_yates_keeps_every_item():
    items = list(range(104))
    fisher_yates(items, Pcg32(5, 6))
    assert items != list(range(104))
    assert sorted(items) == list(range(104))


@pytest.mark.parametrize("items", [[], ["x"]])
def test_fisher_yates_leaves_short_lists_and_the_generator_alone(items):
    gen = Pcg32(3, 4)
    state = gen.state
    fisher_yates(items, gen)
    assert gen.state == state
    assert items in ([], ["x"])


def test_stream_of_is_fnv1a_64():
    assert stream_of("") == 0xCBF29CE484222325
    assert stream_of("a") == 0xAF63DC4C8601EC8C
    assert stream_of("klondike") == 0x90338F14C91FE070


def test_every_game_has_a_stream_of_its_own():
    assert len({stream_of(key) for key in GAME_ORDER}) == len(GAME_ORDER)


# Microsoft FreeCell's deals as published, read across 8 cards to a row
# (T is a ten)
MICROSOFT = {
    1: "JD 2D 9H JC 5D 7H 7C 5H / KD KC 9S 5S AD QC KH 3H / 2S KS 9D QD JS AS AH 3C / "
    "4C 5C TS QH 4H AC 4D 7S / 3S TD 4S TH 8H 2C JH 7D / 6D 8S 8D QS 6C 3D 8C TC / "
    "6S 9C 2H 6H",
    617: "7D AD 5C 3S 5S 8C 2D AH / TD 7S QD AC 6D 8H AS KH / TH QC 3H 9D 6S 8D 3D TC / "
    "KD 5H 9S 3C 8S 7H 4D JS / 4C QS 9C 9H 7C 6H 2C 2S / 4S TS 2H 5D JC 6C JH QH / "
    "JD KS KC 4H",
    11982: "AH AS 4H AC 2D 6S TS JS / 3D 3H QS QC 8S 7H AD KS / KD 6H 5S 4D 9H JH 9S 3C / "
    "JC 5D 5C 8C 9D TD KH 7C / 6C 2C TH QH 6D TC 4S 7S / JD 7D 8H 9C 2H QD 4C 5H / "
    "KC 8D 2S 3S",
    1000000: "2D 6H 6S TH JC 3C 4D TD / 9C 3D 7D 7C QC AC 2S 4C / KD 5H 5D QH JH 6C 9H KS / "
    "JD 7S QD 8D 2H AD 5C 8C / 3H 4S 3S KC KH 9D 7H 8S / TC AS 6D 8H 2C QS 5S JS / "
    "TS AH 9S 4H",
}


def microsoft_text(card):
    return "A23456789TJQK"[card.rank - 1] + card.suit


@pytest.mark.parametrize("number", sorted(MICROSOFT))
def test_microsoft_deals_match_the_published_layouts(number):
    dealt = [microsoft_text(c) for c in microsoft_deal(number)]
    rows = [" ".join(dealt[i : i + 8]) for i in range(0, 52, 8)]
    assert " / ".join(rows) == MICROSOFT[number]


@pytest.mark.parametrize("number", [0, 1, 2**31 - 1])
def test_a_microsoft_deal_has_each_card_once(number):
    dealt = microsoft_deal(number)
    assert sorted(dealt, key=str) == sorted(make_deck(), key=str)
