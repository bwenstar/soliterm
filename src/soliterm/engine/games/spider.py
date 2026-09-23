"""Spider: two decks in 1, 2 or 4 suits, building down and clearing King-to-Ace runs."""

from __future__ import annotations

from ..cards import make_deck
from ..gamedef import GameDef


class Spider(GameDef):
    key = "spider"
    name = "Spider"
    blurb = "Build down in suit; clear K-to-A runs. 1, 2, or 4 suits."

    @classmethod
    def default_options(cls):
        return {"suits": 1}

    @classmethod
    def option_spec(cls):
        return [("suits", "Suits", [1, 2, 4])]

    def deal(self, g):
        g.reset_slots()
        suits = {1: "S", 2: "SH", 4: "SHDC"}[g.options.get("suits", 1)]
        g.deck = make_deck(8 // len(suits), suits)
        g.shuffle()
        # 8 foundations (completed suits go here), then 10 columns
        self.foundations = [g.add_slot("foundation") for _ in range(8)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(10)]
        self.stock = g.add_slot("stock")
        for col in range(10):
            n = 6 if col < 4 else 5
            for row in range(n):
                g.deal_from_deck(self.tableau[col], 1, face_up=(row == n - 1))
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def _run_len(self, pile):
        if not pile or not pile[-1].face_up:
            return 0
        run = 1
        k = len(pile) - 1
        while k - 1 >= 0:
            a, b = pile[k - 1], pile[k]
            if a.face_up and a.suit == b.suit and a.rank == b.rank + 1:
                run += 1
                k -= 1
            else:
                break
        return run

    def can_pickup(self, g, sid, n):
        if g.kind(sid) != "tableau":
            return False
        return n <= self._run_len(g.cards(sid))

    def can_drop(self, g, src, cards, dst):
        if g.kind(dst) != "tableau":
            return False
        top = g.top(dst)
        if top is None:
            return True
        return top.face_up and top.rank == cards[0].rank + 1

    def on_click(self, g, sid):
        if g.kind(sid) != "stock" or g.empty(sid):
            return False
        if any(g.empty(t) for t in self.tableau):
            return False
        for t in self.tableau:
            g.slots[t].cards.append(g.slots[sid].cards.pop().up(True))
        return True

    def can_deal(self, g):
        return (not g.empty(self.stock)) and all(not g.empty(t) for t in self.tableau)

    def deal_blocked_reason(self, g):
        if g.empty(self.stock):
            return "the stock is empty - nothing left to deal"
        # stock has cards, so the block must be an empty column
        n_empty = sum(1 for t in self.tableau if g.empty(t))
        cols = "column" if n_empty == 1 else "columns"
        return (f"fill the {n_empty} empty {cols} before dealing "
                "- Spider won't deal onto an empty column")

    def after_move(self, g, src, cards, dst):
        if g.kind(src) == "tableau":
            g.flip_top(src)

    def post_move(self, g):
        self._resolve(g)
        g.score = self._score(g)
        g.update_status()

    def _resolve(self, g):
        changed = True
        while changed:
            changed = False
            for t in self.tableau:
                pile = g.cards(t)
                if len(pile) >= 13:
                    tail = pile[-13:]
                    s = tail[0].suit
                    if all(c.face_up and c.suit == s and c.rank == 13 - i
                           for i, c in enumerate(tail)):
                        fid = next(f for f in self.foundations if g.empty(f))
                        g.slots[fid].cards = tail
                        del pile[-13:]
                        g.flip_top(t)
                        changed = True

    def _score(self, g):
        score = 12 * sum(1 for f in self.foundations if not g.empty(f))
        for t in self.tableau:
            pile = g.cards(t)
            for i in range(len(pile) - 1):
                a, b = pile[i], pile[i + 1]
                if a.face_up and b.face_up and a.suit == b.suit and a.rank == b.rank + 1:
                    score += 1
        return score

    def is_won(self, g):
        return all(not g.empty(f) for f in self.foundations)

    def autoplay(self, g):
        return 0  # completions are automatic in post_move

    def status(self, g):
        done = sum(1 for f in self.foundations if not g.empty(f))
        return f"Stock: {len(g.cards(self.stock))} ({len(g.cards(self.stock))//10} deals)  Done: {done}/8"

    def progress(self, g):
        """Spider progresses by building in-suit runs and completing suits.

        Completed suits dominate; otherwise reward each face-up card and each
        in-suit descending adjacency (the same signal _score uses), plus a big
        bonus for uncovering face-down cards. A reversible same-rank shuffle
        between two columns leaves all of these unchanged, so it scores 0 gain.
        """
        completed = sum(1 for f in self.foundations if not g.empty(f))
        face_up = 0
        adjacencies = 0
        for t in self.tableau:
            pile = g.cards(t)
            face_up += sum(1 for c in pile if c.face_up)
            for i in range(len(pile) - 1):
                a, b = pile[i], pile[i + 1]
                if (a.face_up and b.face_up and a.suit == b.suit
                        and a.rank == b.rank + 1):
                    adjacencies += 1
        return 1000 * completed + 10 * face_up + adjacencies
