"""Forty Thieves: two decks and ten columns, building down by suit."""

from __future__ import annotations

from ..cards import ACE, make_deck
from ..gamedef import GameDef


class FortyThieves(GameDef):
    key = "fortythieves"
    name = "Forty Thieves"
    blurb = "Two decks, ten columns. Build foundations up by suit; tableau down by suit."

    def deal(self, g):
        g.reset_slots()
        g.deck = make_deck(2)
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste", "right")
        self.foundations = [g.add_slot("foundation") for _ in range(8)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(10)]
        for _ in range(4):
            for t in self.tableau:
                g.deal_from_deck(t, 1, face_up=True)
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def can_pickup(self, g, sid, n):
        k = g.kind(sid)
        if k == "waste":
            return n == 1
        if k == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n:]
            for a, b in zip(run, run[1:]):
                if not (a.suit == b.suit and b.rank == a.rank - 1):
                    return False
            return True
        return False

    def tableau_adjacent(self, upper, lower):
        return upper.suit == lower.suit and lower.rank == upper.rank - 1

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        c = cards[0]
        if k == "foundation":
            if len(cards) != 1:
                return False
            top = g.top(dst)
            return (c.rank == ACE) if top is None else self.same_suit_up(top, c)
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return True
            return top.suit == c.suit and top.rank == c.rank + 1
        return False

    def on_click(self, g, sid):
        if sid == self.stock and not g.empty(self.stock):
            g.slots[self.waste].cards.append(g.slots[self.stock].cards.pop().up(True))
            return True
        return False

    def on_double_click(self, g, sid):
        if g.kind(sid) == "foundation":
            # as in AisleRiot: send up every card that can go, safe or not
            return self._send_up(g, safe_only=False) > 0
        if g.kind(sid) not in ("tableau", "waste"):
            return False
        c = g.top(sid)
        if c is None:
            return False
        fid = self.foundation_for(g, c)
        if fid is not None:
            g.slots[fid].cards.append(g.slots[sid].cards.pop())
            g.score += 1
            return True
        dst = self._tableau_place(g, sid, c)
        if dst is None:
            return False
        g.slots[dst].cards.append(g.slots[sid].cards.pop())
        return True

    def _tableau_place(self, g, sid, c):
        """Where a double click puts a card that can't go up, as AisleRiot
        picks it: the first column it builds on, else an empty one."""
        for t in self.tableau:
            if t != sid and not g.empty(t) and self.can_drop(g, sid, [c], t):
                return t
        for t in self.tableau:
            if g.empty(t):
                return t
        return None

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1
        elif g.kind(src) == "foundation":
            g.score -= 1

    def is_won(self, g):
        return sum(len(g.cards(f)) for f in self.foundations) == 104

    def can_deal(self, g):
        return not g.empty(self.stock)

    def autoplay(self, g):
        return self._send_up(g, safe_only=True)

    def _send_up(self, g, safe_only):
        """Move cards up to the foundations until none will go, and return
        how many went. With safe_only, only those autoplay counts as safe."""
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau + [self.waste]:
                c = g.top(sid)
                if (c and self.foundation_for(g, c) is not None
                        and (not safe_only or self.safe_to_autoplay(g, c))):
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(f)) for f in self.foundations)
        return f"Stock: {len(g.cards(self.stock))}  Foundations: {done}/104"

    # hint(): generic progress-based engine hint (see Solitaire.hint).
