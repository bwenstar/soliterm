#!/usr/bin/env python3
"""sol - command-line-only Solitaire (Klondike + Spider).

A dependency-free replica of `/usr/games/sol` (GNOME AisleRiot). It plays the
two most popular AisleRiot games entirely in the terminal:

  * Klondike  - the classic game `sol` opens by default.
  * Spider    - 1-, 2-, or 4-suit, the second most popular AisleRiot game.

Features
  * Interactive curses TUI with a main menu, an Options screen, and a
    persistent High Scores table.
  * Pipe-friendly text mode (--text) for scripting and testing.
  * Options you can change in-game: Klondike draw count (1 or 3) and Spider
    suit count (1/2/4). Choices are saved to a config file.
  * AisleRiot-style scoring (see SCORING section) and persistent high scores
    saved under ~/.local/share/sol-cli/ (XDG-aware).

Run `python3 sol.py` to play, or `python3 sol.py --help` for options.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #

SUITS = "SHDC"                 # Spades, Hearts, Diamonds, Clubs
SUIT_SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RANK_NAME = {1: "A", 11: "J", 12: "Q", 13: "K"}
RED_SUITS = {"H", "D"}


@dataclass(frozen=True)
class Card:
    rank: int          # 1 (Ace) .. 13 (King)
    suit: str          # one of SUITS
    face_up: bool = False

    @property
    def is_red(self) -> bool:
        return self.suit in RED_SUITS

    @property
    def rank_str(self) -> str:
        return RANK_NAME.get(self.rank, str(self.rank))

    def flipped(self, face_up: bool) -> "Card":
        return Card(self.rank, self.suit, face_up)

    def label(self, symbols: bool = True) -> str:
        suit = SUIT_SYMBOL[self.suit] if symbols else self.suit
        return f"{self.rank_str}{suit}"

    def __str__(self) -> str:
        return self.label(symbols=False)


def make_deck() -> List[Card]:
    """A single standard 52-card deck (used by Klondike)."""
    return [Card(rank, suit) for suit in SUITS for rank in range(1, 14)]


def make_spider_deck(suits: int) -> List[Card]:
    """The 104-card Spider deck for the given number of suits (1, 2, or 4).

    1 suit  -> 8 copies of spades.
    2 suits -> 4 copies each of spades and hearts.
    4 suits -> 2 full decks.
    """
    if suits == 1:
        used = "S"
    elif suits == 2:
        used = "SH"
    else:
        used = "SHDC"
    copies = 8 // len(used)
    deck: List[Card] = []
    for _ in range(copies):
        for suit in used:
            for rank in range(1, 14):
                deck.append(Card(rank, suit))
    return deck


# --------------------------------------------------------------------------- #
# Pile identifiers
# --------------------------------------------------------------------------- #
# A move is expressed as (source, dest). Sources/dests are strings:
#   "t0".."t6"  tableau piles (Klondike); "t0".."t9" for Spider
#   "f0".."f3"  foundations 0..3 (Klondike)
#   "w"         waste (Klondike)


def tableau_id(i: int) -> str:
    return f"t{i}"


def foundation_id(i: int) -> str:
    return f"f{i}"


def _suffix_index(pile_id: str, hi: int, lo: int = 0) -> Optional[int]:
    """Parse the numeric suffix of a pile id (e.g. 't3' -> 3).

    Returns the index only when it is a plain integer within [lo, hi]; any
    malformed or out-of-range id (negative, non-numeric, too large) yields
    None so callers can reject it as an illegal move rather than crashing.
    """
    try:
        idx = int(pile_id[1:])
    except (ValueError, IndexError):
        return None
    if idx < lo or idx > hi:
        return None
    return idx


# --------------------------------------------------------------------------- #
# SCORING
# --------------------------------------------------------------------------- #
# These are AisleRiot's OWN scoring rules, to match `/usr/games/sol` faithfully.
# They were recovered by disassembling the installed AisleRiot 3.22.31 Guile
# bytecode (klondike.go/spider.go/api.go) and cross-checking the GNOME help:
#
#   Klondike (klondike.scm:107-113): +1 for a card placed ON a foundation,
#       -1 for a card taken OFF a foundation; nothing else scores; the score is
#       NOT clamped at zero (api.scm:734 is a plain add). Max score 52.
#   Spider  (spider.scm:111-132): the score equals the number of in-suit,
#       descending, adjacent card pairs on the board (each "+1 when formed,
#       -1 when broken"), so a completed 13-card suit is worth 12. Starts at 0
#       (NOT 500 - that's the Microsoft convention). Max / winning score 96.
#
# Everything is centralised here so it is trivial to retune (e.g. to the classic
# Microsoft scheme: waste->found +10, turn-over +5, found->tableau -15, etc.).

KLONDIKE_SCORE = {
    "waste_to_tableau": 0,         # turning a waste card onto the tableau
    "waste_to_foundation": 1,      # waste -> foundation
    "tableau_to_foundation": 1,    # tableau -> foundation
    "tableau_to_tableau": 0,       # rearranging within the tableau
    "turn_over": 0,                # revealing a previously face-down card
    "foundation_to_tableau": -1,   # taking a card back off a foundation
    "recycle": 0,                  # recycling the stock (no penalty)
}
KLONDIKE_SCORE_CLAMP_ZERO = False  # AisleRiot does not clamp; score may go < 0

# Spider's score is derived from the board (see SpiderGame._compute_score),
# not accumulated per-move, so it needs no per-action table. Max score 96.
SPIDER_WINNING_SCORE = 96


# --------------------------------------------------------------------------- #
# Klondike engine
# --------------------------------------------------------------------------- #


@dataclass
class Game:
    """Klondike Solitaire.

    The public API (new_game/move/draw/undo/autofinish/is_won/serialize/...) is
    stable; the score field and timing were added on top without changing any
    move legality or card-conservation behaviour.
    """

    draw_count: int = 1
    seed: Optional[int] = None
    score: int = 0
    start_time: float = 0.0
    stock: List[Card] = field(default_factory=list)
    waste: List[Card] = field(default_factory=list)
    foundations: List[List[Card]] = field(default_factory=lambda: [[] for _ in range(4)])
    tableau: List[List[Card]] = field(default_factory=lambda: [[] for _ in range(7)])
    moves: int = 0
    redeals: int = 0
    _history: List[bytes] = field(default_factory=list, repr=False)

    name = "Klondike"

    # -- setup ------------------------------------------------------------- #

    def new_game(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = seed
        rng = random.Random(self.seed)
        deck = make_deck()
        rng.shuffle(deck)
        self.stock = []
        self.waste = []
        self.foundations = [[] for _ in range(4)]
        self.tableau = [[] for _ in range(7)]
        self.moves = 0
        self.redeals = 0
        self.score = 0
        self.start_time = time.time()
        self._history = []

        idx = 0
        for col in range(7):
            for row in range(col + 1):
                card = deck[idx]
                idx += 1
                face_up = row == col          # only the last (top) card is up
                self.tableau[col].append(card.flipped(face_up))
        # remaining cards form the stock, all face down
        self.stock = [c.flipped(False) for c in deck[idx:]]

    # -- scoring ----------------------------------------------------------- #

    def _award(self, key: str) -> None:
        self.score += KLONDIKE_SCORE.get(key, 0)
        if KLONDIKE_SCORE_CLAMP_ZERO and self.score < 0:
            self.score = 0

    def elapsed_seconds(self) -> float:
        if not self.start_time:
            return 0.0
        return max(0.0, time.time() - self.start_time)

    # -- history / undo ---------------------------------------------------- #

    def _snapshot(self) -> bytes:
        return self.serialize().encode()

    def _push_history(self) -> None:
        self._history.append(self._snapshot())

    def undo(self) -> bool:
        if not self._history:
            return False
        snap = self._history.pop()
        restored = Game.deserialize(snap.decode())
        self.draw_count = restored.draw_count
        self.seed = restored.seed
        self.score = restored.score
        self.stock = restored.stock
        self.waste = restored.waste
        self.foundations = restored.foundations
        self.tableau = restored.tableau
        self.moves = restored.moves
        self.redeals = restored.redeals
        # start_time is intentionally NOT restored: the clock keeps running.
        return True

    # -- queries ----------------------------------------------------------- #

    def is_won(self) -> bool:
        return sum(len(f) for f in self.foundations) == 52

    def foundation_for_suit(self, suit: str) -> int:
        """Index of the foundation already holding `suit`, or first empty one."""
        for i, f in enumerate(self.foundations):
            if f and f[-1].suit == suit:
                return i
        for i, f in enumerate(self.foundations):
            if not f:
                return i
        return -1

    @staticmethod
    def valid_tableau_run(cards: List[Card]) -> bool:
        """True if `cards` form a face-up, descending, alternating-colour run."""
        if not cards:
            return False
        for c in cards:
            if not c.face_up:
                return False
        for a, b in zip(cards, cards[1:]):
            if b.rank != a.rank - 1 or b.is_red == a.is_red:
                return False
        return True

    def can_place_on_tableau(self, card: Card, col: int) -> bool:
        pile = self.tableau[col]
        if not pile:
            return card.rank == 13            # empty pile: King only
        top = pile[-1]
        if not top.face_up:
            return False
        return card.rank == top.rank - 1 and card.is_red != top.is_red

    def can_place_on_foundation(self, card: Card, fidx: int) -> bool:
        f = self.foundations[fidx]
        if not f:
            return card.rank == 1             # empty foundation: Ace only
        top = f[-1]
        return card.suit == top.suit and card.rank == top.rank + 1

    # -- the moves --------------------------------------------------------- #

    def draw(self) -> bool:
        """Draw from stock to waste, or recycle waste when stock is empty."""
        if not self.stock and not self.waste:
            return False
        self._push_history()
        if not self.stock:
            # recycle: waste back to stock, preserving deal order
            self.stock = [c.flipped(False) for c in reversed(self.waste)]
            self.waste = []
            self.redeals += 1
            self.moves += 1
            self._award("recycle")
            return True
        n = min(self.draw_count, len(self.stock))
        drawn = [self.stock.pop().flipped(True) for _ in range(n)]
        self.waste.extend(drawn)
        self.moves += 1
        return True

    def _flip_tableau_top(self, col: int) -> None:
        pile = self.tableau[col]
        if pile and not pile[-1].face_up:
            pile[-1] = pile[-1].flipped(True)
            self._award("turn_over")

    def _waste_top(self) -> Optional[Card]:
        return self.waste[-1] if self.waste else None

    def move_to_foundation(self, source: str) -> bool:
        """Move the top card of `source` (waste or tableau) to a foundation."""
        if source == "w":
            card = self._waste_top()
            if card is None:
                return False
            fidx = self.foundation_for_suit(card.suit)
            if fidx < 0 or not self.can_place_on_foundation(card, fidx):
                return False
            self._push_history()
            self.foundations[fidx].append(self.waste.pop())
            self._award("waste_to_foundation")
            self.moves += 1
            return True
        if source.startswith("t"):
            col = _suffix_index(source, hi=6)
            if col is None:
                return False
            pile = self.tableau[col]
            if not pile or not pile[-1].face_up:
                return False
            card = pile[-1]
            fidx = self.foundation_for_suit(card.suit)
            if fidx < 0 or not self.can_place_on_foundation(card, fidx):
                return False
            self._push_history()
            self.foundations[fidx].append(pile.pop())
            self._award("tableau_to_foundation")
            self._flip_tableau_top(col)
            self.moves += 1
            return True
        return False

    def move_to_tableau(self, source: str, dest_col: int, count: Optional[int] = None) -> bool:
        """Move card(s) from `source` onto tableau pile `dest_col`.

        For a tableau source, moves the deepest legal run by default; pass
        `count` to move exactly that many cards from the top of the pile.
        A foundation source ("f0".."f3") moves its top card back down.
        """
        if dest_col < 0 or dest_col > 6:
            return False
        if source == "w":
            card = self._waste_top()
            if card is None or not self.can_place_on_tableau(card, dest_col):
                return False
            self._push_history()
            self.tableau[dest_col].append(self.waste.pop())
            self._award("waste_to_tableau")
            self.moves += 1
            return True

        if source.startswith("f"):
            fidx = _suffix_index(source, hi=3)
            if fidx is None:
                return False
            f = self.foundations[fidx]
            if not f or not self.can_place_on_tableau(f[-1], dest_col):
                return False
            self._push_history()
            self.tableau[dest_col].append(self.foundations[fidx].pop())
            self._award("foundation_to_tableau")
            self.moves += 1
            return True

        if source.startswith("t"):
            src_col = _suffix_index(source, hi=6)
            if src_col is None:
                return False
            if src_col == dest_col:
                return False
            pile = self.tableau[src_col]
            if not pile:
                return False

            # face-up segment of the source pile
            first_up = next((i for i, c in enumerate(pile) if c.face_up), None)
            if first_up is None:
                return False
            face_up = pile[first_up:]
            if not self.valid_tableau_run(face_up):
                return False

            if count is not None:
                if count < 1 or count > len(face_up):
                    return False
                start = len(pile) - count
                moving = pile[start:]
                if not self.can_place_on_tableau(moving[0], dest_col):
                    return False
            else:
                # deepest card in the run that can legally land on dest
                start = None
                for i in range(first_up, len(pile)):
                    if self.can_place_on_tableau(pile[i], dest_col):
                        start = i
                        break
                if start is None:
                    return False
                moving = pile[start:]

            self._push_history()
            del pile[len(pile) - len(moving):]
            self.tableau[dest_col].extend(moving)
            self._award("tableau_to_tableau")
            self._flip_tableau_top(src_col)
            self.moves += 1
            return True

        return False

    def move(self, source: str, dest: str, count: Optional[int] = None) -> bool:
        """Dispatch a move from `source` to `dest`. Returns True on success."""
        if dest == "f" or dest.startswith("f"):
            if dest == "f":
                return self.move_to_foundation(source)
            # explicit foundation index
            fidx = _suffix_index(dest, hi=3)
            if fidx is None:
                return False
            if source == "w":
                card = self._waste_top()
                if card and self.can_place_on_foundation(card, fidx):
                    self._push_history()
                    self.foundations[fidx].append(self.waste.pop())
                    self._award("waste_to_foundation")
                    self.moves += 1
                    return True
                return False
            if source.startswith("t"):
                col = _suffix_index(source, hi=6)
                if col is None:
                    return False
                pile = self.tableau[col]
                if pile and pile[-1].face_up and self.can_place_on_foundation(pile[-1], fidx):
                    self._push_history()
                    self.foundations[fidx].append(pile.pop())
                    self._award("tableau_to_foundation")
                    self._flip_tableau_top(col)
                    self.moves += 1
                    return True
                return False
            return False
        if dest.startswith("t"):
            dcol = _suffix_index(dest, hi=6)
            if dcol is None:
                return False
            return self.move_to_tableau(source, dcol, count)
        return False

    def autoplay_once(self) -> bool:
        """Send a single best candidate (waste/tableau top) to a foundation."""
        # waste first, then tableau tops
        if self.move_to_foundation("w"):
            return True
        for col in range(7):
            pile = self.tableau[col]
            if pile and pile[-1].face_up and self.move_to_foundation(tableau_id(col)):
                return True
        return False

    def autofinish(self) -> int:
        """Greedily push every available card to the foundations."""
        n = 0
        while self.autoplay_once():
            n += 1
        return n

    def has_any_move(self) -> bool:
        """True if any legal move (other than a pure stock draw) exists."""
        # to foundation
        if self._waste_top() and self.foundation_for_suit(self._waste_top().suit) >= 0:
            c = self._waste_top()
            if self.can_place_on_foundation(c, self.foundation_for_suit(c.suit)):
                return True
        for col in range(7):
            pile = self.tableau[col]
            if pile and pile[-1].face_up:
                c = pile[-1]
                fi = self.foundation_for_suit(c.suit)
                if fi >= 0 and self.can_place_on_foundation(c, fi):
                    return True
        # waste -> tableau
        if self._waste_top():
            for col in range(7):
                if self.can_place_on_tableau(self._waste_top(), col):
                    return True
        # tableau -> tableau
        for src in range(7):
            pile = self.tableau[src]
            first_up = next((i for i, c in enumerate(pile) if c.face_up), None)
            if first_up is None:
                continue
            for i in range(first_up, len(pile)):
                for dst in range(7):
                    if dst == src:
                        continue
                    if self.can_place_on_tableau(pile[i], dst):
                        # avoid the no-op of shuffling a full pile to empty col
                        if not self.tableau[dst] and i == first_up:
                            continue
                        return True
        return False

    # -- serialization (for undo + tests) ---------------------------------- #

    def serialize(self) -> str:
        def enc(c: Card) -> str:
            return f"{c.rank}{c.suit}{'U' if c.face_up else 'D'}"

        parts = [
            f"draw={self.draw_count}",
            f"seed={self.seed}",
            f"score={self.score}",
            f"moves={self.moves}",
            f"redeals={self.redeals}",
            "stock=" + ",".join(enc(c) for c in self.stock),
            "waste=" + ",".join(enc(c) for c in self.waste),
        ]
        for i, f in enumerate(self.foundations):
            parts.append(f"f{i}=" + ",".join(enc(c) for c in f))
        for i, t in enumerate(self.tableau):
            parts.append(f"t{i}=" + ",".join(enc(c) for c in t))
        return "\n".join(parts)

    @staticmethod
    def deserialize(text: str) -> "Game":
        g = Game()
        g.foundations = [[] for _ in range(4)]
        g.tableau = [[] for _ in range(7)]

        def dec(s: str) -> Card:
            face = s[-1] == "U"
            suit = s[-2]
            rank = int(s[:-2])
            return Card(rank, suit, face)

        def cards(val: str) -> List[Card]:
            val = val.strip()
            return [dec(x) for x in val.split(",")] if val else []

        for line in text.splitlines():
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key == "draw":
                g.draw_count = int(val)
            elif key == "seed":
                g.seed = None if val == "None" else int(val)
            elif key == "score":
                g.score = int(val)
            elif key == "moves":
                g.moves = int(val)
            elif key == "redeals":
                g.redeals = int(val)
            elif key == "stock":
                g.stock = cards(val)
            elif key == "waste":
                g.waste = cards(val)
            elif key.startswith("f"):
                g.foundations[int(key[1:])] = cards(val)
            elif key.startswith("t"):
                g.tableau[int(key[1:])] = cards(val)
        return g


# --------------------------------------------------------------------------- #
# Spider engine
# --------------------------------------------------------------------------- #


class SpiderGame:
    """Spider Solitaire (1-, 2-, or 4-suit, 104 cards, 10 columns).

    Rules:
      * 54 cards dealt to 10 columns (cols 0-3 get 6, cols 4-9 get 5); only the
        top card of each column is face up.
      * The remaining 50 cards form the stock, dealt 10 at a time (one to each
        column).  You may not deal while any column is empty.
      * Build down by rank regardless of suit; you may move a group of cards
        together only if they form a same-suit descending run.
      * Any card/run may be placed on an empty column.
      * A complete K..A same-suit run is removed automatically to a foundation.
      * Win = all 8 suits completed.
    """

    name = "Spider"

    def __init__(self, suits: int = 1, seed: Optional[int] = None) -> None:
        self.suits = suits
        self.seed = seed
        self.score = 0
        self.start_time = 0.0
        self.stock: List[Card] = []
        self.tableau: List[List[Card]] = [[] for _ in range(10)]
        self.completed: List[List[Card]] = []   # finished K..A suits
        self.moves = 0
        self.deals = 0
        self._history: List[bytes] = []

    # alias so generic UI code can show "foundations done / 8"
    @property
    def foundations(self) -> List[List[Card]]:
        return self.completed

    # -- setup ------------------------------------------------------------- #

    def new_game(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = seed
        rng = random.Random(self.seed)
        deck = make_spider_deck(self.suits)
        rng.shuffle(deck)
        self.tableau = [[] for _ in range(10)]
        self.completed = []
        self.moves = 0
        self.deals = 0
        self.score = 0           # recomputed from the board at end of new_game
        self.start_time = time.time()
        self._history = []

        idx = 0
        # 54 cards: first 4 columns get 6, the rest get 5.
        for col in range(10):
            n = 6 if col < 4 else 5
            for row in range(n):
                card = deck[idx]
                idx += 1
                face_up = row == n - 1
                self.tableau[col].append(card.flipped(face_up))
        self.stock = [c.flipped(False) for c in deck[idx:]]
        self.score = self._compute_score()

    # -- scoring / timing -------------------------------------------------- #

    def _compute_score(self) -> int:
        """AisleRiot Spider score: the number of in-suit descending adjacent
        face-up pairs currently on the board, plus 12 for each completed suit
        (a completed 13-card suit contributes 13-1 = 12). Max = 8*12 = 96.
        """
        score = 12 * len(self.completed)
        for pile in self.tableau:
            for i in range(len(pile) - 1):
                a, b = pile[i], pile[i + 1]
                if (a.face_up and b.face_up
                        and a.suit == b.suit and a.rank == b.rank + 1):
                    score += 1
        return score

    def elapsed_seconds(self) -> float:
        if not self.start_time:
            return 0.0
        return max(0.0, time.time() - self.start_time)

    # -- history / undo ---------------------------------------------------- #

    def _push_history(self) -> None:
        self._history.append(self.serialize().encode())

    def undo(self) -> bool:
        if not self._history:
            return False
        restored = SpiderGame.deserialize(self._history.pop().decode())
        self.suits = restored.suits
        self.seed = restored.seed
        self.score = restored.score
        self.stock = restored.stock
        self.tableau = restored.tableau
        self.completed = restored.completed
        self.moves = restored.moves
        self.deals = restored.deals
        return True

    # -- queries ----------------------------------------------------------- #

    def is_won(self) -> bool:
        return len(self.completed) == 8

    def _movable_run_len(self, pile: List[Card]) -> int:
        """Length of the top same-suit descending consecutive face-up run."""
        if not pile or not pile[-1].face_up:
            return 0
        run = 1
        k = len(pile) - 1
        while k - 1 >= 0:
            deeper, shallower = pile[k - 1], pile[k]
            if (deeper.face_up and deeper.suit == shallower.suit
                    and deeper.rank == shallower.rank + 1):
                run += 1
                k -= 1
            else:
                break
        return run

    def can_deal(self) -> bool:
        if not self.stock:
            return False
        return all(self.tableau[c] for c in range(10))

    # -- the moves --------------------------------------------------------- #

    def _flip_top(self, col: int) -> None:
        pile = self.tableau[col]
        if pile and not pile[-1].face_up:
            pile[-1] = pile[-1].flipped(True)

    def _resolve_completions(self) -> int:
        """Remove any completed K..A same-suit runs to the foundations."""
        removed = 0
        changed = True
        while changed:
            changed = False
            for col in range(10):
                pile = self.tableau[col]
                if len(pile) < 13:
                    continue
                tail = pile[-13:]
                if not all(c.face_up for c in tail):
                    continue
                suit = tail[0].suit
                ok = all(tail[i].suit == suit and tail[i].rank == 13 - i
                         for i in range(13))
                if ok:
                    self.completed.append(tail)
                    del pile[-13:]
                    self._flip_top(col)
                    removed += 1
                    changed = True
        self.score = self._compute_score()
        return removed

    def deal(self) -> bool:
        """Deal one row (one card to every column). Illegal if a column is empty."""
        if not self.can_deal():
            return False
        self._push_history()
        for col in range(10):
            card = self.stock.pop()
            self.tableau[col].append(card.flipped(True))
        self.deals += 1
        self.moves += 1
        self._resolve_completions()   # recomputes self.score from the board
        self.score = self._compute_score()
        return True

    # generic alias so shared UI code can call draw()
    def draw(self) -> bool:
        return self.deal()

    def move(self, source: str, dest: str, count: Optional[int] = None) -> bool:
        """Move cards between tableau columns. Sources/dests are 't0'..'t9'."""
        if not (source.startswith("t") and dest.startswith("t")):
            return False
        src = _suffix_index(source, hi=9)
        dst = _suffix_index(dest, hi=9)
        if src is None or dst is None or src == dst:
            return False
        pile = self.tableau[src]
        if not pile:
            return False
        run = self._movable_run_len(pile)
        if run == 0:
            return False
        dst_pile = self.tableau[dst]

        if count is None:
            if not dst_pile:
                count = run                       # empty col: move whole run
            else:
                top = dst_pile[-1]
                if not top.face_up:
                    return False
                # how many cards put the deepest moved card directly under top
                count = top.rank - pile[-1].rank
        if count is None or count < 1 or count > run:
            return False

        moving = pile[-count:]
        if dst_pile:
            top = dst_pile[-1]
            if not top.face_up or top.rank != moving[0].rank + 1:
                return False
        # (empty destination accepts any run)

        self._push_history()
        del pile[len(pile) - count:]
        self.tableau[dst].extend(moving)
        self._flip_top(src)
        self.moves += 1
        self._resolve_completions()   # recomputes self.score from the board
        self.score = self._compute_score()
        return True

    def autofinish(self) -> int:
        """Spider has no manual foundation moves; completions are automatic."""
        return self._resolve_completions()

    def has_any_move(self) -> bool:
        if self.can_deal():
            return True
        for src in range(10):
            pile = self.tableau[src]
            run = self._movable_run_len(pile)
            if run == 0:
                continue
            for take in range(1, run + 1):
                bottom = pile[-take]
                for dst in range(10):
                    if dst == src:
                        continue
                    dp = self.tableau[dst]
                    if not dp:
                        # moving onto empty is only meaningful if it's not the
                        # whole pile already alone on a column
                        if take == len(pile):
                            continue
                        return True
                    if dp[-1].face_up and dp[-1].rank == bottom.rank + 1:
                        return True
        return False

    # -- serialization ----------------------------------------------------- #

    def serialize(self) -> str:
        def enc(c: Card) -> str:
            return f"{c.rank}{c.suit}{'U' if c.face_up else 'D'}"

        def encpile(p: List[Card]) -> str:
            return ",".join(enc(c) for c in p)

        parts = [
            "type=spider",
            f"suits={self.suits}",
            f"seed={self.seed}",
            f"score={self.score}",
            f"moves={self.moves}",
            f"deals={self.deals}",
            "stock=" + encpile(self.stock),
        ]
        for i in range(10):
            parts.append(f"c{i}=" + encpile(self.tableau[i]))
        for i, p in enumerate(self.completed):
            parts.append(f"p{i}=" + encpile(p))
        return "\n".join(parts)

    @staticmethod
    def deserialize(text: str) -> "SpiderGame":
        g = SpiderGame()
        g.tableau = [[] for _ in range(10)]
        g.completed = []

        def dec(s: str) -> Card:
            return Card(int(s[:-2]), s[-2], s[-1] == "U")

        def cards(val: str) -> List[Card]:
            val = val.strip()
            return [dec(x) for x in val.split(",")] if val else []

        done: Dict[int, List[Card]] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key == "suits":
                g.suits = int(val)
            elif key == "seed":
                g.seed = None if val == "None" else int(val)
            elif key == "score":
                g.score = int(val)
            elif key == "moves":
                g.moves = int(val)
            elif key == "deals":
                g.deals = int(val)
            elif key == "stock":
                g.stock = cards(val)
            elif key.startswith("c"):
                g.tableau[int(key[1:])] = cards(val)
            elif key.startswith("p"):
                done[int(key[1:])] = cards(val)
        g.completed = [done[k] for k in sorted(done)]
        return g


# --------------------------------------------------------------------------- #
# Persistence: config + high scores
# --------------------------------------------------------------------------- #

APP_DIR_NAME = "sol-cli"


def _xdg(env: str, default_rel: str) -> str:
    base = os.environ.get(env)
    if not base:
        base = os.path.join(os.path.expanduser("~"), default_rel)
    return base


def config_dir() -> str:
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), APP_DIR_NAME)


def data_dir() -> str:
    return os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def highscores_path() -> str:
    return os.path.join(data_dir(), "highscores.json")


DEFAULT_CONFIG = {
    "klondike_draw": 1,    # 1 or 3
    "spider_suits": 1,     # 1, 2, or 4
    "symbols": True,       # unicode suit symbols vs letters
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    # sanitise
    if cfg["klondike_draw"] not in (1, 3):
        cfg["klondike_draw"] = 1
    if cfg["spider_suits"] not in (1, 2, 4):
        cfg["spider_suits"] = 1
    cfg["symbols"] = bool(cfg["symbols"])
    return cfg


def save_config(cfg: dict) -> bool:
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        return True
    except OSError:
        return False


def highscore_key(game) -> str:
    if isinstance(game, SpiderGame):
        return f"spider-{game.suits}suit"
    return f"klondike-draw{game.draw_count}"


def load_highscores() -> dict:
    try:
        with open(highscores_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_highscores(scores: dict) -> bool:
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(highscores_path(), "w", encoding="utf-8") as fh:
            json.dump(scores, fh, indent=2)
        return True
    except OSError:
        return False


def record_highscore(game, won: bool) -> Optional[int]:
    """Record a finished game. Returns the 1-based rank if it made the top 10."""
    key = highscore_key(game)
    entry = {
        "score": int(game.score),
        "time": round(game.elapsed_seconds(), 1),
        "moves": int(game.moves),
        "won": bool(won),
        "when": time.strftime("%Y-%m-%d %H:%M"),
    }
    scores = load_highscores()
    table = scores.get(key, [])
    table.append(entry)
    # rank: higher score first; for equal scores, faster (lower time) first
    table.sort(key=lambda e: (-e.get("score", 0), e.get("time", 1e18)))
    table = table[:10]
    scores[key] = table
    save_highscores(scores)
    # Find OUR entry by object identity, not value: list.index() would match a
    # byte-identical earlier row even after ours was truncated out of the top 10.
    rank = next((i + 1 for i, e in enumerate(table) if e is entry), None)
    return rank


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:d}:{seconds % 60:02d}"


# --------------------------------------------------------------------------- #
# Plain-text rendering (used by --text mode and as a curses fallback)
# --------------------------------------------------------------------------- #

CARD_BACK = "##"
EMPTY_SLOT = "--"


def card_cell(card: Optional[Card], symbols: bool = True, width: int = 3) -> str:
    if card is None:
        return EMPTY_SLOT.ljust(width)
    if not card.face_up:
        return CARD_BACK.ljust(width)
    return card.label(symbols).ljust(width)


def render_text(game: Game, symbols: bool = True) -> str:
    """Render a Klondike board to text."""
    lines: List[str] = []
    stock_cell = CARD_BACK if game.stock else EMPTY_SLOT
    waste_cell = card_cell(game._waste_top(), symbols)
    found = "  ".join(card_cell(f[-1] if f else None, symbols) for f in game.foundations)
    lines.append(f"Stock[{len(game.stock):2}] {stock_cell}    Waste {waste_cell}     Foundations  {found}")
    lines.append("")
    # Columns are labelled 1-based (t1..t7) to match the command scheme
    # documented in HELP_TEXT and used by the curses TUI.
    header = "   ".join(f"t{i + 1}" for i in range(7))
    lines.append("   " + header)

    height = max((len(t) for t in game.tableau), default=0)
    if height == 0:
        height = 1
    for row in range(height):
        cells = []
        for col in range(7):
            pile = game.tableau[col]
            if row < len(pile):
                cells.append(card_cell(pile[row], symbols))
            elif row == 0 and not pile:
                cells.append(EMPTY_SLOT.ljust(3))
            else:
                cells.append("   ")
        lines.append(f"{row:2} " + "  ".join(cells))
    lines.append("")
    status = f"score={game.score}  moves={game.moves}  redeals={game.redeals}  time={fmt_time(game.elapsed_seconds())}"
    if game.is_won():
        status += "   *** YOU WIN! ***"
    lines.append(status)
    return "\n".join(lines)


def render_spider_text(game: SpiderGame, symbols: bool = True) -> str:
    """Render a Spider board to text."""
    lines: List[str] = []
    lines.append(
        f"Stock[{len(game.stock):2}] ({len(game.stock)//10} deals left)"
        f"     Completed {len(game.completed)}/8     suits={game.suits}"
    )
    lines.append("")
    header = " ".join(f"{i + 1:>3}" for i in range(10))
    lines.append("   " + header)

    height = max((len(t) for t in game.tableau), default=0)
    if height == 0:
        height = 1
    for row in range(height):
        cells = []
        for col in range(10):
            pile = game.tableau[col]
            if row < len(pile):
                cells.append(card_cell(pile[row], symbols).ljust(3))
            elif row == 0 and not pile:
                cells.append(EMPTY_SLOT.ljust(3))
            else:
                cells.append("   ")
        lines.append(f"{row:2} " + " ".join(c.ljust(3) for c in cells))
    lines.append("")
    status = f"score={game.score}  moves={game.moves}  time={fmt_time(game.elapsed_seconds())}"
    if game.is_won():
        status += "   *** YOU WIN! ***"
    lines.append(status)
    return "\n".join(lines)


def render(game, symbols: bool = True) -> str:
    if isinstance(game, SpiderGame):
        return render_spider_text(game, symbols)
    return render_text(game, symbols)


# --------------------------------------------------------------------------- #
# Text-mode command parsers (shared by text REPL and tests)
# --------------------------------------------------------------------------- #

HELP_TEXT = """\
Klondike commands (text mode):
  d / s          draw from stock (recycles waste when stock empty)
  <src><dst>     move, e.g.  25  (tableau2 -> tableau5),  w3 (waste -> tableau3)
                 src: digits 1-7 = tableau, w = waste
                 dst: digits 1-7 = tableau, f = foundation (auto suit)
  <src><dst><n>  move exactly n cards, e.g.  253  (3 cards from t2 -> t5)
  a              autofinish: send everything possible to the foundations
  o1 / o3        switch to 1-card or 3-card draw (saved as your default)
  u              undo last move
  n              new game
  p / .          reprint board
  h / ?          this help
  q              quit
"""

SPIDER_HELP_TEXT = """\
Spider commands (text mode):
  d / s          deal a new row (one card to each column; needs no empty column)
  <src> <dst>    move cards between columns 1-10, e.g.  3 5
                 (moves the largest legal same-suit run that fits)
  <src> <dst> <n>   move exactly n cards, e.g.  3 5 4
  a              auto-remove any completed suits
  o1 / o2 / o4   switch suit count (starts a new game; saved as your default)
  u              undo last move
  n              new game
  p / .          reprint board
  h / ?          this help
  q              quit
"""


def parse_selector_source(ch: str) -> Optional[str]:
    if ch == "w":
        return "w"
    if ch.isdigit() and "1" <= ch <= "7":
        return tableau_id(int(ch) - 1)
    return None


def parse_selector_dest(ch: str) -> Optional[str]:
    if ch == "f":
        return "f"
    if ch.isdigit() and "1" <= ch <= "7":
        return tableau_id(int(ch) - 1)
    return None


def apply_klondike_command(game: Game, cmd: str,
                           config: Optional[dict] = None) -> Tuple[bool, str]:
    """Apply a Klondike text command. Returns (ok, message)."""
    cmd = cmd.strip().lower()
    if not cmd:
        return False, ""
    if cmd in ("q", "quit", "exit"):
        return True, "__quit__"
    if cmd in ("h", "?", "help"):
        return True, HELP_TEXT
    if cmd in ("p", ".", "print"):
        return True, "__print__"
    if cmd in ("d", "s", "draw"):
        ok = game.draw()
        return ok, "" if ok else "nothing to draw"
    if cmd in ("a", "auto"):
        n = game.autofinish()
        return n > 0, f"autofinished {n} card(s)"
    if cmd in ("u", "undo"):
        ok = game.undo()
        return ok, "" if ok else "nothing to undo"
    if cmd in ("n", "new"):
        game.new_game()
        return True, "new game"
    if cmd in ("o1", "o3"):
        game.draw_count = int(cmd[1])
        if config is not None:
            config["klondike_draw"] = game.draw_count
            save_config(config)
        return True, f"draw count set to {game.draw_count} (applies to future draws)"

    # movement: src, dst, optional count
    src = parse_selector_source(cmd[0])
    if src is None or len(cmd) < 2:
        return False, f"bad command: {cmd!r} (try h)"
    dst = parse_selector_dest(cmd[1])
    if dst is None:
        return False, f"bad destination: {cmd!r} (try h)"
    count = None
    if len(cmd) > 2:
        rest = cmd[2:]
        if not rest.isdigit():
            return False, f"bad count: {cmd!r}"
        count = int(rest)
    ok = game.move(src, dst, count)
    return ok, "" if ok else "illegal move"


def apply_spider_command(game: SpiderGame, cmd: str,
                         config: Optional[dict] = None) -> Tuple[bool, str]:
    """Apply a Spider text command. Returns (ok, message)."""
    raw = cmd.strip().lower()
    if not raw:
        return False, ""
    if raw in ("q", "quit", "exit"):
        return True, "__quit__"
    if raw in ("h", "?", "help"):
        return True, SPIDER_HELP_TEXT
    if raw in ("p", ".", "print"):
        return True, "__print__"
    if raw in ("d", "s", "deal", "draw"):
        ok = game.deal()
        return ok, "" if ok else "cannot deal (stock empty or a column is empty)"
    if raw in ("a", "auto"):
        n = game.autofinish()
        return n > 0, f"removed {n} completed suit(s)"
    if raw in ("u", "undo"):
        ok = game.undo()
        return ok, "" if ok else "nothing to undo"
    if raw in ("n", "new"):
        game.new_game()
        return True, "new game"
    if raw in ("o1", "o2", "o4"):
        game.suits = int(raw[1])
        if config is not None:
            config["spider_suits"] = game.suits
            save_config(config)
        game.new_game()
        return True, f"started a new {game.suits}-suit Spider game"

    parts = raw.replace(",", " ").split()
    if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
        src = int(parts[0]) - 1
        dst = int(parts[1]) - 1
        if not (0 <= src <= 9 and 0 <= dst <= 9):
            return False, "columns must be 1-10"
        count = int(parts[2]) if len(parts) == 3 else None
        ok = game.move(tableau_id(src), tableau_id(dst), count)
        return ok, "" if ok else "illegal move"
    return False, f"bad command: {cmd!r} (try h)"


def apply_command(game, cmd: str, config: Optional[dict] = None) -> Tuple[bool, str]:
    """Dispatch a text command to the right per-game parser."""
    if isinstance(game, SpiderGame):
        return apply_spider_command(game, cmd, config)
    return apply_klondike_command(game, cmd, config)


# --------------------------------------------------------------------------- #
# Text REPL (works over a pipe; the curses-free fallback)
# --------------------------------------------------------------------------- #


def run_text(game, symbols: bool = True, stream=None, config: Optional[dict] = None) -> int:
    out = sys.stdout
    inp = stream if stream is not None else sys.stdin
    help_text = SPIDER_HELP_TEXT if isinstance(game, SpiderGame) else HELP_TEXT
    print(f"sol - {game.name} (text mode). Type h for help.\n", file=out)
    print(render(game, symbols), file=out)
    recorded = False
    for raw in inp:
        cmd = raw.strip()
        if not cmd:
            continue
        ok, msg = apply_command(game, cmd, config)
        if msg == "__quit__":
            print("bye", file=out)
            return 0
        if msg == "__print__":
            print(render(game, symbols), file=out)
            continue
        if msg == help_text:
            print(msg, file=out)
            continue
        if msg:
            print(msg, file=out)
        print(render(game, symbols), file=out)
        if game.is_won() and not recorded:
            recorded = True
            rank = record_highscore(game, won=True)
            print("Congratulations - you won!", file=out)
            print(f"Final score {game.score} in {fmt_time(game.elapsed_seconds())} "
                  f"({game.moves} moves).", file=out)
            if rank:
                print(f"New high score - rank #{rank}!", file=out)
            return 0
    return 0


# --------------------------------------------------------------------------- #
# Curses TUI
# --------------------------------------------------------------------------- #


def run_curses(config: dict, start_game=None) -> int:
    import curses

    def main(stdscr) -> int:
        curses.curs_set(0)
        stdscr.keypad(True)
        has_color = curses.has_colors()
        if has_color:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_RED, -1)      # red suits
            curses.init_pair(2, curses.COLOR_WHITE, -1)    # black suits
            curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)  # selection
            curses.init_pair(4, curses.COLOR_CYAN, -1)     # chrome
            curses.init_pair(5, curses.COLOR_YELLOW, -1)   # win / hints

        def CP(n: int) -> int:
            return curses.color_pair(n) if has_color else 0

        def safe_add(y: int, x: int, text: str, attr: int = 0) -> None:
            h, w = stdscr.getmaxyx()
            if 0 <= y < h and 0 <= x < w:
                try:
                    stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
                except curses.error:
                    pass

        def attr_for(card: Optional[Card], selected: bool) -> int:
            if not has_color:
                return curses.A_REVERSE if selected else curses.A_NORMAL
            if selected:
                return CP(3) | curses.A_BOLD
            if card is None or not card.face_up:
                return CP(4)
            return CP(1) if card.is_red else CP(2)

        def cell_text(card: Optional[Card]) -> str:
            if card is None:
                return "[  ]"
            if not card.face_up:
                return "[##]"
            return f"[{card.label():>2}]"

        # ------------------------------------------------------------------ #
        # Main menu
        # ------------------------------------------------------------------ #
        def menu_screen() -> str:
            items = [
                ("New Klondike game", "klondike"),
                ("New Spider game", "spider"),
                ("Options", "options"),
                ("High scores", "scores"),
                ("Quit", "quit"),
            ]
            sel = 0
            while True:
                stdscr.erase()
                safe_add(1, 4, "sol - Command-line Solitaire", CP(4) | curses.A_BOLD)
                safe_add(2, 4, "a replica of /usr/games/sol (AisleRiot)", CP(4))
                for i, (label, _) in enumerate(items):
                    marker = "> " if i == sel else "  "
                    attr = (CP(3) | curses.A_BOLD) if i == sel else 0
                    safe_add(4 + i, 6, f"{marker}{label}", attr)
                draw = config["klondike_draw"]
                suits = config["spider_suits"]
                safe_add(4 + len(items) + 1, 6,
                         f"(Klondike: draw {draw}   Spider: {suits} suit"
                         f"{'s' if suits != 1 else ''})", CP(4))
                safe_add(4 + len(items) + 3, 6,
                         "Up/Down to move, Enter to select, q to quit", CP(4))
                stdscr.refresh()
                key = stdscr.getch()
                if key in (curses.KEY_UP, ord("k")):
                    sel = (sel - 1) % len(items)
                elif key in (curses.KEY_DOWN, ord("j")):
                    sel = (sel + 1) % len(items)
                elif key in (ord("q"), ord("Q")):
                    return "quit"
                elif key in (curses.KEY_ENTER, 10, 13):
                    return items[sel][1]

        # ------------------------------------------------------------------ #
        # Options screen
        # ------------------------------------------------------------------ #
        def options_screen() -> None:
            sel = 0
            while True:
                draw = config["klondike_draw"]
                suits = config["spider_suits"]
                sym = config["symbols"]
                rows = [
                    f"Klondike draw count : {draw}   (Left/Right to change: 1 / 3)",
                    f"Spider suit count   : {suits}   (Left/Right to change: 1 / 2 / 4)",
                    f"Card symbols        : {'unicode ♠♥♦♣' if sym else 'letters S/H/D/C'}",
                    "Back",
                ]
                stdscr.erase()
                safe_add(1, 4, "Options", CP(4) | curses.A_BOLD)
                for i, row in enumerate(rows):
                    marker = "> " if i == sel else "  "
                    attr = (CP(3) | curses.A_BOLD) if i == sel else 0
                    safe_add(3 + i, 6, f"{marker}{row}", attr)
                safe_add(3 + len(rows) + 1, 6,
                         "Changes are saved automatically. Enter/q to go back.", CP(4))
                stdscr.refresh()
                key = stdscr.getch()
                if key in (curses.KEY_UP, ord("k")):
                    sel = (sel - 1) % len(rows)
                elif key in (curses.KEY_DOWN, ord("j")):
                    sel = (sel + 1) % len(rows)
                elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord(" ")):
                    if sel == 0:
                        config["klondike_draw"] = 3 if config["klondike_draw"] == 1 else 1
                    elif sel == 1:
                        cycle = {1: 2, 2: 4, 4: 1}
                        rcycle = {1: 4, 2: 1, 4: 2}
                        config["spider_suits"] = (rcycle if key == curses.KEY_LEFT
                                                  else cycle)[config["spider_suits"]]
                    elif sel == 2:
                        config["symbols"] = not config["symbols"]
                    save_config(config)
                elif key in (curses.KEY_ENTER, 10, 13, ord("q"), ord("Q")):
                    if sel == 3 or key in (ord("q"), ord("Q")):
                        return

        # ------------------------------------------------------------------ #
        # High scores screen
        # ------------------------------------------------------------------ #
        def scores_screen() -> None:
            scores = load_highscores()
            stdscr.erase()
            safe_add(1, 4, "High scores", CP(4) | curses.A_BOLD)
            y = 3
            order = ["klondike-draw1", "klondike-draw3",
                     "spider-1suit", "spider-2suit", "spider-4suit"]
            keys = order + [k for k in scores if k not in order]
            any_shown = False
            for key in keys:
                table = scores.get(key)
                if not table:
                    continue
                any_shown = True
                safe_add(y, 4, key, CP(5) | curses.A_BOLD)
                y += 1
                safe_add(y, 6, f"{'#':>2} {'score':>6} {'time':>6} {'moves':>6}  result  when", CP(4))
                y += 1
                for i, e in enumerate(table[:10]):
                    res = "WON " if e.get("won") else "----"
                    safe_add(y, 6,
                             f"{i + 1:>2} {e.get('score', 0):>6} "
                             f"{fmt_time(e.get('time', 0)):>6} {e.get('moves', 0):>6}  "
                             f"{res}    {e.get('when', '')}")
                    y += 1
                y += 1
                if y > stdscr.getmaxyx()[0] - 3:
                    break
            if not any_shown:
                safe_add(3, 6, "No games finished yet - go win one!", CP(4))
            safe_add(stdscr.getmaxyx()[0] - 2, 4, "Press any key to go back.", CP(4))
            stdscr.refresh()
            stdscr.getch()

        # ------------------------------------------------------------------ #
        # Shared win banner
        # ------------------------------------------------------------------ #
        def win_banner(game) -> None:
            rank = record_highscore(game, won=True)
            stdscr.erase()
            safe_add(2, 6, "*** YOU WIN! ***", CP(5) | curses.A_BOLD)
            safe_add(4, 6, f"Game   : {game.name}")
            safe_add(5, 6, f"Score  : {game.score}")
            safe_add(6, 6, f"Time   : {fmt_time(game.elapsed_seconds())}")
            safe_add(7, 6, f"Moves  : {game.moves}")
            if rank:
                safe_add(9, 6, f"New high score - rank #{rank}!", CP(5) | curses.A_BOLD)
            safe_add(11, 6, "Press any key to return to the menu.", CP(4))
            stdscr.refresh()
            stdscr.getch()

        # ------------------------------------------------------------------ #
        # Klondike play screen
        # ------------------------------------------------------------------ #
        def play_klondike(game: Game) -> None:
            pending: Optional[str] = None
            message = "? for help, m for menu, q to quit."

            def pretty_sel(sel):
                if sel is None:
                    return "none"
                if sel == "w":
                    return "waste"
                if sel.startswith("t"):
                    return f"tableau {int(sel[1:]) + 1}"
                if sel.startswith("f"):
                    return f"foundation {int(sel[1:]) + 1}"
                return sel

            def draw_board():
                stdscr.erase()
                chrome = CP(4)
                safe_add(0, 2, "sol - Klondike", chrome | curses.A_BOLD)
                symbols = config["symbols"]

                safe_add(2, 2, "Stock", chrome)
                stock_card = Card(0, "S", False) if game.stock else None
                safe_add(3, 2, "[##]" if game.stock else "[  ]",
                         attr_for(stock_card, pending == "s"))
                safe_add(4, 2, f" {len(game.stock):>2}", chrome)

                safe_add(2, 9, "Waste", chrome)
                wt = game._waste_top()
                safe_add(3, 9, cell_text(wt), attr_for(wt, pending == "w"))
                safe_add(4, 9, f" {len(game.waste):>2}", chrome)

                safe_add(2, 22, "Foundations", chrome)
                for i, f in enumerate(game.foundations):
                    top = f[-1] if f else None
                    safe_add(3, 22 + i * 6, cell_text(top), attr_for(top, pending == f"f{i}"))

                top_y = 6
                for col in range(7):
                    x = 2 + col * 7
                    safe_add(top_y, x, f" t{col + 1} ", chrome)
                    pile = game.tableau[col]
                    src_sel = pending == f"t{col}"
                    if not pile:
                        safe_add(top_y + 1, x, "[  ]", attr_for(None, src_sel))
                        continue
                    first_up = next((i for i, c in enumerate(pile) if c.face_up), len(pile))
                    for row, card in enumerate(pile):
                        sel = src_sel and row >= first_up
                        safe_add(top_y + 1 + row, x, cell_text(card), attr_for(card, sel))

                h, _ = stdscr.getmaxyx()
                sy = h - 3
                sel_txt = f"selected: {pretty_sel(pending)}" if pending else "no selection"
                safe_add(sy, 2,
                         f"score {game.score}   moves {game.moves}   "
                         f"redeals {game.redeals}   draw {game.draw_count}   "
                         f"time {fmt_time(game.elapsed_seconds())}   {sel_txt}", chrome)
                safe_add(sy + 1, 2, message[: stdscr.getmaxyx()[1] - 4], chrome)
                stdscr.refresh()

            def show_help():
                lines = [
                    "Klondike - controls",
                    "",
                    "  space / d   draw from stock (recycles when empty)",
                    "  1..7        select / target a tableau pile",
                    "  w           select the waste pile",
                    "  f           send selected card to its foundation",
                    "  Esc         clear the current selection",
                    "  a           autofinish to foundations",
                    "  u  undo     n  new game    o  toggle draw 1/3",
                    "  m  menu     ?  help        q  quit",
                    "",
                    "  Pick a source (1-7 or w), then a destination (1-7 or f).",
                    "  Tableau moves carry the whole valid run.",
                    "",
                    "  Press any key to continue.",
                ]
                stdscr.erase()
                for i, ln in enumerate(lines):
                    safe_add(1 + i, 2, ln, curses.A_BOLD if i == 0 else 0)
                stdscr.refresh()
                stdscr.getch()

            def select_source(sel):
                nonlocal pending, message
                if sel == "w" and not game.waste:
                    message = "waste is empty"
                    pending = None
                    return
                if sel.startswith("t") and not game.tableau[int(sel[1:])]:
                    message = "that tableau pile is empty"
                    pending = None
                    return
                pending = sel
                message = ""

            def try_move(dest):
                nonlocal pending, message
                if pending is None:
                    return
                ok = game.move(pending, dest)
                message = "" if ok else "illegal move"
                pending = None

            while True:
                draw_board()
                if game.is_won():
                    win_banner(game)
                    return
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
                    raise _Quit()
                if key in (ord("m"), ord("M")):
                    return
                if key == ord("?"):
                    show_help()
                    continue
                if key == 27:
                    pending = None
                    message = ""
                    continue
                if key in (ord(" "), ord("d"), ord("D")):
                    if not game.draw():
                        message = "nothing to draw"
                    pending = None
                    continue
                if key in (ord("u"), ord("U")):
                    if not game.undo():
                        message = "nothing to undo"
                    pending = None
                    continue
                if key in (ord("a"), ord("A")):
                    n = game.autofinish()
                    message = f"autofinished {n} card(s)" if n else "no card could move up"
                    pending = None
                    continue
                if key in (ord("n"), ord("N")):
                    game.new_game()
                    pending = None
                    message = "new game"
                    continue
                if key in (ord("o"), ord("O")):
                    game.draw_count = 3 if game.draw_count == 1 else 1
                    config["klondike_draw"] = game.draw_count
                    save_config(config)
                    message = f"draw count now {game.draw_count}"
                    continue
                if key in (ord("w"), ord("W")):
                    if pending is None:
                        select_source("w")
                    else:
                        message = "waste cannot be a destination"
                    continue
                if key in (ord("f"), ord("F")):
                    if pending is not None:
                        try_move("f")
                    else:
                        message = "select a card first, then press f"
                    continue
                if ord("1") <= key <= ord("7"):
                    col = key - ord("1")
                    if pending is None:
                        select_source(tableau_id(col))
                    else:
                        try_move(tableau_id(col))
                    continue

        # ------------------------------------------------------------------ #
        # Spider play screen
        # ------------------------------------------------------------------ #
        def play_spider(game: SpiderGame) -> None:
            pending: Optional[int] = None
            message = "? for help, m for menu, q to quit."

            def draw_board():
                stdscr.erase()
                chrome = CP(4)
                safe_add(0, 2, f"sol - Spider ({game.suits} suit"
                         f"{'s' if game.suits != 1 else ''})", chrome | curses.A_BOLD)
                safe_add(2, 2, "Stock", chrome)
                safe_add(3, 2, "[##]" if game.stock else "[  ]",
                         attr_for(Card(0, "S", False) if game.stock else None, False))
                safe_add(4, 2, f" {len(game.stock):>2} ({len(game.stock)//10} deals)", chrome)
                safe_add(2, 22, f"Completed {len(game.completed)}/8", chrome)

                top_y = 6
                for col in range(10):
                    x = 2 + col * 6
                    safe_add(top_y, x, f"{col + 1:>3} ", chrome)
                    pile = game.tableau[col]
                    src_sel = pending == col
                    if not pile:
                        safe_add(top_y + 1, x, "[  ]", attr_for(None, src_sel))
                        continue
                    run = game._movable_run_len(pile)
                    run_start = len(pile) - run
                    for row, card in enumerate(pile):
                        sel = src_sel and row >= run_start
                        safe_add(top_y + 1 + row, x, cell_text(card), attr_for(card, sel))

                h, _ = stdscr.getmaxyx()
                sy = h - 3
                sel_txt = f"selected col {pending + 1}" if pending is not None else "no selection"
                safe_add(sy, 2,
                         f"score {game.score}   moves {game.moves}   "
                         f"time {fmt_time(game.elapsed_seconds())}   {sel_txt}", chrome)
                safe_add(sy + 1, 2, message[: stdscr.getmaxyx()[1] - 4], chrome)
                stdscr.refresh()

            def show_help():
                lines = [
                    "Spider - controls",
                    "",
                    "  space / d   deal a new row (needs no empty column)",
                    "  1..9, 0     select a column (0 = column 10)",
                    "              first key = source, second key = destination",
                    "  Esc         clear the current selection",
                    "  a           auto-remove completed suits",
                    "  u  undo     n  new game",
                    "  m  menu     ?  help        q  quit",
                    "",
                    "  Build down by rank (any suit). A group moves together only",
                    "  if it is a same-suit run. Complete K..A suits clear away.",
                    "",
                    "  Press any key to continue.",
                ]
                stdscr.erase()
                for i, ln in enumerate(lines):
                    safe_add(1 + i, 2, ln, curses.A_BOLD if i == 0 else 0)
                stdscr.refresh()
                stdscr.getch()

            def key_to_col(key):
                if ord("1") <= key <= ord("9"):
                    return key - ord("1")
                if key == ord("0"):
                    return 9
                return None

            while True:
                draw_board()
                if game.is_won():
                    win_banner(game)
                    return
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
                    raise _Quit()
                if key in (ord("m"), ord("M")):
                    return
                if key == ord("?"):
                    show_help()
                    continue
                if key == 27:
                    pending = None
                    message = ""
                    continue
                if key in (ord(" "), ord("d"), ord("D")):
                    if not game.deal():
                        message = "cannot deal (stock empty or a column is empty)"
                    pending = None
                    continue
                if key in (ord("u"), ord("U")):
                    if not game.undo():
                        message = "nothing to undo"
                    pending = None
                    continue
                if key in (ord("a"), ord("A")):
                    n = game.autofinish()
                    message = f"removed {n} suit(s)" if n else "nothing to remove"
                    pending = None
                    continue
                if key in (ord("n"), ord("N")):
                    game.new_game()
                    pending = None
                    message = "new game"
                    continue
                col = key_to_col(key)
                if col is not None:
                    if pending is None:
                        if game.tableau[col]:
                            pending = col
                            message = ""
                        else:
                            message = "that column is empty"
                    else:
                        ok = game.move(tableau_id(pending), tableau_id(col))
                        message = "" if ok else "illegal move"
                        pending = None
                    continue

        # ------------------------------------------------------------------ #
        # Top-level screen loop
        # ------------------------------------------------------------------ #
        def launch(kind: str) -> None:
            if kind == "klondike":
                g = Game(draw_count=config["klondike_draw"])
                g.new_game()
                play_klondike(g)
            elif kind == "spider":
                g = SpiderGame(suits=config["spider_suits"])
                g.new_game()
                play_spider(g)

        try:
            if start_game is not None:
                if isinstance(start_game, SpiderGame):
                    play_spider(start_game)
                else:
                    play_klondike(start_game)
            while True:
                choice = menu_screen()
                if choice == "quit":
                    return 0
                if choice == "options":
                    options_screen()
                elif choice == "scores":
                    scores_screen()
                else:
                    launch(choice)
        except _Quit:
            return 0

    try:
        return curses.wrapper(main)
    except curses.error as exc:
        print(f"curses error: {exc}", file=sys.stderr)
        print("Falling back to text mode.\n", file=sys.stderr)
        g = start_game or Game(draw_count=config["klondike_draw"])
        if start_game is None:
            g.new_game()
        return run_text(g, config["symbols"], config=config)


class _Quit(Exception):
    """Internal signal: leave the curses app entirely."""


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sol",
        description="Command-line Solitaire: Klondike + Spider (a replica of /usr/games/sol).",
    )
    p.add_argument("--game", choices=("klondike", "spider"), default=None,
                   help="which game to start (default: Klondike, or the menu in the TUI)")
    p.add_argument("--draw", type=int, choices=(1, 3), default=None,
                   help="Klondike: cards to draw from the stock at a time")
    p.add_argument("--suits", type=int, choices=(1, 2, 4), default=None,
                   help="Spider: number of suits (1 easiest, 4 hardest)")
    p.add_argument("--seed", type=int, default=None,
                   help="deal a specific (reproducible) shuffle")
    p.add_argument("--text", action="store_true",
                   help="force text mode (no curses); reads commands from stdin")
    p.add_argument("--ascii", action="store_true",
                   help="use letter suits (S/H/D/C) instead of unicode symbols")
    p.add_argument("--scores", action="store_true",
                   help="print the saved high scores and exit")
    p.add_argument("--reset-scores", action="store_true",
                   help="erase all saved high scores and exit")
    return p


def print_scores() -> None:
    scores = load_highscores()
    if not scores:
        print("No high scores yet.")
        return
    order = ["klondike-draw1", "klondike-draw3",
             "spider-1suit", "spider-2suit", "spider-4suit"]
    keys = order + [k for k in scores if k not in order]
    for key in keys:
        table = scores.get(key)
        if not table:
            continue
        print(f"\n{key}")
        print(f"  {'#':>2} {'score':>6} {'time':>6} {'moves':>6}  result  when")
        for i, e in enumerate(table[:10]):
            res = "WON " if e.get("won") else "----"
            print(f"  {i + 1:>2} {e.get('score', 0):>6} "
                  f"{fmt_time(e.get('time', 0)):>6} {e.get('moves', 0):>6}  "
                  f"{res}    {e.get('when', '')}")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()

    if args.reset_scores:
        save_highscores({})
        print("High scores cleared.")
        return 0
    if args.scores:
        print_scores()
        return 0

    # CLI overrides update the running config (and are persisted on change).
    if args.draw is not None:
        config["klondike_draw"] = args.draw
    if args.suits is not None:
        config["spider_suits"] = args.suits
    if args.ascii:
        config["symbols"] = False
    symbols = config["symbols"]

    # Decide whether we have an explicit game to start.
    game = None
    if args.game == "spider":
        game = SpiderGame(suits=config["spider_suits"], seed=args.seed)
        game.new_game()
    elif args.game == "klondike" or args.seed is not None or args.text:
        game = Game(draw_count=config["klondike_draw"], seed=args.seed)
        game.new_game()

    use_curses = not args.text and sys.stdout.isatty() and sys.stdin.isatty()
    if use_curses:
        try:
            import curses  # noqa: F401
        except Exception:
            use_curses = False

    if use_curses:
        return run_curses(config, start_game=game)

    if game is None:
        game = Game(draw_count=config["klondike_draw"], seed=args.seed)
        game.new_game()
    return run_text(game, symbols, config=config)


if __name__ == "__main__":
    sys.exit(main())
