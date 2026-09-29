"""Golf: clear the tableau onto the waste by rank, one up or down."""

from __future__ import annotations

from ..cards import ACE, KING
from ..gamedef import GameDef, a_rank


class Golf(GameDef):
    key = "golf"
    name = "Golf"
    blurb = "Clear the tableau onto the waste by rank, up or down, no wrapping."
    short_blurb = "Clear seven columns, one rank up or down."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste", "right")
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(7)]
        for _ in range(5):
            for t in self.tableau:
                g.deal_from_deck(t, 1, face_up=True)
        # the remaining 17 cards form the stock (face down). The waste starts
        # empty, as in AisleRiot: the first click on the stock turns one up.
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def can_pickup(self, g, sid, n):
        return g.kind(sid) == "tableau" and n == 1 and not g.empty(sid)

    def can_drop(self, g, src, cards, dst):
        if dst != self.waste or g.empty(self.waste):
            return False
        w = g.top(self.waste).rank
        if w == KING:
            return False  # nothing plays on a King (no wrap)
        c = cards[0].rank
        return c == w + 1 or c == w - 1

    def why_not(self, g, src, cards, dst):
        if g.kind(src) == "waste":
            return "nothing comes back off the waste"
        reason = self.lift_refusal(g, src, cards)
        if reason:
            return reason
        if len(cards) > 1:
            return "cards go to the waste one at a time"
        if dst != self.waste:
            if g.kind(dst) == "tableau":
                return "cards never go from one column to another"
            return self.slot_refusal(g, cards, dst)
        top = g.top(self.waste)
        if top is None:
            return "the waste is empty - deal from the stock first"
        on = top.label(g.symbols)
        if top.rank == KING:
            return f"nothing goes on {on} - ranks don't wrap round in Golf"
        if top.rank == ACE:
            return f"only a 2 goes on {on} - ranks don't wrap round in Golf"
        return f"only {a_rank(top.rank - 1)} or {a_rank(top.rank + 1)} goes on {on}"

    def on_click(self, g, sid):
        if sid == self.stock and not g.empty(self.stock):
            g.slots[self.waste].cards.append(g.slots[self.stock].cards.pop().up(True))
            return True
        # click a tableau card that legally plays onto the waste
        if g.kind(sid) == "tableau" and not g.empty(sid):
            c = g.top(sid)
            if not g.empty(self.waste):
                w = g.top(self.waste).rank
                if w != KING and (c.rank == w + 1 or c.rank == w - 1):
                    g.slots[self.waste].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    return True
        return False

    def on_double_click(self, g, sid):
        return self.on_click(g, sid)

    def after_move(self, g, src, cards, dst):
        if dst == self.waste:
            g.score += 1

    def is_won(self, g):
        return all(g.empty(t) for t in self.tableau)

    def can_deal(self, g):
        return not g.empty(self.stock)

    def status(self, g):
        return f"Stock: {len(g.cards(self.stock))} left"

    def progress(self, g):
        """Golf has no foundations: progress is clearing the tableau. Fewer
        tableau cards = more progress, so every legal play onto the waste counts.
        """
        return -sum(len(g.cards(t)) for t in self.tableau)
