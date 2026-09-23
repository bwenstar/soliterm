"""Golf: clear the tableau onto the waste by rank, one up or down."""

from __future__ import annotations

from ..cards import KING
from ..gamedef import GameDef


class Golf(GameDef):
    key = "golf"
    name = "Golf"
    blurb = "Clear the tableau onto the waste by rank, up or down, no wrapping."

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
        # the remaining 17 cards form the stock (face down); one is turned up
        # to start the waste.
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.slots[self.waste].cards.append(g.slots[self.stock].cards.pop().up(True))
        g.update_status()

    def can_pickup(self, g, sid, n):
        return g.kind(sid) == "tableau" and n == 1 and not g.empty(sid)

    def can_drop(self, g, src, cards, dst):
        if dst != self.waste or g.empty(self.waste):
            return False
        w = g.top(self.waste).rank
        if w == KING:
            return False                 # nothing plays on a King (no wrap)
        c = cards[0].rank
        return c == w + 1 or c == w - 1

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
