"""Canfield: a reserve of 13, deal three, and a foundation base that wraps K to A."""

from __future__ import annotations

from ..cards import KING, RANK_NAME
from ..gamedef import GameDef


class Canfield(GameDef):
    key = "canfield"
    name = "Canfield"
    blurb = "Reserve of 13, deal three at a time. Foundations and tableau wrap K->A."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste", "right")
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.reserve = g.add_slot("reserve", "down")
        self.tableau = [g.add_slot("tableau", "down") for _ in range(4)]
        # reserve: 13 cards, top face up
        for i in range(13):
            g.deal_from_deck(self.reserve, 1, face_up=(i == 12))
        # one card to each tableau column, face up
        for t in self.tableau:
            g.deal_from_deck(t, 1, face_up=True)
        # one card to the first foundation sets the base rank
        g.deal_from_deck(self.foundations[0], 1, face_up=True)
        g.base_val = g.top(self.foundations[0]).rank
        g.score = 1                        # that card counts like any other
        # rest to stock
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def _f_up(self, top_rank, card_rank):
        return card_rank == (top_rank % 13) + 1

    def _t_down_altcolor(self, top, card):
        # build down with wrap (Ace below 2; King below Ace)
        nextrank = top.rank - 1 if top.rank > 1 else KING
        return top.is_red != card.is_red and card.rank == nextrank

    def tableau_adjacent(self, upper, lower):
        return self._t_down_altcolor(upper, lower)

    def can_pickup(self, g, sid, n):
        k = g.kind(sid)
        if k in ("waste", "reserve"):
            return n == 1
        if k == "foundation":
            # still in play, bar the base card each foundation starts from
            top = g.top(sid)
            return n == 1 and top is not None and top.rank != g.base_val
        if k == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n:]
            return all(self._t_down_altcolor(a, b) for a, b in zip(run, run[1:]))
        return False

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        c = cards[0]
        if k == "foundation":
            if len(cards) != 1:
                return False
            top = g.top(dst)
            if top is None:
                return c.rank == g.base_val
            return top.suit == c.suit and self._f_up(top.rank, c.rank)
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return True               # any card may start an empty column
            return self._t_down_altcolor(top, c)
        return False

    def on_click(self, g, sid):
        if sid != self.stock:
            return False
        if g.empty(self.stock):
            waste = g.slots[self.waste].cards
            if not waste:
                return False
            g.slots[self.stock].cards = [c.up(False) for c in reversed(waste)]
            g.slots[self.waste].cards = []
            g.redeals_done += 1
            return True
        for _ in range(min(3, len(g.cards(self.stock)))):
            g.slots[self.waste].cards.append(g.slots[self.stock].cards.pop().up(True))
        return True

    def on_double_click(self, g, sid):
        if g.kind(sid) not in ("tableau", "waste", "reserve"):
            return False
        c = g.top(sid)
        if c is None:
            return False
        fid = self._foundation_for(g, c)
        if fid is None:
            return False
        g.slots[fid].cards.append(g.slots[sid].cards.pop())
        g.score += 1
        self._refill(g)
        return True

    def _foundation_for(self, g, card):
        for fid in self.foundations:
            top = g.top(fid)
            if top is None:
                if card.rank == g.base_val:
                    return fid
            elif top.suit == card.suit and self._f_up(top.rank, card.rank):
                return fid
        return None

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1
        elif g.kind(src) == "foundation":
            g.score -= 1
        self._refill(g)

    def _refill(self, g):
        # an empty tableau column is auto-filled from the reserve (Canfield rule)
        for t in self.tableau:
            if g.empty(t) and not g.empty(self.reserve):
                g.slots[t].cards.append(g.slots[self.reserve].cards.pop())
                g.flip_top(t)
        # the reserve's top is always face up. Every reserve removal (a play to
        # foundation/tableau, an autoplay, or the refill above) routes through
        # here, so re-flipping the new top here keeps the whole pile consistent.
        g.flip_top(self.reserve)

    def is_won(self, g):
        return sum(len(g.cards(f)) for f in self.foundations) == 52

    def can_deal(self, g):
        return not g.empty(self.stock) or not g.empty(self.waste)

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau + [self.waste, self.reserve]:
                c = g.top(sid)
                if (c and self._foundation_for(g, c) is not None
                        and self.safe_to_autoplay(g, c)):
                    fid = self._foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    self._refill(g)
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(f)) for f in self.foundations)
        base = RANK_NAME.get(g.base_val, str(g.base_val))
        stock, reserve = len(g.cards(self.stock)), len(g.cards(self.reserve))
        return f"Stock: {stock}  Reserve: {reserve}  Base: {base}  ({done}/52)"

    # hint(): generic progress-based engine hint (see Solitaire.hint).
