"""Triple Peaks: clear three overlapping peaks onto the waste in runs."""

from __future__ import annotations

from ..gamedef import GameDef

# (rows down, half cards across) of each peak card, top row first
SPOTS = (
    [(0, x) for x in (3, 9, 15)]
    + [(1, x) for x in (2, 4, 8, 10, 14, 16)]
    + [(2, x) for x in range(1, 18, 2)]
    + [(3, x) for x in range(0, 19, 2)]
)

# the two cards that cover each one (none for the bottom row)
COVERS = [
    [j for j, (down, across) in enumerate(SPOTS) if down == row + 1 and abs(across - col) == 1]
    for row, col in SPOTS
]

# for each peak's top card, and again for clearing the lot
BONUS = {"standard": 15, "multiplier": 25}


class TriplePeaks(GameDef):
    key = "triplepeaks"
    name = "Triple Peaks"
    blurb = "Clear three peaks, one rank up or down; K wraps to A."

    @classmethod
    def default_options(cls):
        return {"scoring": "standard"}

    @classmethod
    def option_spec(cls):
        return [("scoring", "Scoring", ["standard", "multiplier"])]

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste", "right")
        g.carriage_return()
        self.peaks = [g.add_slot("tableau") for _ in SPOTS]
        for i, p in enumerate(self.peaks):
            g.deal_from_deck(p, 1, face_up=not COVERS[i])
        g.deal_from_deck(self.waste, 1, face_up=True)  # free, as in AisleRiot
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def spot(self, g, sid):
        i = sid - self.peaks[0]
        return SPOTS[i] if 0 <= i < len(SPOTS) else None

    def _run(self, g):
        """Cards played since the stock was last turned."""
        return sum(1 for c in g.cards(self.waste) if c.face_up) - 1

    def can_pickup(self, g, sid, n):
        top = g.top(sid)
        return g.kind(sid) == "tableau" and n == 1 and top is not None and top.face_up

    def can_drop(self, g, src, cards, dst):
        top = g.top(self.waste)
        if dst != self.waste or top is None:
            return False
        return (cards[0].rank - top.rank) % 13 in (1, 12)  # a rank up or down; K and A touch

    def on_click(self, g, sid):
        if sid == self.stock:
            stock = g.slots[sid].cards
            if not stock:
                return False
            waste = g.slots[self.waste].cards
            waste[:] = [c.up(False) for c in waste]  # the run is over
            waste.append(stock.pop().up(True))
            if g.options.get("scoring") != "multiplier":
                g.score = max(0, g.score - 5)
            return True
        if self.can_pickup(g, sid, 1) and self.can_drop(g, sid, [g.top(sid)], self.waste):
            g.slots[self.waste].cards.append(g.slots[sid].cards.pop())
            self._played(g, sid)
            return True
        return False

    def on_double_click(self, g, sid):
        return self.on_click(g, sid)

    def after_move(self, g, src, cards, dst):
        if dst == self.waste:
            self._played(g, src)

    def _played(self, g, src):
        """Turn up what the card played from src uncovered, and score it."""
        i = self.peaks.index(src)
        for k, covers in enumerate(COVERS):
            if i in covers and all(g.empty(self.peaks[c]) for c in covers):
                g.flip_top(self.peaks[k])
        scoring = g.options.get("scoring", "standard")
        run = self._run(g)
        g.score += 2 ** (run - 1) if scoring == "multiplier" else run
        if i < 3:  # a peak's top card
            g.score += BONUS[scoring]
        if self.is_won(g):
            g.score += BONUS[scoring]

    def is_won(self, g):
        return all(g.empty(p) for p in self.peaks)

    def status(self, g):
        return f"Stock: {len(g.cards(self.stock))} left  Run: {self._run(g)}"

    def progress(self, g):
        """Fewer cards on the peaks, and more of them turned up. Every play
        gains at least 9, and uncovering a card adds 1, so the hint prefers
        plays that open the peaks up."""
        return sum(-9 if c.face_up else -10 for p in self.peaks for c in g.cards(p))
