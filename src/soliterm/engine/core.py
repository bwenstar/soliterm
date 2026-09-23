"""The engine: slots and the Solitaire game state that dispatches to a GameDef."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

from .cards import SUITS, Card, make_deck

if TYPE_CHECKING:
    from .gamedef import GameDef


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
