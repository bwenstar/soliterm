"""soliterm.tui.cascade - the cards bouncing off the board after a win.

The old Windows Solitaire way: one card at a time leaves a foundation,
falls, bounces along the bottom of the screen and leaves a trail, since
nothing is erased. Cascade only does the sums. step() says what to draw
for one frame and the App draws it, so a test can run a whole cascade
without a terminal.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Optional

from ..engine.cards import Card

FRAME_MS = 40  # one frame, and how long a key has to stop it
MAX_FRAMES = 150  # six seconds at most
MAX_S = MAX_FRAMES * FRAME_MS / 1000  # and no longer however slow the terminal
AT_ONCE = 8  # cards in the air together
LAUNCH_EVERY = 4  # frames between one card setting off and the next
BOUNCE = 0.75  # how much of its speed a card keeps off the floor

# runtime aliases, so no X | None before Python 3.10
Pile = tuple[int, int, list[Card]]  # the top card's (y, x), and the cards, bottom first
Draw = tuple[int, int, Optional[Card]]  # a card, or None for an empty slot, at (y, x)


class Flyer:
    """A card in the air."""

    __slots__ = ("at", "card", "vx", "vy", "x", "y")

    def __init__(self, y: int, x: int, vy: float, vx: float, card: Card):
        self.y, self.x = float(y), float(x)
        self.vy, self.vx = vy, vx
        self.card = card
        self.at = (y, x)  # the cell it was last drawn at


class Cascade:
    """The cards of piles, the top one first, flying off a height by width
    screen one after another. Cards are card_h rows by card_w columns, and
    the same seed sends them the same way."""

    def __init__(
        self,
        piles: Sequence[Pile],
        height: int,
        width: int,
        card_h: int,
        card_w: int,
        seed: int | None = None,
    ):
        self.piles = [(y, x, list(cards)) for y, x, cards in piles]
        self.width, self.card_w = width, card_w
        self.floor = height - card_h  # a card's top row when it sits on the bottom
        self.gravity = height / 200  # rows per frame, per frame
        self.speed = width / 60  # columns per frame, give or take 40%
        self.lift = height / 40  # the most a card jumps up as it leaves
        self.rng = random.Random(seed)
        self.flying: list[Flyer] = []
        self.launched: list[Card] = []
        self.frame = 0
        self.turn = 0  # the pile the next card comes from

    @property
    def done(self) -> bool:
        return self.frame >= MAX_FRAMES or (
            not self.flying and not any(cards for _, _, cards in self.piles)
        )

    def step(self) -> list[Draw]:
        """Move on one frame. Returns what to draw, in order: a pile a card
        just left (showing the card under it), then each card that moved to
        a new cell."""
        out: list[Draw] = []
        if self.frame % LAUNCH_EVERY == 0 and len(self.flying) < AT_ONCE:
            out.extend(self._launch())
        g = self.gravity
        for f in self.flying:
            f.vy += g
            f.y += f.vy
            f.x += f.vx
            if f.y >= self.floor:
                f.y = self.floor
                f.vy = -f.vy * BOUNCE if f.vy > g else 0.0
            at = (round(f.y), round(f.x))
            if at != f.at:
                f.at = at
                out.append((at[0], at[1], f.card))
        self.flying = [f for f in self.flying if -self.card_w < f.x < self.width]
        self.frame += 1
        return out

    def _launch(self) -> list[Draw]:
        """Send the top card of the next pile that has one on its way,
        taking the piles in turn: KS, KH, KD, KC, QS and so on."""
        n = len(self.piles)
        for i in range(n):
            y, x, cards = self.piles[(self.turn + i) % n]
            if cards:
                self.turn = (self.turn + i + 1) % n
                card = cards.pop()
                self.launched.append(card)
                vx = self.speed * self.rng.uniform(0.6, 1.4) * self.rng.choice((-1, 1))
                vy = -self.rng.uniform(0, self.lift)
                self.flying.append(Flyer(y, x, vy, vx, card))
                return [(y, x, cards[-1] if cards else None)]
        return []
