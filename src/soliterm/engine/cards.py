"""Cards and decks: Card, make_deck and the suit and rank constants."""

from __future__ import annotations

from dataclasses import dataclass

SUITS = "SHDC"  # Spades, Hearts, Diamonds, Clubs
SUIT_SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RANK_NAME = {1: "A", 11: "J", 12: "Q", 13: "K"}
RED_SUITS = {"H", "D"}
ACE, JACK, QUEEN, KING = 1, 11, 12, 13


@dataclass(frozen=True)
class Card:
    rank: int  # 1 (Ace) .. 13 (King)
    suit: str  # one of SUITS
    face_up: bool = False

    @property
    def is_red(self) -> bool:
        return self.suit in RED_SUITS

    @property
    def is_black(self) -> bool:
        return self.suit not in RED_SUITS

    @property
    def color(self) -> str:
        return "R" if self.is_red else "B"

    @property
    def rank_str(self) -> str:
        return RANK_NAME.get(self.rank, str(self.rank))

    def up(self, face_up: bool = True) -> Card:
        return Card(self.rank, self.suit, face_up)

    def label(self, symbols: bool = True) -> str:
        suit = SUIT_SYMBOL[self.suit] if symbols else self.suit
        return f"{self.rank_str}{suit}"

    def __str__(self) -> str:
        return self.label(symbols=False)


def make_deck(decks: int = 1, suits: str = SUITS) -> list[Card]:
    """A deck of `decks` copies over the given suits (all face down)."""
    out: list[Card] = []
    for _ in range(decks):
        for suit in suits:
            for rank in range(1, 14):
                out.append(Card(rank, suit))
    return out
