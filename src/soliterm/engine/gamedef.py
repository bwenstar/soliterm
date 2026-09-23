"""GameDef, the base class every game module fills in, and its shared rule helpers."""

from __future__ import annotations

from typing import List, Optional, Tuple

from .cards import ACE, Card
from .core import Solitaire


class GameDef:
    """Base class for a game module. Subclasses fill in the callbacks."""

    key = "base"
    name = "Base"
    blurb = ""

    # ---- options ---- #
    @classmethod
    def default_options(cls) -> dict:
        return {}

    @classmethod
    def option_spec(cls) -> List[Tuple[str, str, list]]:
        """List of (option_key, label, [allowed values]) for the Options UI."""
        return []

    @classmethod
    def sanitize_options(cls, options: Optional[dict]) -> dict:
        """The options to play with: the defaults, overridden by every value
        in `options` that option_spec() allows.

        Options come from config.json, which may be hand-edited or older than
        the game, so anything unexpected is dropped rather than trusted: an
        unknown key goes, and a value that is not one of the allowed ones (in
        type as well, so "3" or 3.0 is not 3) falls back to the default.
        """
        opts = dict(cls.default_options())
        given = options or {}
        for key, _label, allowed in cls.option_spec():
            if key not in given:
                continue
            value = given[key]
            if any(type(value) is type(a) and value == a for a in allowed):
                opts[key] = value
        return opts

    # ---- setup ---- #
    def deal(self, g: Solitaire) -> None:
        raise NotImplementedError

    # ---- interaction callbacks ---- #
    def can_pickup(self, g: Solitaire, sid: int, n: int) -> bool:
        return False

    def can_drop(self, g: Solitaire, src: int, cards: List[Card], dst: int) -> bool:
        return False

    def on_click(self, g: Solitaire, sid: int) -> bool:
        return False

    def on_double_click(self, g: Solitaire, sid: int) -> bool:
        return False

    def after_move(self, g: Solitaire, src: int, cards: List[Card], dst: int) -> None:
        pass

    def post_move(self, g: Solitaire) -> None:
        """Runs after every successful action (e.g. resolve completions)."""
        g.update_status()

    # ---- info callbacks ---- #
    def is_won(self, g: Solitaire) -> bool:
        return False

    def hint(self, g: Solitaire) -> Optional[Tuple[int, int, str]]:
        return None

    def fallback_move(self, g: Solitaire) -> Optional[Tuple[int, int, int]]:
        """A move for the hint when nothing else helps, as (src, dst, n).

        Only asked once no move advances the game, dealing would change
        nothing and no move sets one up. Following it must never lead back
        round to the same position. The default has nothing to offer.
        """
        return None

    def no_hint_reason(self, g: Solitaire) -> Optional[str]:
        """Why there is no hint, when the game can say better than the
        generic message does (see Solitaire.no_hint_reason)."""
        return None

    def can_deal(self, g: Solitaire) -> bool:
        return bool(g.ids_of("stock")) and not g.empty(g.ids_of("stock")[0])

    def deal_blocked_reason(self, g: Solitaire) -> str:
        """Why a deal isn't allowed right now (shown to the player).

        Only called when can_deal() is False. The default covers the common
        case (no stock, or an empty stock); games with extra deal rules (e.g.
        Spider's "every column must be non-empty") override this.
        """
        if not g.ids_of("stock"):
            return "this game has no stock to deal from"
        return "the stock is empty - nothing left to deal"

    def autoplay(self, g: Solitaire) -> int:
        return 0

    def status(self, g: Solitaire) -> str:
        return ""

    # ---- shared helpers ---- #
    @staticmethod
    def alt_color_down(upper: Card, lower: Card) -> bool:
        """`lower` builds on `upper`: one lower, opposite colour (tableau)."""
        return upper.is_red != lower.is_red and lower.rank == upper.rank - 1

    @staticmethod
    def same_suit_up(prev: Card, nxt: Card) -> bool:
        return prev.suit == nxt.suit and nxt.rank == prev.rank + 1

    def foundation_for(self, g: Solitaire, card: Card) -> Optional[int]:
        """The foundation a card can go to right now (up-by-suit, ace base)."""
        for sid in g.ids_of("foundation"):
            top = g.top(sid)
            if top is None:
                if card.rank == ACE:
                    return sid
            elif self.same_suit_up(top, card):
                return sid
        return None

    def tableau_adjacent(self, upper: Card, lower: Card) -> bool:
        """True if `lower` validly builds directly on `upper` in the tableau.

        This is the per-game tableau sequencing rule, used by progress() to
        count how much real building exists on the board. Defaults to the most
        common rule (down by alternating colour); games that build down by suit
        or by rank override it.
        """
        return self.alt_color_down(upper, lower)

    def progress(self, g: Solitaire) -> int:
        """A monotonic measure of how close the board is to being won.

        Used by the generic hint to reject moves that don't advance the game.
        Higher is better. The default rewards (most → least):
          * cards on the foundations (the goal)          - weight 100
          * face-down cards turned up                    - weight 10
          * cards taken off the waste / free cells /     - weight 3
            reserve (parked cards put back into play)
          * tableau cards built into a valid sequence    - weight 1
        The last term is what lets the hint suggest a genuine BUILD (e.g. 6S
        onto 7H to start a sequence) - the move AisleRiot's hint offers too -
        rather than conservatively telling you to deal. A reversible shuffle
        (sliding a run between two equivalent anchors) loses one adjacency and
        gains one, for a net delta of 0, so it is still never suggested and the
        hint stays provably loop-free.
        """
        score = 0
        face_up = 0
        adjacencies = 0
        for s in g.slots:
            if s.kind == "foundation":
                score += 100 * len(s.cards)
            elif s.kind == "tableau":
                pile = s.cards
                face_up += sum(1 for c in pile if c.face_up)
                for i in range(len(pile) - 1):
                    a, b = pile[i], pile[i + 1]
                    if a.face_up and b.face_up and self.tableau_adjacent(a, b):
                        adjacencies += 1
            elif s.kind in ("waste", "freecell", "reserve"):
                # fewer parked cards = more progress
                score -= 3 * len(s.cards)
        return score + 10 * face_up + adjacencies
