"""Yukon: Klondike without a stock, where any face-up group can move."""

from __future__ import annotations

from ..cards import ACE, KING
from ..gamedef import GameDef


class Yukon(GameDef):
    key = "yukon"
    name = "Yukon"
    blurb = "Like Klondike, but move any group of cards regardless of order."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(7)]
        # column 0 gets 1 face-up; columns 1..6 get 1 face-down base + extra
        g.deal_from_deck(self.tableau[0], 1, face_up=True)
        for col in range(1, 7):
            for _ in range(col):
                g.deal_from_deck(self.tableau[col], 1, face_up=False)
        # then five face-up cards onto columns 1..6
        for _ in range(5):
            for col in range(1, 7):
                g.deal_from_deck(self.tableau[col], 1, face_up=True)
        for col in range(1, 7):
            g.flip_top(self.tableau[col])
        g.update_status()

    def can_pickup(self, g, sid, n):
        if g.kind(sid) != "tableau":
            return False
        run = g.cards(sid)[len(g.cards(sid)) - n :]
        return all(c.face_up for c in run)  # any face-up group, any order

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        if k == "foundation":
            if len(cards) != 1:
                return False
            top = g.top(dst)
            return (cards[0].rank == ACE) if top is None else self.same_suit_up(top, cards[0])
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return cards[0].rank == KING
            return self.alt_color_down(top, cards[0])
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
        g.flip_top(sid)
        g.score += 1
        return True

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1
        elif g.kind(src) == "foundation":
            g.score -= 1
        if g.kind(src) == "tableau":
            g.flip_top(src)

    def is_won(self, g):
        return sum(len(g.cards(s)) for s in self.foundations) == 52

    def can_deal(self, g):
        return False

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau:
                c = g.top(sid)
                if c and self.foundation_for(g, c) is not None and self.safe_to_autoplay(g, c):
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.flip_top(sid)
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(s)) for s in self.foundations)
        return f"Foundations: {done}/52"

    # hint(): generic progress-based engine hint (see Solitaire.hint).
