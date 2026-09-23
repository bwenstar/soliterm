#!/usr/bin/env python3
"""aisle - a command-line replica of GNOME AisleRiot (`/usr/games/sol`).

AisleRiot is a collection of solitaire card games sharing one engine: a set of
"slots" holding cards, and per-game rule modules that answer a handful of
callbacks (can you pick up this run? can it land there? what does a click do?
is there a hint? has the game been won?). This module mirrors that design.

Reimplemented from the rules/feature set of GNOME AisleRiot (the engine model,
the games' rules, the statistics dialog). No GPL source code is copied.

Engine: this module (Slot / Solitaire / GameDef and helpers).
Games:  Klondike, Spider, FreeCell, Golf, Yukon, Canfield, Forty Thieves,
        Bakers Dozen, Eight Off.
UI:     aisle_tui.py provides the curses front-end (keyboard + mouse); this
        module also has a pipe-friendly text mode for scripting and testing.

This file is self-contained and has no third-party dependencies.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #

SUITS = "SHDC"                       # Spades, Hearts, Diamonds, Clubs
SUIT_SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RANK_NAME = {1: "A", 11: "J", 12: "Q", 13: "K"}
RED_SUITS = {"H", "D"}
ACE, JACK, QUEEN, KING = 1, 11, 12, 13


@dataclass(frozen=True)
class Card:
    rank: int                # 1 (Ace) .. 13 (King)
    suit: str                # one of SUITS
    face_up: bool = False

    @property
    def is_red(self) -> bool:
        return self.suit in RED_SUITS

    @property
    def is_black(self) -> bool:
        return self.suit not in RED_SUITS

    @property
    def color(self) -> str:
        return "R" if self.is_red else "B"

    @property
    def rank_str(self) -> str:
        return RANK_NAME.get(self.rank, str(self.rank))

    def up(self, face_up: bool = True) -> "Card":
        return Card(self.rank, self.suit, face_up)

    def label(self, symbols: bool = True) -> str:
        suit = SUIT_SYMBOL[self.suit] if symbols else self.suit
        return f"{self.rank_str}{suit}"

    def __str__(self) -> str:
        return self.label(symbols=False)


def make_deck(decks: int = 1, suits: str = SUITS) -> List[Card]:
    """A deck of `decks` copies over the given suits (all face down)."""
    out: List[Card] = []
    for _ in range(decks):
        for suit in suits:
            for rank in range(1, 14):
                out.append(Card(rank, suit))
    return out


# --------------------------------------------------------------------------- #
# Slots
# --------------------------------------------------------------------------- #
# Slot kinds mirror AisleRiot's slot semantics:
#   stock      - the face-down draw pile
#   waste      - cards turned up from the stock
#   foundation - the goal piles (usually built up by suit)
#   tableau    - the main play columns
#   reserve    - a reserve pile (Canfield); cards feed the tableau
#   freecell   - single-card holding cells (FreeCell / Eight Off)
# `expand` controls how the UI lays the slot out:
#   "none"  - only the top card shows (stock, waste-1, freecell, foundation)
#   "down"  - cards fan downward (tableau columns)
#   "right" - cards fan rightward (extended waste in Golf/Canfield)


@dataclass
class Slot:
    sid: int
    kind: str
    expand: str = "none"             # "none" | "down" | "right"
    cards: List[Card] = field(default_factory=list)
    # `row` groups slots onto display lines (set as slots are added).
    row: int = 0

    @property
    def empty(self) -> bool:
        return not self.cards

    @property
    def top(self) -> Optional[Card]:
        return self.cards[-1] if self.cards else None


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #


class Solitaire:
    """Holds the slots and the shared state; dispatches to a GameDef."""

    def __init__(self, gamedef: "GameDef", seed: Optional[int] = None,
                 options: Optional[dict] = None):
        self.gamedef = gamedef
        self.seed = seed
        self.options = dict(gamedef.default_options())
        if options:
            self.options.update(options)
        self.rng = random.Random(seed)
        self.slots: List[Slot] = []
        self._current_row = 0
        self.deck: List[Card] = []
        self._score = 0
        self.base_val = 0            # Canfield foundation base rank
        self.status = ""
        self.moves = 0
        self.redeals_done = 0
        self.current_seed = seed     # the concrete seed of the deal in play
        self._undo: List[bytes] = []
        self._redo: List[bytes] = []
        self.new_game()

    # Score is clamped at 0: AisleRiot never displays a negative score, and
    # taking a card back off a foundation should not push the total below zero.
    # Centralising it here means every `g.score -= 1` across the games is safe.
    @property
    def score(self) -> int:
        return self._score

    @score.setter
    def score(self, value: int) -> None:
        self._score = max(0, int(value))

    # -- slot construction (called by GameDef.deal) ----------------------- #

    def reset_slots(self) -> None:
        self.slots = []
        self._current_row = 0

    def carriage_return(self) -> None:
        self._current_row += 1

    def add_slot(self, kind: str, expand: str = "none",
                 cards: Optional[List[Card]] = None) -> int:
        sid = len(self.slots)
        self.slots.append(Slot(sid, kind, expand, list(cards) if cards else [], self._current_row))
        return sid

    def make_deck(self, decks: int = 1, suits: str = SUITS) -> None:
        self.deck = make_deck(decks, suits)

    def shuffle(self) -> None:
        self.rng.shuffle(self.deck)

    def deal_from_deck(self, slot_id: int, n: int = 1, face_up: bool = False) -> None:
        for _ in range(n):
            if not self.deck:
                return
            self.slots[slot_id].cards.append(self.deck.pop().up(face_up))

    # -- lifecycle -------------------------------------------------------- #

    def new_game(self, seed: Optional[int] = None) -> None:
        """Deal a new game.

        With an explicit `seed` (or a fixed self.seed from --seed) the deal is
        reproducible. Otherwise a concrete random seed is chosen and remembered
        as `current_seed`, so the exact hand can be replayed via restart().
        """
        if seed is not None:
            deal_seed = seed
        elif self.seed is not None:
            deal_seed = self.seed
        else:
            # no fixed seed: pick a concrete one so this deal can be replayed
            deal_seed = random.randrange(1, 2 ** 31)
        self.current_seed = deal_seed
        self.rng = random.Random(deal_seed)
        self.score = 0
        self.base_val = 0
        self.moves = 0
        self.redeals_done = 0
        self.status = ""
        self._undo = []
        self._redo = []
        self.gamedef.deal(self)

    def restart(self) -> None:
        """Re-deal the exact same hand (same shuffle) currently in play."""
        self.new_game(seed=getattr(self, "current_seed", self.seed))

    # -- simulation + move enumeration (used by hints / end-state) -------- #

    def clone(self) -> "Solitaire":
        """A cheap, independent copy of the position for what-if simulation.

        Cards are immutable (frozen dataclass) so copying the slot lists is
        enough; the clone has its own empty undo/redo so simulating moves on it
        never touches the real game.
        """
        g = Solitaire.__new__(Solitaire)
        g.gamedef = self.gamedef
        g.seed = self.seed
        g.current_seed = self.current_seed
        g.options = dict(self.options)
        g.rng = random.Random()
        g.slots = [Slot(s.sid, s.kind, s.expand, list(s.cards), s.row)
                   for s in self.slots]
        g._current_row = self._current_row
        g.deck = list(self.deck)
        g._score = self._score
        g.base_val = self.base_val
        g.status = self.status
        g.moves = self.moves
        g.redeals_done = self.redeals_done
        g._undo = []
        g._redo = []
        return g

    def legal_moves(self) -> List[Tuple[int, int, int]]:
        """Every legal slot->slot move right now, as (src, dst, n) tuples.

        Enumerates each pickup size the game accepts from a slot (1..len) against
        every other slot it will accept - so foundation plays (n=1), full-run
        moves, and partial sub-run moves that uncover a card are all surfaced.
        Cheap enough to run on demand (boards are tiny; cards are immutable).
        """
        out: List[Tuple[int, int, int]] = []
        n_slots = len(self.slots)
        for src in range(n_slots):
            pile = self.cards(src)
            if not pile:
                continue
            for n in range(1, len(pile) + 1):
                if not self.gamedef.can_pickup(self, src, n):
                    continue
                cards = pile[len(pile) - n:]
                for dst in range(n_slots):
                    if dst == src:
                        continue
                    if self.gamedef.can_drop(self, src, list(cards), dst):
                        out.append((src, dst, n))
        return out

    def deal_is_productive(self) -> bool:
        """True if dealing/recycling the stock would actually change the board."""
        if not self.ids_of("stock"):
            return False
        sim = self.clone()
        before = sim.serialize()
        sim.deal()
        return sim.serialize() != before

    def progress(self) -> int:
        """A monotonic 'how far toward winning' score (see GameDef.progress)."""
        return self.gamedef.progress(self)

    def _describe_move(self, src: int, dst: int, n: int) -> str:
        pile = self.cards(src)
        landing = pile[len(pile) - n]          # the card that lands on dst
        k = self.kind(dst)
        if k == "foundation":
            return f"Move {landing} to its foundation"
        if k == "freecell":
            return f"Move {landing} to a free cell"
        if self.empty(dst):
            return f"Move {landing} to the empty column"
        return f"Move {landing} onto {self.top(dst)}"

    # -- end-state detection --------------------------------------------- #

    def has_any_move(self) -> bool:
        """True if ANY legal action exists (a move or a productive deal).

        This is deliberately UNfiltered - unlike hint(), which only suggests
        moves that make progress. A board with only reversible shuffles left is
        not 'game over' (the player can still move), so this must see those.
        """
        if self.legal_moves():
            return True
        return self.deal_is_productive()

    def is_stuck(self) -> bool:
        return not self.is_won() and not self.has_any_move()

    # -- slot queries ----------------------------------------------------- #

    def slots_of(self, kind: str) -> List[Slot]:
        return [s for s in self.slots if s.kind == kind]

    def ids_of(self, kind: str) -> List[int]:
        return [s.sid for s in self.slots if s.kind == kind]

    def cards(self, sid: int) -> List[Card]:
        return self.slots[sid].cards

    def top(self, sid: int) -> Optional[Card]:
        return self.slots[sid].top

    def empty(self, sid: int) -> bool:
        return self.slots[sid].empty

    def kind(self, sid: int) -> str:
        return self.slots[sid].kind

    # -- low-level mutation ---------------------------------------------- #

    def flip_top(self, sid: int) -> None:
        pile = self.slots[sid].cards
        if pile and not pile[-1].face_up:
            pile[-1] = pile[-1].up(True)

    def _move_cards(self, src: int, dst: int, n: int) -> List[Card]:
        pile = self.slots[src].cards
        moving = pile[len(pile) - n:]
        del pile[len(pile) - n:]
        self.slots[dst].cards.extend(moving)
        return moving

    # -- the move pipeline (mirrors AisleRiot button-pressed/released) ---- #

    def default_pickup(self, sid: int) -> int:
        """How many top cards a 'grab' on this slot takes by default.

        Returns the largest n (1..len) the game's can_pickup accepts, else 0.
        """
        n_cards = len(self.cards(sid))
        for n in range(n_cards, 0, -1):
            if self.gamedef.can_pickup(self, sid, n):
                return n
        return 0

    def can_pickup(self, sid: int, n: int) -> bool:
        return self.gamedef.can_pickup(self, sid, n)

    def attempt_move(self, src: int, dst: int, n: Optional[int] = None) -> bool:
        """Try to move card(s) from src to dst. Returns True if performed."""
        if not (0 <= src < len(self.slots)) or not (0 <= dst < len(self.slots)):
            return False
        if src == dst:
            return False
        if self.empty(src):
            return False
        if n is None:
            n = self.default_pickup(src)
        if n <= 0 or n > len(self.cards(src)):
            return False
        if not self.gamedef.can_pickup(self, src, n):
            return False
        moving = self.cards(src)[len(self.cards(src)) - n:]
        if not self.gamedef.can_drop(self, src, list(moving), dst):
            return False
        self._checkpoint()
        self._move_cards(src, dst, n)
        self.gamedef.after_move(self, src, list(moving), dst)
        self.moves += 1
        self.gamedef.post_move(self)
        return True

    def click(self, sid: int) -> bool:
        """Single click on a slot (e.g. deal from stock). Returns True if acted."""
        if not (0 <= sid < len(self.slots)):
            return False
        # `on_click` may mutate state, so we must checkpoint first; if nothing
        # happens we restore BOTH stacks (the checkpoint clears redo).
        saved_redo = list(self._redo)
        self._checkpoint()
        if self.gamedef.on_click(self, sid):
            self.moves += 1
            self.gamedef.post_move(self)
            return True
        self._undo.pop()                  # nothing happened; drop the checkpoint
        self._redo = saved_redo           # ...and keep the redo history intact
        return False

    def double_click(self, sid: int) -> bool:
        """Double click on a slot (auto-move to foundation). Returns True if acted."""
        if not (0 <= sid < len(self.slots)):
            return False
        saved_redo = list(self._redo)
        self._checkpoint()
        if self.gamedef.on_double_click(self, sid):
            self.moves += 1
            self.gamedef.post_move(self)
            return True
        self._undo.pop()
        self._redo = saved_redo
        return False

    # -- undo / redo ------------------------------------------------------ #

    def _checkpoint(self) -> None:
        self._undo.append(self.serialize().encode())
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.serialize().encode())
        self._restore(self._undo.pop().decode())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.serialize().encode())
        self._restore(self._redo.pop().decode())
        return True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    # -- high-level helpers used by the UI -------------------------------- #

    def is_won(self) -> bool:
        return self.gamedef.is_won(self)

    def best_move(self) -> Optional[Tuple[int, int, int]]:
        """The single most useful move that ADVANCES the game, as (src,dst,n).

        Simulates every legal move and keeps the one that most improves a
        progress metric, so it never returns a reversible shuffle (sliding a run
        between two equally valid columns scores zero gain). Because progress is
        bounded and a returned move strictly increases it, following best_move()
        can never cycle. Returns None when no move makes progress.
        """
        base = self.progress()
        best = None
        best_rank = -1
        for (src, dst, n) in self.legal_moves():
            sim = self.clone()
            if not sim.attempt_move(src, dst, n):
                continue
            gain = sim.progress() - base
            if gain <= 0:
                continue                       # no progress: skip (kills loops)
            # tie-break: bigger gain first, then prefer moving fewer cards
            # (the minimal move that achieves the gain), then deeper source
            rank = gain * 1000 - n * 10 + len(self.cards(src))
            if rank > best_rank:
                best_rank = rank
                best = (src, dst, n)
        return best

    def hint(self) -> Optional[Tuple[int, int, str]]:
        """A progress-making move as (src, dst, description) for the UI.

        Falls back to suggesting a productive deal when no move advances the
        game. See best_move() for the loop-free guarantee.
        """
        mv = self.best_move()
        if mv is not None:
            src, dst, n = mv
            return (src, dst, self._describe_move(src, dst, n))
        if self.deal_is_productive():
            stock = self.ids_of("stock")
            if stock:
                return (stock[0], stock[0], "Deal from the stock")
        return None

    def can_deal(self) -> bool:
        return self.gamedef.can_deal(self)

    def deal_blocked_reason(self) -> str:
        """A player-facing explanation of why a deal isn't possible right now."""
        return self.gamedef.deal_blocked_reason(self)

    def deal(self) -> bool:
        """Deal from the stock (the game decides what that means)."""
        stock_ids = self.ids_of("stock")
        if stock_ids:
            return self.click(stock_ids[0])
        return False

    def autoplay(self) -> int:
        """Repeatedly send any obviously-safe cards to foundations.

        The whole sweep is a single undoable action: we checkpoint first and
        discard the checkpoint if nothing moved.
        """
        saved_redo = list(self._redo)
        self._checkpoint()
        n = self.gamedef.autoplay(self)
        if n > 0:
            self.moves += 1
            self.gamedef.post_move(self)
        else:
            self._undo.pop()
            self._redo = saved_redo
        return n

    def update_status(self) -> None:
        self.status = self.gamedef.status(self)

    # -- serialization (undo + tests) ------------------------------------ #

    def serialize(self) -> str:
        def enc(c: Card) -> str:
            return f"{c.rank}{c.suit}{'U' if c.face_up else 'D'}"

        parts = [
            f"game={self.gamedef.key}",
            f"seed={self.seed}",
            f"score={self.score}",
            f"base={self.base_val}",
            f"moves={self.moves}",
            f"redeals={self.redeals_done}",
            f"options={self.options}",
        ]
        for s in self.slots:
            parts.append(f"s{s.sid}|{s.kind}|{s.expand}|{s.row}|"
                         + ",".join(enc(c) for c in s.cards))
        return "\n".join(parts)

    def _restore(self, text: str) -> None:
        def dec(t: str) -> Card:
            return Card(int(t[:-2]), t[-2], t[-1] == "U")

        new_slots: List[Slot] = []
        for line in text.splitlines():
            if line.startswith("score="):
                self.score = int(line[6:])
            elif line.startswith("base="):
                self.base_val = int(line[5:])
            elif line.startswith("moves="):
                self.moves = int(line[6:])
            elif line.startswith("redeals="):
                self.redeals_done = int(line[8:])
            elif line.startswith("s") and "|" in line:
                head, _, cardstr = line.partition("|")
                kind, expand, row, rest = (cardstr.split("|", 3) + ["", "", "0", ""])[:4]
                sid = int(head[1:])
                cards = [dec(x) for x in rest.split(",")] if rest else []
                new_slots.append(Slot(sid, kind, expand, cards, int(row or 0)))
        if new_slots:
            self.slots = sorted(new_slots, key=lambda s: s.sid)


# --------------------------------------------------------------------------- #
# Game definitions
# --------------------------------------------------------------------------- #


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


# ====== Klondike ============================================================ #


class Klondike(GameDef):
    key = "klondike"
    name = "Klondike"
    blurb = "The classic. Build the foundations up by suit, Ace to King."

    @classmethod
    def default_options(cls):
        return {"draw": 1}

    @classmethod
    def option_spec(cls):
        return [("draw", "Cards to draw", [1, 3])]

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste")
        g.add_slot("foundation"); g.add_slot("foundation")
        g.add_slot("foundation"); g.add_slot("foundation")
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(7)]
        # remaining go to stock face down
        for col in range(7):
            for row in range(col + 1):
                g.deal_from_deck(self.tableau[col], 1, face_up=(row == col))
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def can_pickup(self, g, sid, n):
        if g.kind(sid) == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n:]
            if not all(c.face_up for c in run):
                return False
            return self._valid_run(run)
        if g.kind(sid) in ("waste", "foundation"):
            return n == 1
        return False

    @staticmethod
    def _valid_run(run):
        for a, b in zip(run, run[1:]):
            if not (a.is_red != b.is_red and b.rank == a.rank - 1):
                return False
        return True

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        if k == "foundation":
            if len(cards) != 1:
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
            if not waste:
                return False
            g.slots[sid].cards = [c.up(False) for c in reversed(waste)]
            g.slots[self.waste].cards = []
            g.redeals_done += 1
            return True
        draw = g.options.get("draw", 1)
        for _ in range(min(draw, len(g.cards(sid)))):
            g.slots[self.waste].cards.append(g.slots[sid].cards.pop().up(True))
        return True

    def on_double_click(self, g, sid):
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
        return f"Stock: {len(g.cards(self.stock))}  Waste: {len(g.cards(self.waste))}"

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in [self.waste] + self.tableau:
                c = g.top(sid)
                if c and c.face_up:
                    fid = self.foundation_for(g, c)
                    if fid is not None:
                        g.slots[fid].cards.append(g.slots[sid].cards.pop())
                        self._post_take(g, sid)
                        g.score += 1
                        n += 1
                        again = True
        return n

    # hint() is provided generically by the engine (progress-based), so the
    # game-specific override is no longer needed.


# ====== Spider ============================================================== #


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


# ====== FreeCell ============================================================ #


class FreeCell(GameDef):
    key = "freecell"
    name = "FreeCell"
    blurb = "All cards visible. Use the four free cells to build down alt-colour."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
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
        return (free + 1) * (2 ** empty_cols)

    def can_pickup(self, g, sid, n):
        k = g.kind(sid)
        if k in ("freecell", "foundation"):
            return n == 1
        if k == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n:]
            for a, b in zip(run, run[1:]):
                if not self.alt_color_down(a, b):
                    return False
            return True
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
                    if fid is not None:
                        g.slots[fid].cards.append(g.slots[sid].cards.pop())
                        g.score += 1
                        n += 1
                        again = True
        return n

    def status(self, g):
        free = sum(1 for c in self.cells if g.empty(c))
        return f"Free cells: {free}/4"

    # hint(): generic progress-based engine hint (see Solitaire.hint).


# ====== Eight Off (FreeCell variant) ======================================= #


class EightOff(GameDef):
    key = "eightoff"
    name = "Eight Off"
    blurb = "Like FreeCell but with eight cells and the tableau builds by suit."

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

    def _max_supermove(self, g, dst):
        empty_cols = sum(1 for t in self.tableau if g.empty(t) and t != dst)
        return (self._free(g) + 1) * (2 ** empty_cols)

    def can_pickup(self, g, sid, n):
        k = g.kind(sid)
        if k in ("freecell", "foundation"):
            return n == 1
        if k == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n:]
            for a, b in zip(run, run[1:]):
                if not (a.suit == b.suit and b.rank == a.rank - 1):
                    return False
            return True
        return False

    def tableau_adjacent(self, upper, lower):
        return upper.suit == lower.suit and lower.rank == upper.rank - 1

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
                return cards[0].rank == KING       # only a King leads an empty column
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
                if c is not None and self.foundation_for(g, c) is not None:
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        return f"Free cells: {self._free(g)}/8"

    # hint(): generic progress-based engine hint (see Solitaire.hint).


# ====== Golf ================================================================ #


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


# ====== Yukon =============================================================== #


class Yukon(GameDef):
    key = "yukon"
    name = "Yukon"
    blurb = "Like Klondike, but move any group of cards regardless of order."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(7)]
        # column 0 gets 1 face-up; columns 1..6 get 1 face-down base + extra
        g.deal_from_deck(self.tableau[0], 1, face_up=True)
        for col in range(1, 7):
            for _ in range(col):
                g.deal_from_deck(self.tableau[col], 1, face_up=False)
        # then five face-up cards onto columns 1..6
        for _ in range(5):
            for col in range(1, 7):
                g.deal_from_deck(self.tableau[col], 1, face_up=True)
        for col in range(1, 7):
            g.flip_top(self.tableau[col])
        g.update_status()

    def can_pickup(self, g, sid, n):
        if g.kind(sid) != "tableau":
            return False
        run = g.cards(sid)[len(g.cards(sid)) - n:]
        return all(c.face_up for c in run)        # any face-up group, any order

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        if k == "foundation":
            if len(cards) != 1:
                return False
            top = g.top(dst)
            return (cards[0].rank == ACE) if top is None else self.same_suit_up(top, cards[0])
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return cards[0].rank == KING
            return self.alt_color_down(top, cards[0])
        return False

    def on_double_click(self, g, sid):
        if g.kind(sid) != "tableau":
            return False
        c = g.top(sid)
        if c is None:
            return False
        fid = self.foundation_for(g, c)
        if fid is None:
            return False
        g.slots[fid].cards.append(g.slots[sid].cards.pop())
        g.flip_top(sid)
        g.score += 1
        return True

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1
        elif g.kind(src) == "foundation":
            g.score -= 1
        if g.kind(src) == "tableau":
            g.flip_top(src)

    def is_won(self, g):
        return sum(len(g.cards(s)) for s in self.foundations) == 52

    def can_deal(self, g):
        return False

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau:
                c = g.top(sid)
                if c and self.foundation_for(g, c) is not None:
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.flip_top(sid)
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(s)) for s in self.foundations)
        return f"Foundations: {done}/52"

    # hint(): generic progress-based engine hint (see Solitaire.hint).


# ====== Bakers Dozen ======================================================== #


class BakersDozen(GameDef):
    key = "bakersdozen"
    name = "Bakers Dozen"
    blurb = "No stock. Thirteen columns; build foundations up, tableau down by rank."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(13)]
        for _ in range(4):
            for t in self.tableau:
                g.deal_from_deck(t, 1, face_up=True)
        # move any Kings to the bottom of their column (classic Bakers Dozen)
        for t in self.tableau:
            pile = g.cards(t)
            kings = [c for c in pile if c.rank == KING]
            others = [c for c in pile if c.rank != KING]
            g.slots[t].cards = kings + others
        g.update_status()

    def can_pickup(self, g, sid, n):
        if g.kind(sid) == "tableau":
            return n == 1
        return False

    def tableau_adjacent(self, upper, lower):
        return lower.rank == upper.rank - 1     # build down by rank, any suit

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        c = cards[0]
        if k == "foundation":
            top = g.top(dst)
            return (c.rank == ACE) if top is None else self.same_suit_up(top, c)
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return False               # empty columns cannot be refilled
            return top.rank == c.rank + 1  # build down by rank, any suit
        return False

    def on_double_click(self, g, sid):
        if g.kind(sid) != "tableau":
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
        return all(len(g.cards(f)) == 13 for f in self.foundations)

    def can_deal(self, g):
        return False

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau:
                c = g.top(sid)
                if c and self.foundation_for(g, c) is not None:
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(f)) for f in self.foundations)
        return f"Foundations: {done}/52"

    # hint(): generic progress-based engine hint (see Solitaire.hint).


# ====== Forty Thieves ======================================================= #


class FortyThieves(GameDef):
    key = "fortythieves"
    name = "Forty Thieves"
    blurb = "Two decks, ten columns. Build foundations up by suit; tableau down by suit."

    def deal(self, g):
        g.reset_slots()
        g.deck = make_deck(2)
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste", "right")
        self.foundations = [g.add_slot("foundation") for _ in range(8)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(10)]
        for _ in range(4):
            for t in self.tableau:
                g.deal_from_deck(t, 1, face_up=True)
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def can_pickup(self, g, sid, n):
        k = g.kind(sid)
        if k == "waste":
            return n == 1
        if k == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n:]
            for a, b in zip(run, run[1:]):
                if not (a.suit == b.suit and b.rank == a.rank - 1):
                    return False
            return True
        return False

    def tableau_adjacent(self, upper, lower):
        return upper.suit == lower.suit and lower.rank == upper.rank - 1

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        c = cards[0]
        if k == "foundation":
            if len(cards) != 1:
                return False
            top = g.top(dst)
            return (c.rank == ACE) if top is None else self.same_suit_up(top, c)
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return True
            return top.suit == c.suit and top.rank == c.rank + 1
        return False

    def on_click(self, g, sid):
        if sid == self.stock and not g.empty(self.stock):
            g.slots[self.waste].cards.append(g.slots[self.stock].cards.pop().up(True))
            return True
        return False

    def on_double_click(self, g, sid):
        if g.kind(sid) not in ("tableau", "waste"):
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
        return sum(len(g.cards(f)) for f in self.foundations) == 104

    def can_deal(self, g):
        return not g.empty(self.stock)

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau + [self.waste]:
                c = g.top(sid)
                if c and self.foundation_for(g, c) is not None:
                    fid = self.foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(f)) for f in self.foundations)
        return f"Stock: {len(g.cards(self.stock))}  Foundations: {done}/104"

    # hint(): generic progress-based engine hint (see Solitaire.hint).


# ====== Canfield ============================================================ #


class Canfield(GameDef):
    key = "canfield"
    name = "Canfield"
    blurb = "Reserve of 13, deal three at a time. Foundations and tableau wrap K->A."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.stock = g.add_slot("stock")
        self.waste = g.add_slot("waste", "right")
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.reserve = g.add_slot("reserve", "down")
        self.tableau = [g.add_slot("tableau", "down") for _ in range(4)]
        # reserve: 13 cards, top face up
        for i in range(13):
            g.deal_from_deck(self.reserve, 1, face_up=(i == 12))
        # one card to each tableau column, face up
        for t in self.tableau:
            g.deal_from_deck(t, 1, face_up=True)
        # one card to the first foundation sets the base rank
        g.deal_from_deck(self.foundations[0], 1, face_up=True)
        g.base_val = g.top(self.foundations[0]).rank
        # rest to stock
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)
        g.update_status()

    def _f_up(self, top_rank, card_rank):
        return card_rank == (top_rank % 13) + 1

    def _t_down_altcolor(self, top, card):
        # build down with wrap (Ace below 2; King below Ace)
        nextrank = top.rank - 1 if top.rank > 1 else KING
        return top.is_red != card.is_red and card.rank == nextrank

    def tableau_adjacent(self, upper, lower):
        return self._t_down_altcolor(upper, lower)

    def can_pickup(self, g, sid, n):
        k = g.kind(sid)
        if k in ("waste", "reserve"):
            return n == 1
        if k == "tableau":
            run = g.cards(sid)[len(g.cards(sid)) - n:]
            for a, b in zip(run, run[1:]):
                if not self._t_down_altcolor(a, b):
                    return False
            return True
        return False

    def can_drop(self, g, src, cards, dst):
        k = g.kind(dst)
        c = cards[0]
        if k == "foundation":
            if len(cards) != 1:
                return False
            top = g.top(dst)
            if top is None:
                return c.rank == g.base_val
            return top.suit == c.suit and self._f_up(top.rank, c.rank)
        if k == "tableau":
            top = g.top(dst)
            if top is None:
                return True               # any card may start an empty column
            return self._t_down_altcolor(top, c)
        return False

    def on_click(self, g, sid):
        if sid != self.stock:
            return False
        if g.empty(self.stock):
            waste = g.slots[self.waste].cards
            if not waste:
                return False
            g.slots[self.stock].cards = [c.up(False) for c in reversed(waste)]
            g.slots[self.waste].cards = []
            g.redeals_done += 1
            return True
        for _ in range(min(3, len(g.cards(self.stock)))):
            g.slots[self.waste].cards.append(g.slots[self.stock].cards.pop().up(True))
        return True

    def on_double_click(self, g, sid):
        if g.kind(sid) not in ("tableau", "waste", "reserve"):
            return False
        c = g.top(sid)
        if c is None:
            return False
        fid = self._foundation_for(g, c)
        if fid is None:
            return False
        g.slots[fid].cards.append(g.slots[sid].cards.pop())
        g.score += 1
        self._refill(g)
        return True

    def _foundation_for(self, g, card):
        for fid in self.foundations:
            top = g.top(fid)
            if top is None:
                if card.rank == g.base_val:
                    return fid
            elif top.suit == card.suit and self._f_up(top.rank, card.rank):
                return fid
        return None

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1
        elif g.kind(src) == "foundation":
            g.score -= 1
        self._refill(g)

    def _refill(self, g):
        # an empty tableau column is auto-filled from the reserve (Canfield rule)
        for t in self.tableau:
            if g.empty(t) and not g.empty(self.reserve):
                g.slots[t].cards.append(g.slots[self.reserve].cards.pop())
                g.flip_top(t)
        # the reserve's top is always face up. Every reserve removal (a play to
        # foundation/tableau, an autoplay, or the refill above) routes through
        # here, so re-flipping the new top here keeps the whole pile consistent.
        g.flip_top(self.reserve)

    def is_won(self, g):
        return sum(len(g.cards(f)) for f in self.foundations) == 52

    def can_deal(self, g):
        return not g.empty(self.stock) or not g.empty(self.waste)

    def autoplay(self, g):
        n = 0
        again = True
        while again:
            again = False
            for sid in self.tableau + [self.waste, self.reserve]:
                c = g.top(sid)
                if c and self._foundation_for(g, c) is not None:
                    fid = self._foundation_for(g, c)
                    g.slots[fid].cards.append(g.slots[sid].cards.pop())
                    g.score += 1
                    self._refill(g)
                    n += 1
                    again = True
        return n

    def status(self, g):
        done = sum(len(g.cards(f)) for f in self.foundations)
        base = RANK_NAME.get(g.base_val, str(g.base_val))
        return f"Stock: {len(g.cards(self.stock))}  Reserve: {len(g.cards(self.reserve))}  Base: {base}  ({done}/52)"

    # hint(): generic progress-based engine hint (see Solitaire.hint).


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

GAMES: Dict[str, type] = {cls.key: cls for cls in [
    Klondike, Spider, FreeCell, EightOff, Golf, Yukon,
    BakersDozen, FortyThieves, Canfield,
]}

GAME_ORDER = ["klondike", "spider", "freecell", "eightoff", "golf",
              "yukon", "bakersdozen", "fortythieves", "canfield"]


def new_solitaire(key: str, seed: Optional[int] = None,
                  options: Optional[dict] = None) -> Solitaire:
    return Solitaire(GAMES[key](), seed=seed, options=options)
