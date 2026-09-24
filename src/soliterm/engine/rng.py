"""soliterm.engine.rng - the shuffles behind every deal.

Python's random module only promises the same random() numbers for a seed;
shuffle() and randrange() have changed between versions. A deal number has
to deal the same hand on every Python, so the engine shuffles with its own
generator: PCG32 (pcg-random.org, pcg32_random_r in pcg-c-basic) and a
Fisher-Yates shuffle. FreeCell deals with the Microsoft FreeCell
generator instead, so its deal numbers are the ones FreeCell players know.
"""

from __future__ import annotations

from collections.abc import MutableSequence
from typing import TypeVar

from .cards import Card

T = TypeVar("T")

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF
_MULT = 6364136223846793005


class Pcg32:
    """PCG32 (XSH RR), seeded as pcg32_srandom_r(seed, stream) seeds it."""

    def __init__(self, seed: int, stream: int = 0) -> None:
        self.inc = ((stream << 1) | 1) & _MASK64
        self.state = 0
        self.next32()
        self.state = (self.state + seed) & _MASK64
        self.next32()

    def next32(self) -> int:
        """The next number from 0 to 2**32 - 1."""
        old = self.state
        self.state = (old * _MULT + self.inc) & _MASK64
        xorshifted = (((old >> 18) ^ old) >> 27) & _MASK32
        rot = old >> 59
        return ((xorshifted >> rot) | (xorshifted << (-rot & 31))) & _MASK32

    def below(self, bound: int) -> int:
        """A number from 0 to bound - 1, with no bias (pcg32_boundedrand_r)."""
        if not 0 < bound <= 1 << 32:
            raise ValueError(f"bound must be 1 to 2**32, not {bound}")
        threshold = (1 << 32) % bound
        while True:
            r = self.next32()
            if r >= threshold:
                return r % bound


def fisher_yates(items: MutableSequence[T], gen: Pcg32) -> None:
    """Shuffle items in place, swapping from the end down."""
    for i in range(len(items) - 1, 0, -1):
        j = gen.below(i + 1)
        items[i], items[j] = items[j], items[i]


def stream_of(name: str) -> int:
    """A PCG stream for a game: the 64-bit FNV-1a hash of its key, so deal
    5 of Klondike and deal 5 of Yukon are not the same shuffle."""
    h = 0xCBF29CE484222325
    for byte in name.encode("utf-8"):
        h = ((h ^ byte) * 0x100000001B3) & _MASK64
    return h


def microsoft_deal(number: int) -> list[Card]:
    """Microsoft FreeCell's deal `number`, in the order the cards go down:
    the first card to column 1, the ninth back to column 1 again."""
    deck = [Card(rank, suit) for rank in range(1, 14) for suit in "CDHS"]
    state = number
    dealt: list[Card] = []
    while deck:
        state = (state * 214013 + 2531011) & 0x7FFFFFFF
        i = (state >> 16) % len(deck)
        deck[i], deck[-1] = deck[-1], deck[i]
        dealt.append(deck.pop())
    return dealt
