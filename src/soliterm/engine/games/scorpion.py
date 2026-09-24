"""Scorpion: build down in suit, move any face-up group, and untangle the knots."""

from __future__ import annotations

from ..cards import KING
from ..gamedef import GameDef


class Scorpion(GameDef):
    key = "scorpion"
    name = "Scorpion"
    blurb = "Build down in suit, move any group; four K-to-A piles."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.tableau = [g.add_slot("tableau", "down") for _ in range(7)]
        # seven rows across; the first three hide the first four columns' cards
        for row in range(7):
            for col, t in enumerate(self.tableau):
                g.deal_from_deck(t, 1, face_up=row >= 3 or col >= 4)
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        # the score comes from the board, so a pair in the deal counts now
        g.score = self._score(g)
        g.update_status()

    def tableau_adjacent(self, upper, lower):
        return upper.suit == lower.suit and lower.rank == upper.rank - 1

    def can_pickup(self, g, sid, n):
        if g.kind(sid) != "tableau":
            return False
        pile = g.cards(sid)
        return all(c.face_up for c in pile[len(pile) - n :])  # any group, any order

    def can_drop(self, g, src, cards, dst):
        if g.kind(dst) != "tableau":
            return False
        top = g.top(dst)
        if top is None:
            return cards[0].rank == KING
        return top.face_up and self.tableau_adjacent(top, cards[0])

    def on_click(self, g, sid):
        stock = g.slots[self.stock].cards
        if sid != self.stock or not stock:
            return False
        # onto the first three columns, empty or not
        for t in self.tableau[: len(stock)]:
            g.slots[t].cards.append(stock.pop().up(True))
        return True

    def after_move(self, g, src, cards, dst):
        g.flip_top(src)

    def post_move(self, g):
        g.score = self._score(g)
        g.update_status()

    def _whole_suit(self, pile):
        """A column holding one suit, King to Ace, and nothing else."""
        return len(pile) == 13 and all(
            c.face_up and c.suit == pile[0].suit and c.rank == KING - i for i, c in enumerate(pile)
        )

    def _score(self, g):
        """As AisleRiot counts it: a point for each card in suit on the one
        above it, four for each suit whole in a column of its own, and three
        for each face-down card turned up."""
        score = 0
        hidden = 0
        for t in self.tableau:
            pile = g.cards(t)
            hidden += sum(1 for c in pile if not c.face_up)
            score += sum(
                1
                for a, b in zip(pile, pile[1:])
                if a.face_up and b.face_up and self.tableau_adjacent(a, b)
            )
            score += 4 * self._whole_suit(pile)
        return score + 3 * (12 - hidden)

    def is_won(self, g):
        return all(not g.cards(t) or self._whole_suit(g.cards(t)) for t in self.tableau)

    def is_dead_end(self, g):
        """Nothing left to deal, and every move just slides a whole column
        under a King into an empty one, which changes nothing. A won board
        can only do that too, and is no dead end."""
        if not g.empty(self.stock) or self.is_won(g):
            return False
        moves = g.legal_moves()
        return bool(moves) and all(g.empty(dst) and n == len(g.cards(src)) for src, dst, n in moves)

    def no_hint_reason(self, g):
        if self.is_dead_end(g):
            return (
                "the only moves left slide a whole column into an empty one "
                "- undo to try another line"
            )
        return None

    def status(self, g):
        done = sum(1 for t in self.tableau if self._whole_suit(g.cards(t)))
        return f"Stock: {len(g.cards(self.stock))}  Done: {done}/4"
