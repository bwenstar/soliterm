"""The engine: slots and the Solitaire game state that dispatches to a GameDef."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .cards import SUITS, Card, make_deck
from .rng import Pcg32, fisher_yates, stream_of

MAX_DEAL = 2**31 - 1  # deal numbers run from 0 to this
RANDOM_DEALS = 1_000_000  # a random deal is one of the first million, short to share

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
    expand: str = "none"  # "none" | "down" | "right"
    cards: list[Card] = field(default_factory=list)
    # `row` groups slots onto display lines (set as slots are added).
    row: int = 0

    @property
    def empty(self) -> bool:
        return not self.cards

    @property
    def top(self) -> Card | None:
        return self.cards[-1] if self.cards else None


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #

# The numbers a serialize() text holds besides its slots.
_COUNTERS = ("score", "base", "moves", "redeals")
_CARD = re.compile(r"(1[0-3]|[1-9])([SHDC])([UD])")


def _card(token: str) -> Card:
    """The card a serialize() token such as 12HU stands for."""
    m = _CARD.fullmatch(token)
    if m is None:
        raise ValueError(f"not a card: {token!r}")
    return Card(int(m[1]), m[2], m[3] == "U")


class Solitaire:
    """Holds the slots and the shared state; dispatches to a GameDef."""

    def __init__(self, gamedef: GameDef, seed: int | None = None, options: dict | None = None):
        self.gamedef = gamedef
        # The number of the first deal, or None for a random one. While it's
        # set, new deals follow on from it (see next_deal_number).
        self.seed = seed
        self.options = gamedef.sanitize_options(options)
        self.slots: list[Slot] = []
        self._current_row = 0
        self.deck: list[Card] = []
        self._score = 0
        self.base_val = 0  # Canfield foundation base rank
        self.status = ""
        self.moves = 0
        self.redeals_done = 0
        self.deal_number = 0  # the number of the deal in play, set by new_game
        # How messages name cards: with suit symbols (2♥) or letters (2H).
        # The front-end sets it to match the board it draws.
        self.symbols = True
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self.new_game(seed)

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

    def add_slot(self, kind: str, expand: str = "none", cards: list[Card] | None = None) -> int:
        sid = len(self.slots)
        self.slots.append(Slot(sid, kind, expand, list(cards) if cards else [], self._current_row))
        return sid

    def make_deck(self, decks: int = 1, suits: str = SUITS) -> None:
        self.deck = make_deck(decks, suits)

    def shuffle(self) -> None:
        fisher_yates(self.deck, self.rng)

    def deal_from_deck(self, slot_id: int, n: int = 1, face_up: bool = False) -> None:
        for _ in range(n):
            if not self.deck:
                return
            self.slots[slot_id].cards.append(self.deck.pop().up(face_up))

    # -- lifecycle -------------------------------------------------------- #

    def next_deal_number(self) -> int:
        """The deal n deals: the next number after a chosen deal, so a
        session started on deal 48213 goes on to 48214, or a random one."""
        if self.seed is None:
            return random.randint(1, RANDOM_DEALS)
        return (self.deal_number + 1) % (MAX_DEAL + 1)

    def new_game(self, number: int | None = None, options: dict | None = None) -> None:
        """Deal number `number`, or the next deal (see next_deal_number).
        Given `options`, the game plays by them from this deal on.

        The same number always deals the same hand of a game, whatever its
        options and on any Python: the shuffle is our own (see rng).
        """
        if number is None:
            number = self.next_deal_number()
        elif not 0 <= number <= MAX_DEAL:
            raise ValueError(f"deal numbers run from 0 to {MAX_DEAL}, not {number}")
        if options is not None:
            self.options = self.gamedef.sanitize_options(options)
        self.deal_number = number
        self.rng = Pcg32(number, stream_of(self.gamedef.key))
        self.score = 0
        self.base_val = 0
        self.moves = 0
        self.redeals_done = 0
        self.status = ""
        self._undo = []
        self._redo = []
        self.gamedef.deal(self)

    def restart(self) -> None:
        """Deal the hand in play again, from the start."""
        self.new_game(self.deal_number)

    # -- simulation + move enumeration (used by hints / end-state) -------- #

    def clone(self) -> Solitaire:
        """A cheap, independent copy of the position for what-if simulation.

        Cards are immutable (frozen dataclass) so copying the slot lists is
        enough; the clone has its own empty undo/redo so simulating moves on it
        never touches the real game.
        """
        g = Solitaire.__new__(Solitaire)
        g.gamedef = self.gamedef
        g.seed = self.seed
        g.deal_number = self.deal_number
        g.options = dict(self.options)
        g.symbols = self.symbols
        # a clone never deals; the generator only keeps the object whole
        g.rng = Pcg32(self.deal_number, stream_of(self.gamedef.key))
        g.slots = [Slot(s.sid, s.kind, s.expand, list(s.cards), s.row) for s in self.slots]
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

    def legal_moves(self) -> list[tuple[int, int, int]]:
        """Every legal slot->slot move right now, as (src, dst, n) tuples.

        Enumerates each pickup size the game accepts from a slot (1..len) against
        every other slot it will accept - so foundation plays (n=1), full-run
        moves, and partial sub-run moves that uncover a card are all surfaced.
        Cheap enough to run on demand (boards are tiny; cards are immutable).
        """
        out: list[tuple[int, int, int]] = []
        n_slots = len(self.slots)
        for src in range(n_slots):
            pile = self.cards(src)
            if not pile:
                continue
            for n in range(1, len(pile) + 1):
                if not self.gamedef.can_pickup(self, src, n):
                    continue
                cards = pile[len(pile) - n :]
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
        landing = pile[len(pile) - n].label(self.symbols)  # lands on dst
        k = self.kind(dst)
        if k == "foundation":
            if n > 1:  # a run goes up from its top card
                return f"Move {pile[-1].label(self.symbols)} through {landing} to its foundation"
            return f"Move {landing} to its foundation"
        if k == "freecell":
            return f"Move {landing} to a free cell"
        top = self.top(dst)
        if top is None:
            return f"Move {landing} to the empty column"
        return f"Move {landing} onto {top.label(self.symbols)}"

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
        """Not won, and nothing left to do that could still win it: either
        no move at all, or a dead end the game spots (GameDef.is_dead_end)."""
        if self.is_won():
            return False
        return self.gamedef.is_dead_end(self) or not self.has_any_move()

    # -- slot queries ----------------------------------------------------- #

    def slots_of(self, kind: str) -> list[Slot]:
        return [s for s in self.slots if s.kind == kind]

    def ids_of(self, kind: str) -> list[int]:
        return [s.sid for s in self.slots if s.kind == kind]

    def cards(self, sid: int) -> list[Card]:
        return self.slots[sid].cards

    def top(self, sid: int) -> Card | None:
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

    def _move_cards(self, src: int, dst: int, n: int) -> list[Card]:
        pile = self.slots[src].cards
        moving = pile[len(pile) - n :]
        del pile[len(pile) - n :]
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

    def attempt_move(self, src: int, dst: int, n: int | None = None) -> bool:
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
        moving = self.cards(src)[len(self.cards(src)) - n :]
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
        self._undo.pop()  # nothing happened; drop the checkpoint
        self._redo = saved_redo  # ...and keep the redo history intact
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

    def best_move(self) -> tuple[int, int, int] | None:
        """The single most useful move that ADVANCES the game, as (src,dst,n).

        Simulates every legal move and keeps the one that most improves a
        progress metric, so it never returns a reversible shuffle (sliding a run
        between two equally valid columns scores zero gain). Because progress is
        bounded and a returned move strictly increases it, following best_move()
        can never cycle. Returns None when no move makes progress.
        """
        found = self._most_progress(self.legal_moves(), self.progress())
        return None if found is None else found[0]

    def _most_progress(
        self, moves: list[tuple[int, int, int]], base: int
    ) -> tuple[tuple[int, int, int], int] | None:
        """The move in `moves` that takes progress furthest above `base`, with
        its gain, or None if none of them gets above it."""
        best = None
        best_rank = -1
        for src, dst, n in moves:
            sim = self.clone()
            if not sim.attempt_move(src, dst, n):
                continue
            gain = sim.progress() - base
            if gain <= 0:
                continue  # no progress: skip (kills loops)
            # tie-break: bigger gain first, then prefer moving fewer cards
            # (the minimal move that achieves the gain), then deeper source
            rank = gain * 1000 - n * 10 + len(self.cards(src))
            if rank > best_rank:
                best_rank = rank
                best = ((src, dst, n), gain)
        return best

    def setup_move(self) -> tuple[int, int, int] | None:
        """A move that gains nothing itself but opens up one that does.

        Parking a card in a free cell, or moving a king aside to get at the
        ace under it, scores nothing on its own, so best_move() never offers
        it. This looks one move further: it keeps the first move whose best
        follow-up (a move to or from one of the two piles it changed) leaves
        the board ahead of where it started. Moves to an empty slot are the
        same whichever empty slot of that kind they use, so only one is tried.

        Meant for when best_move() has nothing, and then following it stays
        loop-free too: the setup move can't raise progress, so the follow-up
        it was picked for raises it by more and best_move() takes that next,
        leaving the board ahead of where the pair started.
        """
        base = self.progress()
        best = None
        best_rank = -1
        tried_empty = set()
        for src, dst, n in self.legal_moves():
            if self.empty(dst):
                alike = (src, n, self.kind(dst))
                if alike in tried_empty:
                    continue
                tried_empty.add(alike)
            sim = self.clone()
            if not sim.attempt_move(src, dst, n):
                continue
            follow = [m for m in sim.legal_moves() if m[0] in (src, dst) or m[1] in (src, dst)]
            found = sim._most_progress(follow, base)
            if found is None:
                continue
            rank = found[1] * 1000 - n * 10 + len(self.cards(src))
            if rank > best_rank:
                best_rank = rank
                best = (src, dst, n)
        return best

    def hint_move(self) -> tuple[int, int, int] | None:
        """The move hint() suggests, as (src, dst, n), or None.

        A move that advances the game comes first, then a deal if dealing
        would change the board, then a move that sets up one that advances,
        and last whatever the game itself offers (GameDef.fallback_move). A
        deal comes back as (stock, stock, 0). See best_move() and
        setup_move() for why following it never loops.
        """
        if self.gamedef.is_dead_end(self):
            return None  # no move can save it; undo can
        mv = self.best_move()
        if mv is not None:
            return mv
        if self.deal_is_productive():
            stock = self.ids_of("stock")
            if stock:
                return (stock[0], stock[0], 0)
        mv = self.setup_move()
        if mv is not None:
            return mv
        return self.gamedef.fallback_move(self)

    def hint(self) -> tuple[int, int, str] | None:
        """What hint_move() suggests, as (src, dst, description) for the UI."""
        mv = self.hint_move()
        if mv is None:
            return None
        src, dst, n = mv
        if src == dst:
            return (src, dst, "Deal from the stock")
        return (src, dst, self._describe_move(src, dst, n))

    def no_hint_reason(self) -> str:
        """What to tell the player when hint() has nothing to suggest.

        hint() offers a deal whenever one would change the board, so by the
        time it gives up dealing is no help and is never suggested here.
        """
        reason = self.gamedef.no_hint_reason(self)
        if reason:
            return reason
        if self.legal_moves():
            reason = "no move clearly helps from here - your call"
            return reason + (", or undo" if self.can_undo() else "")
        if self.can_undo():
            return "no moves left - undo to try another line"
        return "no moves left"

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
        """Send safe cards up to the foundations until none is left. A card
        is safe when nothing still in play could want to build on it (see
        GameDef.safe_to_autoplay).

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

    def finish_moves(self) -> list[tuple[int, int]] | None:
        """The moves that would finish the game, one card each as (src, dst),
        or None if it can't be finished by sending cards up.

        Only offered once every card is face up and the stock is empty, as
        then nothing is left to find out. Any card that can go up goes, safe
        or not, since every card is going up. A position where one card has
        to move elsewhere first is left to the player.
        """
        if self.is_won():
            return None
        if any(self.slots[s].cards for s in self.ids_of("stock")):
            return None
        if any(not c.face_up for slot in self.slots for c in slot.cards):
            return None
        found = self.ids_of("foundation")
        if not found:
            return None
        g = self.clone()
        rules = g.gamedef
        out: list[tuple[int, int]] = []
        while True:
            move = None
            for src, slot in enumerate(g.slots):
                if slot.kind == "foundation" or not slot.cards:
                    continue
                if not rules.can_pickup(g, src, 1):
                    continue
                card = slot.cards[-1]
                dst = next((f for f in found if rules.can_drop(g, src, [card], f)), None)
                if dst is not None:
                    move = (src, dst)
                    break
            if move is None:
                break
            cards = g._move_cards(move[0], move[1], 1)
            rules.after_move(g, move[0], cards, move[1])
            rules.post_move(g)
            out.append(move)
        return out if g.is_won() else None

    def update_status(self) -> None:
        self.status = self.gamedef.status(self)

    # -- serialization (undo + tests) ------------------------------------ #

    def serialize(self) -> str:
        def enc(c: Card) -> str:
            return f"{c.rank}{c.suit}{'U' if c.face_up else 'D'}"

        parts = [
            f"game={self.gamedef.key}",
            f"score={self.score}",
            f"base={self.base_val}",
            f"moves={self.moves}",
            f"redeals={self.redeals_done}",
            f"options={self.options}",
        ]
        for s in self.slots:
            parts.append(
                f"s{s.sid}|{s.kind}|{s.expand}|{s.row}|" + ",".join(enc(c) for c in s.cards)
            )
        return "\n".join(parts)

    def snapshot(self, steps: int) -> dict:
        """The game as plain data, to be taken up again by resume_solitaire().

        Undo and redo keep the `steps` steps nearest the position.
        """

        def newest(stack: list[bytes]) -> list[str]:
            # not stack[-steps:], which is the whole stack when steps is 0
            return [t.decode() for t in stack[max(0, len(stack) - steps) :]]

        return {
            "game": self.gamedef.key,
            "options": dict(self.options),
            "deal": self.deal_number,
            "moves": self.moves,
            "score": self.score,
            "position": self.serialize(),
            "undo": newest(self._undo),
            "redo": newest(self._redo),
        }

    def _parse(self, text: str) -> tuple[str, dict[str, int], list[Slot]]:
        """The game key, the counters and the slots (by sid) of a serialize() text.

        Raises ValueError for anything serialize() doesn't write. The seed=
        line of older undo steps and the options= line are skipped.
        """
        key = ""
        counters: dict[str, int] = {}
        slots: list[Slot] = []
        for line in text.splitlines():
            name, eq, value = line.partition("=")
            try:
                if eq and name == "game":
                    key = value
                elif eq and name in _COUNTERS:
                    counters[name] = int(value)
                elif eq and name in ("seed", "options"):
                    continue
                elif line.startswith("s") and line.count("|") == 4:
                    head, kind, expand, row, cards = line.split("|")
                    dealt = [_card(t) for t in cards.split(",")] if cards else []
                    slots.append(Slot(int(head[1:]), kind, expand, dealt, int(row)))
                else:
                    raise ValueError
            except ValueError:
                raise ValueError(f"not part of a position: {line!r}") from None
        missing = [name for name in _COUNTERS if name not in counters]
        if missing:
            raise ValueError(f"a position needs a {missing[0]}= line")
        return key, counters, sorted(slots, key=lambda s: s.sid)

    def _check_position(self, text: str) -> None:
        """Raise ValueError unless text has this game's slots and this deal's cards."""
        key, counters, slots = self._parse(text)
        if key != self.gamedef.key:
            raise ValueError(f"a position of {key or 'no game'} doesn't fit {self.gamedef.key}")
        if min(counters.values()) < 0 or counters["base"] > 13:
            raise ValueError(f"the counters {counters} don't fit a deal")

        def layout(slots: list[Slot]) -> list[tuple[int, str, str, int]]:
            return [(s.sid, s.kind, s.expand, s.row) for s in slots]

        def cards(slots: list[Slot]) -> list[tuple[int, str]]:
            return sorted((c.rank, c.suit) for s in slots for c in s.cards)

        if layout(slots) != layout(self.slots):
            raise ValueError(f"the slots don't fit {self.gamedef.key}")
        if cards(slots) != cards(self.slots):
            raise ValueError("the cards don't fit this deal")

    def _restore(self, text: str) -> None:
        _, counters, slots = self._parse(text)
        self.score = counters["score"]
        self.base_val = counters["base"]
        self.moves = counters["moves"]
        self.redeals_done = counters["redeals"]
        if slots:
            self.slots = slots
        # the status line describes the board, so it has to follow it back
        self.update_status()
