"""Helpers shared by the test modules (import them with `from helpers import`)."""

from collections import Counter

import aisle

# Cards in a full deal of each game.
EXPECTED_CARDS = {"klondike": 52, "spider": 104, "freecell": 52, "eightoff": 52,
                  "golf": 52, "yukon": 52, "bakersdozen": 52, "fortythieves": 104,
                  "canfield": 52}


def deal(key, seed=1, **options):
    """A seeded game; options go in as keywords, e.g. deal("spider", suits=2)."""
    return aisle.new_solitaire(key, seed=seed, options=options or None)


def card_count(g):
    return sum(len(s.cards) for s in g.slots)


def card_multiset(g):
    """Every card on the board as a Counter of (rank, suit)."""
    return Counter((c.rank, c.suit) for s in g.slots for c in s.cards)


def clear_board(g):
    """Empty every slot, for building a contrived position by hand."""
    for s in g.slots:
        s.cards = []


class FakeScr:
    """Just enough of a curses window for BoardUI.

    Keeps a character grid so a test can read the screen back as text.
    """

    def __init__(self, h=40, w=140):
        self.h, self.w = h, w
        self.erase()

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        self.grid = [[" "] * self.w for _ in range(self.h)]

    def refresh(self):
        pass

    def keypad(self, flag):
        pass

    def addnstr(self, y, x, text, n, attr=0):
        if not 0 <= y < self.h:
            return
        for i, ch in enumerate(text[:n]):
            if 0 <= x + i < self.w:
                self.grid[y][x + i] = ch

    def getch(self):
        return -1

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)
