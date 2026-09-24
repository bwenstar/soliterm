"""The shuffle behind every deal, checked against published reference output
so a deal number deals the same hand on any Python."""

import pytest

from soliterm.engine import GAME_ORDER
from soliterm.engine.rng import Pcg32, fisher_yates, stream_of


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
