"""Helpers shared by the test modules (import them with `from helpers import`)."""

import curses
from collections import Counter

from soliterm import engine

# Cards in a full deal of each game.
EXPECTED_CARDS = {
    "klondike": 52,
    "spider": 104,
    "freecell": 52,
    "eightoff": 52,
    "golf": 52,
    "yukon": 52,
    "bakersdozen": 52,
    "fortythieves": 104,
    "canfield": 52,
}


def deal(key, seed=1, **options):
    """A seeded game; options go in as keywords, e.g. deal("spider", suits=2)."""
    return engine.new_solitaire(key, seed=seed, options=options or None)


def card_count(g):
    return sum(len(s.cards) for s in g.slots)


def card_multiset(g):
    """Every card on the board as a Counter of (rank, suit)."""
    return Counter((c.rank, c.suit) for s in g.slots for c in s.cards)


def clear_board(g):
    """Empty every slot, for building a contrived position by hand."""
    for s in g.slots:
        s.cards = []


def random_op(g, rng):
    """Make one random player action on g.

    Mostly moves (sane and silly pickup sizes alike), plus deals, autoplay,
    clicks, undo and redo, so random play pokes every code path.
    """
    ns = len(g.slots)
    r = rng.random()
    if r < 0.16 and g.can_deal():
        g.deal()
    elif r < 0.28:
        g.autoplay()
    elif r < 0.38:
        g.undo()
    elif r < 0.45:
        g.redo()
    elif r < 0.54:
        g.double_click(rng.randrange(ns))
    elif r < 0.61:
        g.click(rng.randrange(ns))
    else:
        g.attempt_move(rng.randrange(ns), rng.randrange(ns), rng.choice([None, 1, 2, 3, 5, 13]))


def board_state(g):
    """The cards on the board, slot by slot, ignoring score and counters."""
    return tuple(tuple(s.cards) for s in g.slots)


def stalled_klondike(blocked=False):
    """Klondike, every card face up, that safe autoplay leaves with one card
    up: 5H and 5D wait on the black fours, and 4C is under 5H. Sent up in
    any order that will go, every card still gets home. Blocked, 5C sits
    on the 4C it needs, so they can't."""
    g = deal("klondike", 1)
    fids, t = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    for f, suit, top in zip(fids, "SHDC", [4, 4, 4, 3]):
        g.slots[f].cards = [engine.Card(r, suit, True) for r in range(1, top + 1)]
    lowest = {"S": 5, "H": 5 if blocked else 6, "D": 5, "C": 6 if blocked else 5}
    for col, suit in zip(t[1:], "SHDC"):
        g.slots[col].cards = [engine.Card(r, suit, True) for r in range(13, lowest[suit] - 1, -1)]
    g.slots[t[0]].cards = [engine.Card(4, "C", True), engine.Card(5, "C" if blocked else "H", True)]
    return g


def legal_walk(g, rng, steps, allow=None):
    """Random play that mostly makes legal moves; yields after every step.

    allow(g, (src, dst, n)) can veto moves the caller wants to stay away from.
    """
    for _ in range(steps):
        r = rng.random()
        if r < 0.10 and g.can_deal():
            g.deal()
        elif r < 0.16:
            g.undo()
        elif r < 0.20:
            g.redo()
        elif r < 0.26:
            g.autoplay()
        else:
            moves = [m for m in g.legal_moves() if allow is None or allow(g, m)]
            if moves:
                g.attempt_move(*rng.choice(moves))
            elif g.can_deal():
                g.deal()
        yield


class FakeScr:
    """Just enough of a curses window for BoardUI.

    Keeps a character grid so a test can read the screen back as text.
    """

    encoding = "utf-8"  # what curses took from the locale

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

    def timeout(self, ms):
        pass

    def addnstr(self, y, x, text, n, attr=0):
        try:
            text.encode(self.encoding)
        except UnicodeEncodeError:
            # as curses does: the whole string is refused, not just the glyph
            raise curses.error("addnwstr() returned ERR") from None
        if not 0 <= y < self.h:
            return
        for i, ch in enumerate(text[:n]):
            if 0 <= x + i < self.w:
                self.grid[y][x + i] = ch

    def getch(self):
        return -1

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)
