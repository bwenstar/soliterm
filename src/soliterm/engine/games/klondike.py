"""Klondike, the classic: seven columns, a stock and a waste, draw one or three."""

from __future__ import annotations

from ..cards import ACE, KING
from ..gamedef import GameDef


class Klondike(GameDef):
    key = "klondike"
    name = "Klondike"
    blurb = "The classic. Build the foundations up by suit, Ace to King."
    short_blurb = "The classic. Build up by suit, Ace to King."

    @classmethod
    def default_options(cls):
        return {"draw": 1, "redeals": "standard"}

    @classmethod
    def option_spec(cls):
        return [
            ("draw", "Cards to draw", [1, 3]),
            ("redeals", "Redeals", ["standard", "none", "unlimited"]),
        ]

    def _redeals_left(self, g):
        """How many more times the waste can go back to the stock, or None
        for no limit. The standard rule is AisleRiot's: two redeals drawing
        one card at a time, as many as you like drawing three."""
        mode = g.options.get("redeals", "standard")
        if mode == "none":
            allowed = 0
        elif mode == "unlimited" or g.options.get("draw", 1) != 1:
            return None
        else:
            allowed = 2
        return max(0, allowed - g.redeals_done)

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste")
        g.add_slot("foundation")
        g.add_slot("foundation")
        g.add_slot("foundation")
        g.add_slot("foundation")
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(7)]
        # remaining go to stock face down
        for col in range(7):
            for row in range(col + 1):
                g.deal_from_deck(self.tableau[col], 1, face_up=(row == col))
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def fan_limit(self, g, sid):
        # drawing three, the board fans the last three out, as in AisleRiot
        if sid == self.waste and g.options.get("draw", 1) == 3:
            return 3
        return None

    def can_pickup(self, g, sid, n):
        if g.kind(sid) == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n :]
            if not all(c.face_up for c in run):
                return False
            return self._valid_run(run)
        if g.kind(sid) in ("waste", "foundation"):
            return n == 1
        return False

    @staticmethod
    def _valid_run(run):
        return all(a.is_red != b.is_red and b.rank == a.rank - 1 for a, b in zip(run, run[1:]))

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        if k == "foundation":
            # a foundation card can come back to the tableau, but moving it
            # to another foundation gets you nothing
            if len(cards) != 1 or g.kind(src) == "foundation":
                return False
            top = g.top(dst)
            c = cards[0]
            return (c.rank == ACE) if top is None else self.same_suit_up(top, c)
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return cards[0].rank == KING
            return top.face_up and self.alt_color_down(top, cards[0])
        return False

    def on_click(self, g, sid):
        if g.kind(sid) != "stock":
            return False
        if g.empty(sid):
            # recycle waste -> stock
            waste = g.slots[self.waste].cards
            if not waste or self._redeals_left(g) == 0:
                return False
            g.slots[sid].cards = [c.up(False) for c in reversed(waste)]
            g.slots[self.waste].cards = []
            g.redeals_done += 1
            return True
        draw = g.options.get("draw", 1)
        for _ in range(min(draw, len(g.cards(sid)))):
            g.slots[self.waste].cards.append(g.slots[sid].cards.pop().up(True))
        return True

    def can_deal(self, g):
        if not g.empty(self.stock):
            return True
        return not g.empty(self.waste) and self._redeals_left(g) != 0

    def deal_blocked_reason(self, g):
        if not g.empty(self.waste):
            return "no redeals left - the waste can't go back to the stock"
        return super().deal_blocked_reason(g)

    def on_double_click(self, g, sid):
        if g.kind(sid) == "foundation":
            # as in AisleRiot: send up every card that can go, safe or not
            return self._send_up(g, safe_only=False) > 0
        if g.kind(sid) not in ("tableau", "waste"):
            return False
        c = g.top(sid)
        if c is None or not c.face_up:
            return False
        fid = self.foundation_for(g, c)
        if fid is None:
            return False
        g.slots[fid].cards.append(g.slots[sid].cards.pop())
        self._post_take(g, sid)
        g.score += 1
        return True

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1
        elif g.kind(src) == "foundation":
            g.score -= 1
        self._post_take(g, src)

    @staticmethod
    def _post_take(g, src):
        if g.kind(src) == "tableau":
            g.flip_top(src)

    def is_won(self, g):
        return sum(len(g.cards(s)) for s in g.ids_of("foundation")) == 52

    def status(self, g):
        text = f"Stock: {len(g.cards(self.stock))}  Waste: {len(g.cards(self.waste))}"
        left = self._redeals_left(g)
        if left is not None:
            text += f"  Redeals left: {left}"
        return text

    def autoplay(self, g):
        return self._send_up(g, safe_only=True)

    def _send_up(self, g, safe_only):
        """Move cards up to the foundations until none will go, and return
        how many went. With safe_only, only those autoplay counts as safe."""
        n = 0
        again = True
        while again:
            again = False
            for sid in [self.waste] + self.tableau:
                c = g.top(sid)
                if c and c.face_up:
                    fid = self.foundation_for(g, c)
                    if fid is not None and (not safe_only or self.safe_to_autoplay(g, c)):
                        g.slots[fid].cards.append(g.slots[sid].cards.pop())
                        self._post_take(g, sid)
                        g.score += 1
                        n += 1
                        again = True
        return n

    # hint() is provided generically by the engine (progress-based), so the
    # game-specific override is no longer needed.
