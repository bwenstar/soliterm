"""Bakers Dozen: thirteen columns and no stock, with Kings sent to the bottom."""

from __future__ import annotations

from ..cards import ACE, KING
from ..gamedef import GameDef


class BakersDozen(GameDef):
    key = "bakersdozen"
    name = "Bakers Dozen"
    blurb = "No stock. Thirteen columns; build foundations up, tableau down by rank."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(13)]
        for _ in range(4):
            for t in self.tableau:
                g.deal_from_deck(t, 1, face_up=True)
        # move any Kings to the bottom of their column (classic Bakers Dozen)
        for t in self.tableau:
            pile = g.cards(t)
            kings = [c for c in pile if c.rank == KING]
            others = [c for c in pile if c.rank != KING]
            g.slots[t].cards = kings + others
        g.update_status()

    def can_pickup(self, g, sid, n):
        if g.kind(sid) == "tableau":
            return n == 1
        return False

    def tableau_adjacent(self, upper, lower):
        return lower.rank == upper.rank - 1     # build down by rank, any suit

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        c = cards[0]
        if k == "foundation":
            top = g.top(dst)
            return (c.rank == ACE) if top is None else self.same_suit_up(top, c)
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return False               # empty columns cannot be refilled
            return top.rank == c.rank + 1  # build down by rank, any suit
        return False

    def on_double_click(self, g, sid):
        if g.kind(sid) != "tableau":
            return False
        c = g.top(sid)
        if c is None:
            return False
        fid = self.foundation_for(g, c)
        if fid is None:
            return False
        g.slots[fid].cards.append(g.slots[sid].cards.pop())
        g.score += 1
        return True

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1
        elif g.kind(src) == "foundation":
            g.score -= 1

    def is_won(self, g):
        return all(len(g.cards(f)) == 13 for f in self.foundations)

    def can_deal(self, g):
        return False

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau:
                c = g.top(sid)
                if c and self.foundation_for(g, c) is not None:
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(f)) for f in self.foundations)
        return f"Foundations: {done}/52"

    # hint(): generic progress-based engine hint (see Solitaire.hint).
