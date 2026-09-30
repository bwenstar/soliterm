"""Pyramid, AisleRiot's Thirteen: take a pyramid apart in pairs making 13."""

from __future__ import annotations

from ..cards import KING
from ..gamedef import GameDef

# (rows down, half cards across) of each pyramid card, the peak first and
# each row left to right, as AisleRiot numbers them
SPOTS = [(row, 6 - row + 2 * i) for row in range(7) for i in range(row + 1)]

# the two cards that cover each one (none for the bottom row)
COVERS = [
    [j for j, (down, across) in enumerate(SPOTS) if down == row + 1 and abs(across - col) == 1]
    for row, col in SPOTS
]

# the stock and the waste top left, and the cards taken off top right,
# all in the pyramid's row so it fits 24 rows
STOCK_SPOT, WASTE_SPOT, DISCARD_SPOT = (0, 0), (0, 2), (0, 12)


class Pyramid(GameDef):
    key = "pyramid"
    name = "Pyramid"
    blurb = "Take the pyramid apart in pairs making 13; a King goes alone."
    short_blurb = "Clear a pyramid in pairs that make 13."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste", "right")
        self.pyramid = [g.add_slot("tableau") for _ in SPOTS]
        # where the cards taken off go, so they can come back on undo and
        # fall in the win's cascade; AisleRiot just takes them away
        self.discard = g.add_slot("foundation")
        for i, p in enumerate(self.pyramid):
            g.deal_from_deck(p, 1, face_up=not COVERS[i])
        # the other 24 are the stock, and the waste starts empty
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def spot(self, g, sid):
        if sid == self.stock:
            return STOCK_SPOT
        if sid == self.waste:
            return WASTE_SPOT
        if sid == self.discard:
            return DISCARD_SPOT
        return SPOTS[sid - self.pyramid[0]]

    def fan_limit(self, g, sid):
        # the waste's top two, which pair with each other, and no more, so
        # the fan stays clear of the pyramid
        return 2 if sid == self.waste else None

    def _free(self, g, sid):
        """The top card of sid if it's free to play: a pyramid card nothing
        covers, which is face up, or the waste's top card."""
        top = g.top(sid)
        if top is None or not top.face_up or g.kind(sid) not in ("tableau", "waste"):
            return None
        return top

    def _waste_pair(self, g):
        """True if the waste's top two cards make 13."""
        waste = g.cards(self.waste)
        return len(waste) > 1 and waste[-1].rank + waste[-2].rank == 13

    def can_pickup(self, g, sid, n):
        return n == 1 and self._free(g, sid) is not None

    def can_drop(self, g, src, cards, dst):
        card = cards[0]
        if dst == self.discard:
            # a King alone, or the waste's top card with the one under it
            return card.rank == KING or (src == self.waste and self._waste_pair(g))
        partner = self._free(g, dst)
        return partner is not None and card.rank + partner.rank == 13

    def why_not(self, g, src, cards, dst):
        if src == self.discard:
            return "cards taken off stay off"
        if g.kind(src) == "tableau" and not cards[0].face_up:
            return "a face-down card stays until both cards over it are gone"
        reason = self.lift_refusal(g, src, cards)
        if reason:
            return reason
        card = cards[0]
        if dst == self.discard:
            waste = g.cards(self.waste)
            if src == self.waste and len(waste) > 1:
                return self._pair_refusal(g, card, waste[-2])
            return f"{card.label(g.symbols)} only goes in a pair making 13"
        if dst == self.stock:
            return self.slot_refusal(g, cards, dst)
        partner = g.top(dst)
        if partner is None:
            if dst == self.waste:
                return "the waste is empty - deal from the stock first"
            return "there's no card there to pair with"
        if not partner.face_up:
            return "a face-down card can't pair until both cards over it go"
        return self._pair_refusal(g, card, partner)

    @staticmethod
    def _pair_refusal(g, card, partner):
        """Why card and partner, both free, don't go off together."""
        if KING in (card.rank, partner.rank):
            return "a King goes off on its own, not in a pair"
        total = card.rank + partner.rank
        if total == 13:
            return ""
        return f"{card.label(g.symbols)} and {partner.label(g.symbols)} make {total}, not 13"

    def on_click(self, g, sid):
        if sid != self.stock or g.empty(sid):
            return False
        g.slots[self.waste].cards.append(g.slots[sid].cards.pop().up(True))
        return True

    def on_double_click(self, g, sid):
        """Take a free King off, or the waste's top two if they make 13."""
        card = self._free(g, sid)
        if card is None or not self.can_drop(g, sid, [card], self.discard):
            return False
        g.slots[self.discard].cards.append(g.slots[sid].cards.pop())
        self.after_move(g, sid, [card], self.discard)
        return True

    def after_move(self, g, src, cards, dst):
        taken = g.slots[self.discard].cards
        if dst == self.discard:
            if cards[0].rank != KING:  # the card under it on the waste too
                taken.append(g.slots[self.waste].cards.pop())
        else:  # the card and its partner, as one move
            pile = g.slots[dst].cards
            taken += pile[-2:]
            del pile[-2:]
        for i, covers in enumerate(COVERS):
            if covers and all(g.empty(self.pyramid[c]) for c in covers):
                g.flip_top(self.pyramid[i])
        g.score = len(taken)  # a point a card, 52 at most

    def is_won(self, g):
        # As AisleRiot counts a win: the stock and the waste empty, and the
        # second row's left card gone. That card goes only once the 20
        # under it have, so all that can be left is a line of cards from
        # the peak down the right edge, only the lowest of them free, and
        # with the stock and the waste gone nothing to pair it with.
        return g.empty(self.stock) and g.empty(self.waste) and g.empty(self.pyramid[1])

    def status(self, g):
        return f"Stock: {len(g.cards(self.stock))} left"

    def describe_move(self, g, src, dst, n):
        card = g.top(src)
        if card is None:
            return None
        name = card.label(g.symbols)
        if dst != self.discard:
            return f"Match {name} with {g.top(dst).label(g.symbols)}"
        if card.rank == KING:
            return f"Remove {name}"
        return f"Match {name} with the {g.cards(self.waste)[-2].label(g.symbols)} under it"

    def no_foundation_reason(self, g, sid, card, place):
        if g.empty(sid) or sid == self.discard:
            return f"nothing {place} to take off"
        if sid == self.stock:
            return "a card on the stock plays once it's turned onto the waste"
        if self._free(g, sid) is None:
            return f"{card} isn't free yet"
        waste = g.cards(self.waste)
        if sid == self.waste and len(waste) > 1:
            return f"{card} and {waste[-2].label(g.symbols)} don't make 13"
        return f"{card} only goes in a pair making 13"

    def progress(self, g):
        """Cards taken off, then pyramid cards turned up. Every move takes
        a card or two off, so every move gains, and the hint never loops.

        A King comes first: it pairs with nothing, so taking it can only
        help, and one on the waste is holding back the cards under it.
        Then the pair that turns up the most pyramid cards, as those are
        what the rest of the game is played with, and among pairs that
        turn up as many, the one taking more pyramid cards, as the waste's
        cards come back as the cards on them go and the pyramid's don't."""
        taken = g.cards(self.discard)
        kings = sum(1 for c in taken if c.rank == KING)
        turned = sum(1 for p in self.pyramid for c in g.cards(p) if c.face_up) + sum(
            1 for p in self.pyramid if g.empty(p)
        )
        left = sum(len(g.cards(p)) for p in self.pyramid)
        return 1000 * kings + 100 * len(taken) + 10 * turned - left
