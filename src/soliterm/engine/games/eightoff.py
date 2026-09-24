"""Eight Off: a FreeCell variant with eight cells and a tableau built by suit."""

from __future__ import annotations

from ..cards import ACE, KING
from ..gamedef import GameDef


class EightOff(GameDef):
    key = "eightoff"
    name = "Eight Off"
    blurb = "Like FreeCell but with eight cells and the tableau builds by suit."
    short_blurb = "FreeCell with eight cells, built by suit."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.cells = [g.add_slot("freecell") for _ in range(8)]
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(8)]
        # 6 cards to each of the 8 columns (48), 4 remaining go to 4 cells
        for _ in range(6):
            for t in self.tableau:
                g.deal_from_deck(t, 1, face_up=True)
        for i in range(4):
            g.deal_from_deck(self.cells[i], 1, face_up=True)
        g.update_status()

    def _free(self, g):
        return sum(1 for c in self.cells if g.empty(c))

    def _max_group(self, g):
        # AisleRiot's rule: one card more than there are free cells. Empty
        # columns don't add to it, as they only take a King.
        return self._free(g) + 1

    def can_pickup(self, g, sid, n):
        k = g.kind(sid)
        if k in ("freecell", "foundation"):
            return n == 1
        if k == "tableau":
            if n > self._max_group(g):
                return False
            run = g.cards(sid)[len(g.cards(sid)) - n :]
            return all(a.suit == b.suit and b.rank == a.rank - 1 for a, b in zip(run, run[1:]))
        return False

    def tableau_adjacent(self, upper, lower):
        return upper.suit == lower.suit and lower.rank == upper.rank - 1

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        if k == "freecell":
            return len(cards) == 1 and g.empty(dst)
        if k == "foundation":
            if len(cards) != 1 or g.kind(src) == "foundation":
                return False
            top = g.top(dst)
            return (cards[0].rank == ACE) if top is None else self.same_suit_up(top, cards[0])
        if k == "tableau":
            if len(cards) > self._max_group(g):
                return False
            top = g.top(dst)
            if top is None:
                return cards[0].rank == KING  # only a King leads an empty column
            return top.suit == cards[0].suit and top.rank == cards[0].rank + 1
        return False

    def on_double_click(self, g, sid):
        if g.kind(sid) not in ("tableau", "freecell"):
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
        return sum(len(g.cards(s)) for s in self.foundations) == 52

    def can_deal(self, g):
        return False

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau + self.cells:
                c = g.top(sid)
                if (
                    c is not None
                    and self.foundation_for(g, c) is not None
                    and self.safe_to_autoplay(g, c)
                ):
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        return f"Free cells: {self._free(g)}/8"

    # hint(): generic progress-based engine hint (see Solitaire.hint).
