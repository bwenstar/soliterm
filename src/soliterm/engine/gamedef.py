"""GameDef, the base class every game module fills in, and its shared rule helpers."""

from __future__ import annotations

from typing import Callable

from .cards import ACE, JACK, KING, QUEEN, Card
from .core import Solitaire

RANK_WORD = {ACE: "Ace", JACK: "Jack", QUEEN: "Queen", KING: "King"}
# the slots a card can lie on alone, as a reason names them
ONE_CARD_SLOT = {
    "waste": "the waste",
    "foundation": "a foundation",
    "reserve": "the reserve",
    "freecell": "a free cell",
}


def a_rank(rank: int, color: str = "") -> str:
    """A card of this rank as a sentence names it: "an Ace", "a 7", "an 8"
    or, with a colour, "a red Queen"."""
    word = f"{color} {RANK_WORD.get(rank, rank)}".lstrip()
    return ("an " if word[0] in "A8" else "a ") + word


def how_many(n: int, noun: str) -> str:
    """n of noun, as in "no free cells", "1 free cell" or "3 free cells"."""
    if n == 1:
        return f"1 {noun}"
    return f"{n or 'no'} {noun}s"


def cards_up_to(n: int) -> str:
    """The most cards that can move, as in "up to 1 card" or "up to 4 cards"."""
    return f"up to {n} card" + ("" if n == 1 else "s")


def alt_color_wanted(top: Card, wrap: bool = False) -> str | None:
    """What builds on top down by alternate colours, as in "a black 4", or
    None under an Ace unless the ranks wrap round to a King."""
    if top.rank == ACE and not wrap:
        return None
    rank = top.rank - 1 if top.rank > ACE else KING
    return a_rank(rank, "black" if top.is_red else "red")


def suit_wanted(top: Card, symbols: bool) -> str | None:
    """What builds on top down by suit, as in "9H", or None under an Ace."""
    if top.rank == ACE:
        return None
    return Card(top.rank - 1, top.suit, True).label(symbols)


def rank_wanted(top: Card) -> str | None:
    """What builds on top down regardless of suit, as in "any 7", or None
    under an Ace."""
    if top.rank == ACE:
        return None
    return f"any {RANK_WORD.get(top.rank - 1, top.rank - 1)}"


class GameDef:
    """Base class for a game module. Subclasses fill in the callbacks."""

    key = "base"
    name = "Base"
    # a line about the game under the board's title, and a shorter one for
    # the menu and --list, where 49 columns are left at 80 with the code
    # skin on
    blurb = ""
    short_blurb = ""

    # ---- options ---- #
    @classmethod
    def default_options(cls) -> dict:
        return {}

    @classmethod
    def option_spec(cls) -> list[tuple[str, str, list]]:
        """List of (option_key, label, [allowed values]) for the Options UI."""
        return []

    @classmethod
    def sanitize_options(cls, options: dict | None) -> dict:
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

    def can_drop(self, g: Solitaire, src: int, cards: list[Card], dst: int) -> bool:
        return False

    def on_click(self, g: Solitaire, sid: int) -> bool:
        return False

    def on_double_click(self, g: Solitaire, sid: int) -> bool:
        return False

    def after_move(self, g: Solitaire, src: int, cards: list[Card], dst: int) -> None:
        pass

    def post_move(self, g: Solitaire) -> None:
        """Runs after every successful action (e.g. resolve completions)."""
        g.update_status()

    # ---- info callbacks ---- #
    def is_won(self, g: Solitaire) -> bool:
        return False

    def hint(self, g: Solitaire) -> tuple[int, int, str] | None:
        return None

    def fallback_move(self, g: Solitaire) -> tuple[int, int, int] | None:
        """A move for the hint when nothing else helps, as (src, dst, n).

        Only asked once no move advances the game, dealing would change
        nothing or only bring the same cards round again, and no move sets
        one up. Following it must never lead back round to the same
        position. The default has nothing to offer.
        """
        return None

    def is_dead_end(self, g: Solitaire) -> bool:
        """True when the game can't be won any more however the cards are
        moved, though some still can be. The default never says so."""
        return False

    def no_hint_reason(self, g: Solitaire) -> str | None:
        """Why there is no hint, when the game can say better than the
        generic message does (see Solitaire.no_hint_reason)."""
        return None

    def why_not(self, g: Solitaire, src: int, cards: list[Card], dst: int) -> str:
        """Why moving `cards`, the top of src, to dst is refused, for the
        player to read after "illegal move: ". Only asked once the move has
        been refused, with src and dst two different slots.

        The default knows Klondike's rules: runs built down by alternate
        colours, foundations up by suit from the Ace, and only a King in an
        empty column. A game with other rules says why by its own. A reason
        names cards the way the board does (g.symbols), never one face down,
        and is at most 58 characters, so the message fits the message line
        at 80 columns. "" leaves it to a line that just says no.
        """
        reason = (
            self.lift_refusal(g, src, cards)
            or self.run_refusal(g, cards, self.alt_color_down)
            or self.slot_refusal(g, cards, dst)
        )
        if reason:
            return reason
        if g.kind(dst) == "foundation":
            if g.kind(src) == "foundation":
                return "a card can't move from one foundation to another"
            return self.foundation_refusal(g, cards, dst)
        top = g.top(dst)
        if top is None:
            return "an empty column takes only a King"
        return self.column_refusal(g, cards[0], top, alt_color_wanted(top))

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

    def fan_limit(self, g: Solitaire, sid: int) -> int | None:
        """Most cards the board fans out to the right in a slot, as
        AisleRiot's partially extended slots do. None shows a "right" slot
        as full as there is room for and any other slot's top card alone.
        Text mode goes by the slot's expand and ignores this."""
        return None

    def spot(self, g: Solitaire, sid: int) -> tuple[int, int] | None:
        """Where the board draws slot sid inside its row, for a game that
        lays cards out by hand rather than side by side: (rows down, half
        cards across). A row down is one covered-card peek, so a card one
        row down hides the lower part of the one above it, as Triple
        Peaks' peaks do. None, the default, puts the slot after the one
        before it.

        A row of slots is placed either all by hand or all in turn. An
        empty slot placed by hand isn't drawn or clickable."""
        return None

    # ---- shared helpers ---- #
    @staticmethod
    def alt_color_down(upper: Card, lower: Card) -> bool:
        """`lower` builds on `upper`: one lower, opposite colour (tableau)."""
        return upper.is_red != lower.is_red and lower.rank == upper.rank - 1

    @staticmethod
    def same_suit_up(prev: Card, nxt: Card) -> bool:
        return prev.suit == nxt.suit and nxt.rank == prev.rank + 1

    # The pieces of a why_not. Each says why a move breaks one rule most
    # games share, or "" when it doesn't.

    @staticmethod
    def lift_refusal(g: Solitaire, src: int, cards: list[Card]) -> str:
        """Cards that can't leave src at all: the stock's, a face-down one,
        or more than the top of a slot that isn't a column."""
        kind = g.kind(src)
        if kind == "stock":
            return "cards in the stock can only be dealt"
        if not all(c.face_up for c in cards):
            return "a face-down card can't be moved"
        if len(cards) > 1 and kind in ONE_CARD_SLOT:
            return f"only the top card of {ONE_CARD_SLOT[kind]} can move"
        return ""

    @staticmethod
    def run_refusal(g: Solitaire, cards: list[Card], builds: Callable[[Card, Card], bool]) -> str:
        """Cards that aren't one built run, where builds(upper, lower) says
        whether lower builds on upper."""
        for a, b in zip(cards, cards[1:]):
            if not builds(a, b):
                return (
                    f"{b.label(g.symbols)} doesn't build on {a.label(g.symbols)}, "
                    "so they can't move together"
                )
        return ""

    @staticmethod
    def slot_refusal(g: Solitaire, cards: list[Card], dst: int) -> str:
        """A slot that takes nothing dropped on it, or a free cell that
        can't take these cards."""
        kind = g.kind(dst)
        if kind in ("stock", "waste", "reserve"):
            return f"nothing goes on the {kind}"
        if kind == "freecell":
            if len(cards) > 1:
                return "a free cell holds one card"
            if not g.empty(dst):
                return "that free cell is full"
        return ""

    @staticmethod
    def foundation_refusal(
        g: Solitaire, cards: list[Card], dst: int, base: int | None = None, wrap: bool = False
    ) -> str:
        """Cards that don't go up on foundation dst, built up by suit from
        the Ace, or from a base rank that wraps round from King to Ace."""
        if len(cards) > 1:
            return "cards go up to a foundation one at a time"
        top = g.top(dst)
        if top is None:
            if base is None:
                return "an empty foundation takes only an Ace"
            return f"an empty foundation takes only {a_rank(base)}, the base rank"
        if len(g.cards(dst)) >= 13 or (top.rank == KING and not wrap):
            return "that foundation is complete"
        wanted = Card(top.rank % KING + 1, top.suit, True)
        return (
            f"{cards[0].label(g.symbols)} doesn't go on {top.label(g.symbols)}, "
            f"which takes {wanted.label(g.symbols)} next"
        )

    @staticmethod
    def column_refusal(g: Solitaire, lead: Card, top: Card, wanted: str | None) -> str:
        """lead doesn't build on top, the card on top of a column, which
        takes `wanted` (as "a black 4"), or nothing when that is None."""
        if not top.face_up:
            return "nothing goes on a face-down card"
        if wanted is None:
            return f"nothing builds on {top.label(g.symbols)}"
        return f"{lead.label(g.symbols)} doesn't go on {top.label(g.symbols)}, which takes {wanted}"

    def foundation_for(self, g: Solitaire, card: Card) -> int | None:
        """The foundation a card can go to right now (up-by-suit, ace base)."""
        for sid in g.ids_of("foundation"):
            top = g.top(sid)
            if top is None:
                if card.rank == ACE:
                    return sid
            elif self.same_suit_up(top, card):
                return sid
        return None

    def safe_to_autoplay(self, g: Solitaire, card: Card) -> bool:
        """True if autoplay may send `card` to a foundation: no card still
        in play could want to build on it (see tableau_adjacent).

        So in Klondike a red 5 waits until both black 4s are home, while in
        Eight Off, which builds by suit, anything that can go up is safe.
        The foundation's base card (an Ace, or Canfield's dealt base rank)
        always goes, and never counts as wanting a card to build on, since
        it can always go straight up; that makes twos safe too.
        """
        base = g.base_val or ACE
        if card.rank == base:
            return True
        return not any(
            c.rank != base and self.tableau_adjacent(card, c)
            for s in g.slots
            if s.kind != "foundation"
            for c in s.cards
        )

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
