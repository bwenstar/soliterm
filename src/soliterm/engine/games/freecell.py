"""FreeCell: every card dealt face up, with four free cells to park cards in."""

from __future__ import annotations

from ..cards import ACE
from ..gamedef import GameDef, alt_color_wanted, cards_up_to, how_many
from ..rng import microsoft_deal


class FreeCell(GameDef):
    key = "freecell"
    name = "FreeCell"
    blurb = "All cards visible. Use the four free cells to build down alt-colour."
    short_blurb = "All cards visible, with four free cells."

    def deal(self, g):
        g.reset_slots()
        # Microsoft's deal: deal_from_deck takes cards off the end
        g.deck = list(reversed(microsoft_deal(g.deal_number)))
        self.cells = [g.add_slot("freecell") for _ in range(4)]
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(8)]
        col = 0
        while g.deck:
            g.deal_from_deck(self.tableau[col % 8], 1, face_up=True)
            col += 1
        g.update_status()

    def _max_supermove(self, g, dst):
        free = sum(1 for c in self.cells if g.empty(c))
        empty_cols = sum(1 for t in self.tableau if g.empty(t) and t != dst)
        return (free + 1) * (2**empty_cols)

    def can_pickup(self, g, sid, n):
        # Cards on the foundations are out of play, as in AisleRiot.
        k = g.kind(sid)
        if k == "freecell":
            return n == 1
        if k == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n :]
            return all(self.alt_color_down(a, b) for a, b in zip(run, run[1:]))
        return False

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        if k == "freecell":
            return len(cards) == 1 and g.empty(dst)
        if k == "foundation":
            if len(cards) != 1:
                return False
            top = g.top(dst)
            return (cards[0].rank == ACE) if top is None else self.same_suit_up(top, cards[0])
        if k == "tableau":
            if len(cards) > self._max_supermove(g, dst):
                return False
            top = g.top(dst)
            if top is None:
                return True
            return self.alt_color_down(top, cards[0])
        return False

    def why_not(self, g, src, cards, dst):
        if g.kind(src) == "foundation":
            return "cards on the foundations stay there"
        reason = (
            self.lift_refusal(g, src, cards)
            or self.run_refusal(g, cards, self.alt_color_down)
            or self.slot_refusal(g, cards, dst)
        )
        if reason:
            return reason
        if g.kind(dst) == "foundation":
            return self.foundation_refusal(g, cards, dst)
        top = g.top(dst)
        if top is not None and not self.alt_color_down(top, cards[0]):
            return self.column_refusal(g, cards[0], top, alt_color_wanted(top))
        # it fits, so the run is too long for the free cells and empty
        # columns to shuffle it across
        free = sum(1 for c in self.cells if g.empty(c))
        empty = sum(1 for t in self.tableau if g.empty(t) and t != dst)
        columns = "other empty column" if top is None else "empty column"
        return (
            f"{cards_up_to(self._max_supermove(g, dst))} with "
            f"{how_many(free, 'free cell')} and {how_many(empty, columns)}"
        )

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
                if c is not None:
                    fid = self.foundation_for(g, c)
                    if fid is not None and self.safe_to_autoplay(g, c):
                        g.slots[fid].cards.append(g.slots[sid].cards.pop())
                        g.score += 1
                        n += 1
                        again = True
        return n

    def status(self, g):
        free = sum(1 for c in self.cells if g.empty(c))
        return f"Free cells: {free}/4"

    # hint(): generic progress-based engine hint (see Solitaire.hint).
