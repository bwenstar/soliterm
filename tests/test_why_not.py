"""Why a move was refused: the reason after "illegal move: " in both front ends."""

import io
import itertools
import random

import pytest

from soliterm import textmode
from soliterm.engine import GAMES, Card, GameDef
from soliterm.engine.core import REFUSED
from soliterm.textmode import apply_text_command
from soliterm.tui.app import App

from helpers import FakeScr, clear_board, deal

# The message line at 80 columns with the code skin on
WIDTH = 72
PREFIX = "illegal move: "
KINDS = {
    "s": "stock",
    "w": "waste",
    "f": "foundation",
    "t": "tableau",
    "c": "freecell",
    "r": "reserve",
}
RANKS = {"A": 1, "J": 11, "Q": 12, "K": 13}


def cards(text):
    """The cards in 'KS QH ~5D', each face up, or face down after a ~."""
    out = []
    for token in text.split():
        name = token.lstrip("~")
        rank = RANKS.get(name[:-1]) or int(name[:-1])
        out.append(Card(rank, name[-1], name == token))
    return out


def board(key, base=None, **piles):
    """A deal of key with every slot emptied, then the piles given laid out
    by kind in slot order, as in tableau=["9S 8H", "", "10D"]. base sets
    Canfield's base rank."""
    g = deal(key, 1)
    clear_board(g)
    for kind, texts in piles.items():
        for sid, text in zip(g.ids_of(kind), texts):
            g.slots[sid].cards = cards(text)
    if base is not None:
        g.base_val = base
    g.symbols = False
    return g


def where(g, move):
    """The (src, dst, n) of a move like "t0 f1" (the first column to the
    second foundation) or "t0 t1 2" (two cards)."""
    parts = move.split()
    src, dst = (g.ids_of(KINDS[p[0]])[int(p[1:])] for p in parts[:2])
    return src, dst, int(parts[2]) if len(parts) == 3 else None


def refused(g, src, dst, n):
    """Whether a move is refused, the way a bare '<src> <dst>' is when n is
    None: the longest run first, then the shorter ones off its top."""
    sim = g.clone()
    if n is not None:
        return not sim.attempt_move(src, dst, n)
    tries = range(max(1, g.default_pickup(src)), 0, -1) if g.cards(src) else [None]
    return not any(sim.attempt_move(src, dst, k) for k in tries)


# The full column of each foundation filled King high, as board() takes it
HEARTS = "AH 2H 3H 4H 5H 6H 7H 8H 9H 10H JH QH KH"
# Columns with cards on them, to fill the rest of the tableau
FULL = ["KC", "KD", "KS", "KH", "QC", "QD", "QS", "QH", "JC", "JD", "JS"]
# The pyramid down to its bottom row, empty, so the cards given next are
# on that row, where nothing covers them
ABOVE = [""] * 21

CASES = {
    "klondike": [
        ({"tableau": ["", "5H"]}, "t0 t1", "nothing there to move"),
        ({"tableau": ["5C"]}, "t0 t0", "the cards are there already"),
        ({"tableau": ["5C", "6H"]}, "t0 t1 0", "a move takes at least one card"),
        ({"tableau": ["5C", "6H"]}, "t0 t1 3", "there is only 1 card there"),
        ({"tableau": ["5C 4H", "6H"]}, "t0 t1 5", "there are only 2 cards there"),
        ({"tableau": ["~9C 8S", "9D"]}, "t0 t1 2", "a face-down card can't be moved"),
        ({"tableau": ["~5C", "6H"]}, "t0 t1", "a face-down card can't be moved"),
        (
            {"tableau": ["9S 8H 5C", "10D"]},
            "t0 t1 3",
            "5C doesn't build on 8H, so they can't move together",
        ),
        ({"tableau": ["8S 7H", "5D"]}, "t0 t1", "8S doesn't go on 5D, which takes a black 4"),
        ({"tableau": ["8S 7H", "5D"]}, "t0 t1 1", "7H doesn't go on 5D, which takes a black 4"),
        ({"tableau": ["8H", "9D"]}, "t0 t1", "8H doesn't go on 9D, which takes a black 8"),
        ({"tableau": ["JH", "KS"]}, "t0 t1", "JH doesn't go on KS, which takes a red Queen"),
        ({"tableau": ["2S", "AH"]}, "t0 t1", "nothing builds on AH"),
        ({"tableau": ["QS", ""]}, "t0 t1", "an empty column takes only a King"),
        ({"tableau": ["QS", "~KH"]}, "t0 t1", "nothing goes on a face-down card"),
        (
            {"tableau": ["6H"], "foundation": ["AH 2H 3H 4H"]},
            "t0 f0",
            "6H doesn't go on 4H, which takes 5H next",
        ),
        (
            {"tableau": ["5S"], "foundation": ["AH 2H 3H 4H"]},
            "t0 f0",
            "5S doesn't go on 4H, which takes 5H next",
        ),
        ({"tableau": ["2H"]}, "t0 f0", "an empty foundation takes only an Ace"),
        (
            {"tableau": ["3H 2S"], "foundation": ["AS"]},
            "t0 f0 2",
            "cards go up to a foundation one at a time",
        ),
        ({"tableau": ["AS"], "foundation": [HEARTS]}, "t0 f0", "that foundation is complete"),
        (
            {"foundation": ["AH", ""]},
            "f0 f1",
            "a card can't move from one foundation to another",
        ),
        (
            {"foundation": ["AH 2H"], "tableau": ["3S"]},
            "f0 t0 2",
            "only the top card of a foundation can move",
        ),
        (
            {"waste": ["5C 6D"], "tableau": ["7C"]},
            "w0 t0 2",
            "only the top card of the waste can move",
        ),
        ({"tableau": ["5C"]}, "t0 s0", "nothing goes on the stock"),
        ({"tableau": ["5C"]}, "t0 w0", "nothing goes on the waste"),
        ({"stock": ["~5C"], "tableau": ["6H"]}, "s0 t0", "cards in the stock can only be dealt"),
    ],
    "spider": [
        (
            {"tableau": ["7H 6S 5S", "8D"]},
            "t0 t1 3",
            "7H and 6S aren't one suit, so they can't move together",
        ),
        ({"tableau": ["7H 6S 5S", "8D"]}, "t0 t1", "6S doesn't go on 8D, which takes any 7"),
        (
            {"tableau": ["9S 6S", "10D"]},
            "t0 t1 2",
            "6S doesn't build on 9S, so they can't move together",
        ),
        ({"tableau": ["JS", "KH"]}, "t0 t1 1", "JS doesn't go on KH, which takes any Queen"),
        ({"tableau": ["5S", "AH"]}, "t0 t1", "nothing builds on AH"),
        ({"tableau": ["~5S 4S", "6H"]}, "t0 t1 2", "a face-down card can't be moved"),
        (
            {"tableau": ["KS"]},
            "t0 f0",
            "a King-to-Ace run in one suit goes up by itself",
        ),
        (
            {"foundation": ["KS QS JS 10S 9S 8S 7S 6S 5S 4S 3S 2S AS"], "tableau": ["2H"]},
            "f0 t0",
            "a finished run stays on its foundation",
        ),
        ({"tableau": ["5S"]}, "t0 s0", "nothing goes on the stock"),
        ({"stock": ["~5S"], "tableau": ["6S"]}, "s0 t0", "cards in the stock can only be dealt"),
    ],
    "spiderette": [
        ({"tableau": ["5S", "9H"]}, "t0 t1", "5S doesn't go on 9H, which takes any 8"),
        (
            {"tableau": ["8H 7S", "9H"]},
            "t0 t1 2",
            "8H and 7S aren't one suit, so they can't move together",
        ),
        (
            {"tableau": ["KS"]},
            "t0 f0",
            "a King-to-Ace run in one suit goes up by itself",
        ),
    ],
    "freecell": [
        (
            {"freecell": ["2C", "3C", "4C"], "tableau": ["9S 8H 7C", "10D", *FULL[:6]]},
            "t0 t1",
            "up to 2 cards with 1 free cell and no empty columns",
        ),
        (
            {"freecell": ["2C", "3C", "4C", "5C"], "tableau": ["9S 8H 7C", "10D", "", *FULL[:5]]},
            "t0 t1",
            "up to 2 cards with no free cells and 1 empty column",
        ),
        (
            {"tableau": ["QH JC 10D 9S 8H 7C 6D 5S 4H 3C 2D", "KS", "", *FULL[:5]]},
            "t0 t1",
            "up to 10 cards with 4 free cells and 1 empty column",
        ),
        (
            {"freecell": ["2C", "3C", "4C", "5C"], "tableau": ["9S 8H 7C", "", *FULL[:6]]},
            "t0 t1 3",
            "up to 1 card with no free cells and no other empty columns",
        ),
        (
            {"freecell": ["2C", "3C", "4C", "5C"], "tableau": ["9S 8H 7C", "5D", *FULL[:6]]},
            "t0 t1",
            "9S doesn't go on 5D, which takes a black 4",
        ),
        ({"foundation": ["AH"], "tableau": ["2S"]}, "f0 t0", "cards on the foundations stay there"),
        ({"tableau": ["5C"], "freecell": ["2H"]}, "t0 c0", "that free cell is full"),
        ({"tableau": ["5C 4H"]}, "t0 c0 2", "a free cell holds one card"),
        (
            {"tableau": ["3H 2S"], "foundation": ["AS"]},
            "t0 f0 2",
            "cards go up to a foundation one at a time",
        ),
        (
            {"tableau": ["3S"], "foundation": ["AH 2H"]},
            "t0 f0",
            "3S doesn't go on 2H, which takes 3H next",
        ),
        (
            {"freecell": ["5H"], "tableau": ["6H"]},
            "c0 t0",
            "5H doesn't go on 6H, which takes a black 5",
        ),
    ],
    "eightoff": [
        (
            {
                "freecell": ["2C", "3C", "4C", "5C", "6C", "7C"],
                "tableau": ["9H 8H 7H 6H", "10H", *FULL[:6]],
            },
            "t0 t1 4",
            "up to 3 cards with 2 free cells",
        ),
        (
            {
                "freecell": ["2C", "3C", "4C", "5C", "6C", "7C"],
                "tableau": ["9H 8H 7H 6H", "10H", "", *FULL[:5]],
            },
            "t0 t1 4",
            "up to 3 cards with 2 free cells - empty columns don't help",
        ),
        (
            {"freecell": ["2C", "3C", "4C", "5C", "6C", "7C", "8C", "9C"], "tableau": ["9H 8H"]},
            "t0 t1 2",
            "up to 1 card with no free cells - empty columns don't help",
        ),
        ({"tableau": ["QH", ""]}, "t0 t1", "an empty column takes only a King"),
        ({"tableau": ["9S", "10H"]}, "t0 t1", "9S doesn't go on 10H, which takes 9H"),
        (
            {"tableau": ["9H 8S", "10H"]},
            "t0 t1 2",
            "8S doesn't build on 9H, so they can't move together",
        ),
        (
            {"foundation": ["AH", ""]},
            "f0 f1",
            "a card can't move from one foundation to another",
        ),
        ({"tableau": ["5C"], "freecell": ["2H"]}, "t0 c0", "that free cell is full"),
        ({"tableau": ["2H"]}, "t0 f0", "an empty foundation takes only an Ace"),
    ],
    "golf": [
        ({"waste": ["5H"], "tableau": ["9C"]}, "t0 w0", "only a 4 or a 6 goes on 5H"),
        ({"waste": ["QH"], "tableau": ["9C"]}, "t0 w0", "only a Jack or a King goes on QH"),
        ({"waste": ["9H"], "tableau": ["2C"]}, "t0 w0", "only an 8 or a 10 goes on 9H"),
        (
            {"waste": ["KH"], "tableau": ["AC"]},
            "t0 w0",
            "nothing goes on KH - ranks don't wrap round in Golf",
        ),
        (
            {"waste": ["AH"], "tableau": ["KC"]},
            "t0 w0",
            "only a 2 goes on AH - ranks don't wrap round in Golf",
        ),
        ({"tableau": ["5C"]}, "t0 w0", "the waste is empty - deal from the stock first"),
        ({"tableau": ["5C", "6H"]}, "t0 t1", "cards never go from one column to another"),
        ({"waste": ["5H"], "tableau": ["6C"]}, "w0 t0", "nothing comes back off the waste"),
        ({"waste": ["5H"], "tableau": ["9C 4D"]}, "t0 w0 2", "cards go to the waste one at a time"),
        ({"tableau": ["5C"]}, "t0 s0", "nothing goes on the stock"),
        ({"stock": ["~5C"], "waste": ["6H"]}, "s0 w0", "cards in the stock can only be dealt"),
    ],
    "triplepeaks": [
        ({"waste": ["KH"], "tableau": ["2C"]}, "t0 w0", "only a Queen or an Ace goes on KH"),
        ({"waste": ["AH"], "tableau": ["3C"]}, "t0 w0", "only a King or a 2 goes on AH"),
        ({"waste": ["7H"], "tableau": ["2C"]}, "t0 w0", "only a 6 or an 8 goes on 7H"),
        (
            {"waste": ["6H"], "tableau": ["~5C"]},
            "t0 w0",
            "a face-down card stays until both cards over it are gone",
        ),
        ({"tableau": ["5C", "6H"]}, "t0 t1", "nothing moves between the peaks"),
        ({"waste": ["5H"], "tableau": [""]}, "w0 t0", "nothing comes back off the waste"),
        ({"waste": ["5H"], "tableau": ["9C"]}, "t0 s0", "nothing goes on the stock"),
    ],
    "yukon": [
        ({"foundation": ["AH"], "tableau": ["2S"]}, "f0 t0", "cards on the foundations stay there"),
        ({"tableau": ["~5S 8H", "10C"]}, "t0 t1 2", "a face-down card can't be moved"),
        ({"tableau": ["8H 2C", "10C"]}, "t0 t1", "8H doesn't go on 10C, which takes a red 9"),
        ({"tableau": ["QH 5S", ""]}, "t0 t1", "an empty column takes only a King"),
        (
            {"tableau": ["2H AH"]},
            "t0 f0 2",
            "cards go up to a foundation one at a time",
        ),
        (
            {"tableau": ["3H"], "foundation": ["AH"]},
            "t0 f0",
            "3H doesn't go on AH, which takes 2H next",
        ),
    ],
    "scorpion": [
        ({"tableau": ["8H 2C", "10H"]}, "t0 t1", "8H doesn't go on 10H, which takes 9H"),
        ({"tableau": ["QH", ""]}, "t0 t1", "an empty column takes only a King"),
        ({"tableau": ["5H", "AH"]}, "t0 t1", "nothing builds on AH"),
        ({"tableau": ["~5S 8H", "9H"]}, "t0 t1 2", "a face-down card can't be moved"),
        ({"tableau": ["5H"]}, "t0 s0", "nothing goes on the stock"),
        ({"stock": ["~5C"], "tableau": ["6H"]}, "s0 t0", "cards in the stock can only be dealt"),
    ],
    "bakersdozen": [
        ({"tableau": ["5H", ""]}, "t0 t1", "an empty column can't be filled again"),
        ({"tableau": ["5H", "7C"]}, "t0 t1", "5H doesn't go on 7C, which takes any 6"),
        ({"tableau": ["5H 4C", "5D"]}, "t0 t1 2", "cards move one at a time in Bakers Dozen"),
        (
            {"foundation": ["AH", ""]},
            "f0 f1",
            "a card can't move from one foundation to another",
        ),
        (
            {"tableau": ["3H"], "foundation": ["AH"]},
            "t0 f0",
            "3H doesn't go on AH, which takes 2H next",
        ),
        (
            {"foundation": ["AH 2H"], "tableau": ["4S"]},
            "f0 t0",
            "2H doesn't go on 4S, which takes any 3",
        ),
    ],
    "fortythieves": [
        (
            {"tableau": ["9H 8H 7H", "10H", *FULL[:8]]},
            "t0 t1",
            "up to 1 card with no empty columns",
        ),
        (
            {"tableau": ["9H 8H 7H", "10H", "", *FULL[:7]]},
            "t0 t1",
            "up to 2 cards with 1 empty column",
        ),
        (
            {"tableau": ["9H 8H", "", *FULL[:8]]},
            "t0 t1 2",
            "up to 1 card with no other empty columns",
        ),
        (
            {"tableau": ["4S 3S 2S"], "foundation": ["AH"]},
            "t0 f0",
            "a run goes up from its top card, and 2S doesn't go on AH",
        ),
        (
            {"tableau": ["2S"], "foundation": ["AH"]},
            "t0 f0",
            "2S doesn't go on AH, which takes 2H next",
        ),
        ({"tableau": ["3S 2S"]}, "t0 f0", "an empty foundation takes only an Ace"),
        ({"tableau": ["AS"], "foundation": [HEARTS]}, "t0 f0", "that foundation is complete"),
        ({"foundation": ["AH"], "tableau": ["2S"]}, "f0 t0", "cards on the foundations stay there"),
        (
            {"tableau": ["9H 8S", "10H"]},
            "t0 t1 2",
            "8S doesn't build on 9H, so they can't move together",
        ),
        ({"tableau": ["9S", "10H"]}, "t0 t1", "9S doesn't go on 10H, which takes 9H"),
        ({"tableau": ["9S"]}, "t0 w0", "nothing goes on the waste"),
        (
            {"waste": ["5C 6D"], "tableau": ["7D"]},
            "w0 t0 2",
            "only the top card of the waste can move",
        ),
    ],
    "canfield": [
        (
            {"tableau": ["5H"]},
            "t0 f0",
            "an empty foundation takes only a Queen, the base rank",
        ),
        (
            {"foundation": ["QH"], "tableau": ["KS"]},
            "f0 t0",
            "QH started that foundation, so it stays there",
        ),
        (
            {"tableau": ["2H"], "foundation": ["QH KH"]},
            "t0 f0",
            "2H doesn't go on KH, which takes AH next",
        ),
        ({"tableau": ["QH", "AS"]}, "t0 t1", "QH doesn't go on AS, which takes a red King"),
        (
            {"tableau": ["AS KH 5C", "2H"]},
            "t0 t1 3",
            "5C doesn't build on KH, so they can't move together",
        ),
        (
            {"foundation": ["QH KH AH 2H 3H 4H 5H 6H 7H 8H 9H 10H JH"], "tableau": ["QS"]},
            "t0 f0",
            "that foundation is complete",
        ),
        ({"tableau": ["5H"], "reserve": ["~2C 3D"]}, "t0 r0", "nothing goes on the reserve"),
        ({"tableau": ["5H"], "reserve": ["~2C 3D"]}, "r0 t0 2", "a face-down card can't be moved"),
        ({"tableau": ["5H"]}, "t0 w0", "nothing goes on the waste"),
        (
            {"waste": ["5C 6D"], "tableau": ["7C"]},
            "w0 t0 2",
            "only the top card of the waste can move",
        ),
    ],
    "pyramid": [
        ({"tableau": [*ABOVE, "5S", "7H"]}, "t21 t22", "5S and 7H make 12, not 13"),
        ({"waste": ["6D"], "tableau": [*ABOVE, "9C"]}, "t21 w0", "9C and 6D make 15, not 13"),
        ({"waste": ["6D"], "tableau": [*ABOVE, "9C"]}, "w0 t21", "6D and 9C make 15, not 13"),
        ({"tableau": [*ABOVE, "KS", "AH"]}, "t22 t21", "a King goes off on its own, not in a pair"),
        ({"tableau": [*ABOVE, "KS", "AH"]}, "t21 t22", "a King goes off on its own, not in a pair"),
        (
            {"tableau": ["~8S", *ABOVE[1:], "5H"]},
            "t0 t21",
            "a face-down card stays until both cards over it are gone",
        ),
        (
            {"tableau": ["~8S", *ABOVE[1:], "5H"]},
            "t21 t0",
            "a face-down card can't pair until both cards over it go",
        ),
        ({"tableau": [*ABOVE, "", "5H"]}, "t22 t21", "there's no card there to pair with"),
        (
            {"tableau": [*ABOVE, "5H"]},
            "t21 w0",
            "the waste is empty - deal from the stock first",
        ),
        ({"tableau": [*ABOVE, "5H"]}, "t21 f0", "5H only goes in a pair making 13"),
        ({"waste": ["5H"]}, "w0 f0", "5H only goes in a pair making 13"),
        ({"waste": ["3S 5H"]}, "w0 f0", "5H and 3S make 8, not 13"),
        (
            {"waste": ["8C 5H"], "tableau": [*ABOVE, "7D"]},
            "w0 t21 2",
            "only the top card of the waste can move",
        ),
        ({"foundation": ["KS"], "tableau": [*ABOVE, "5H"]}, "f0 t21", "cards taken off stay off"),
        ({"stock": ["~5C"], "waste": ["6H"]}, "s0 w0", "cards in the stock can only be dealt"),
        ({"tableau": [*ABOVE, "5H"]}, "t21 s0", "nothing goes on the stock"),
    ],
}


@pytest.mark.parametrize(
    "key, piles, move, want",
    [(key, *case) for key, cases in CASES.items() for case in cases],
)
def test_a_refused_move_says_why(key, piles, move, want):
    g = board(key, base=12 if key == "canfield" else None, **piles)
    src, dst, n = where(g, move)
    before = g.serialize()
    assert refused(g, src, dst, n)
    assert g.why_not(src, dst, n) == want
    assert g.serialize() == before
    assert len(PREFIX + want) <= WIDTH


def test_every_game_says_why_by_its_own_rules():
    # a new game needs cases here, and a why_not of its own unless it
    # plays by the rules the default knows, Klondike's
    assert set(CASES) == set(GAMES)
    common = {key for key, cls in GAMES.items() if cls.why_not is GameDef.why_not}
    assert common == {"klondike"}


def test_the_reasons_name_cards_the_way_the_board_does():
    g = board("klondike", tableau=["8S 7H", "5D"])
    t = g.ids_of("tableau")
    assert g.why_not(t[0], t[1]) == "8S doesn't go on 5D, which takes a black 4"
    g.symbols = True
    assert g.why_not(t[0], t[1]) == "8♠ doesn't go on 5♦, which takes a black 4"


def test_the_freecell_limit_fits_the_message_line_however_it_comes():
    # a run is K to A at most, so the longest a limit stops is 12 cards
    # onto a King or 13 into an empty column; whatever the free cells and
    # empty columns, the reason fits
    for cells, columns, into_empty in itertools.product(range(5), range(4), [False, True]):
        limit = (cells + 1) * 2**columns
        n = 13 if into_empty else 12
        if limit >= n:
            continue
        g = board(
            "freecell",
            freecell=["2C"] * (4 - cells),
            tableau=[
                "KS QH JC 10D 9S 8H 7C 6D 5S 4H 3C 2D AS",
                "" if into_empty else "KC",
                *[""] * columns,
                *FULL[: 6 - columns],
            ],
        )
        src, dst = g.ids_of("tableau")[:2]
        assert refused(g, src, dst, n)
        why = g.why_not(src, dst, n)
        assert why.startswith(f"up to {limit} card"), why
        assert len(PREFIX + why) <= WIDTH, why


# Positions per game for the sweep, the most moves into one deal, and the
# positions a move off the hint's line looked at from each on it
SWEEP = 200
STEPS = 40
BRANCH = 6


def positions(key):
    """SWEEP positions of key met playing seeded deals forward with the
    hint, and a few a legal move away from each."""
    rng = random.Random(key)
    found = []
    seed = 0
    while len(found) < SWEEP:
        g = deal(key, seed)
        seed += 1
        for _ in range(STEPS):
            found.append(g.clone())
            moves = g.legal_moves()
            for move in rng.sample(moves, min(BRANCH, len(moves))):
                off = g.clone()
                off.attempt_move(*move)
                found.append(off)
            mv = None if g.is_won() else g.hint_move()
            if mv is None:
                break
            if mv[0] == mv[1]:
                g.deal()
            else:
                g.attempt_move(*mv)
    return found[:SWEEP]


def hidden_moved(g):
    """g with its face-down cards moved round one place each, so a reason
    that gave one of them away would change, or None with too few to move."""
    sim = g.clone()
    spots = [(s.sid, i) for s in sim.slots for i, c in enumerate(s.cards) if not c.face_up]
    hidden = [sim.slots[sid].cards[i] for sid, i in spots]
    if len(set(hidden)) < 2:
        return None
    for (sid, i), card in zip(spots, hidden[1:] + hidden[:1]):
        sim.slots[sid].cards[i] = card
    return sim


def refusals(g, every_size):
    """The (src, dst, n) of every move g refuses from a slot with cards on
    it: the run a bare move tries, when every shorter one off its top is
    refused too, and with every_size each other size of run as well."""
    legal = set(g.legal_moves())
    out = set()
    for src in range(len(g.slots)):
        if g.empty(src):
            continue
        longest = g.default_pickup(src)
        sizes = range(1, len(g.cards(src)) + 1) if every_size else []
        for dst in range(len(g.slots)):
            if src == dst:
                continue
            if not any((src, dst, k) in legal for k in range(1, longest + 1)):
                out.add((src, dst, longest or 1))
            out.update((src, dst, n) for n in sizes if (src, dst, n) not in legal)
    return out


@pytest.mark.parametrize("key", list(GAMES))
def test_every_move_refused_in_play_says_why(key):
    seen = 0
    for i, g in enumerate(positions(key)):
        g.symbols = True
        other = hidden_moved(g)
        # every size of run on some boards, the run a bare move tries on all
        for src, dst, n in refusals(g, every_size=i % 20 == 0):
            why = g.why_not(src, dst, n)
            assert why and why != REFUSED, (key, i, src, dst, n)
            assert len(PREFIX + why) <= WIDTH, why
            # nothing in it hangs on a face-down card
            if other:
                assert other.why_not(src, dst, n) == why, (key, i, src, dst, n)
            seen += 1
    assert seen > 1000


def test_a_bare_move_is_refused_for_the_longest_run():
    g = board("klondike", tableau=["9S 8H 7C", "5D"])
    t = g.ids_of("tableau")
    assert g.why_not(t[0], t[1]) == g.why_not(t[0], t[1], 3)
    g = board("klondike", tableau=["~9S", "5D"])
    assert g.why_not(t[0], t[1]) == g.why_not(t[0], t[1], 1)


# -- the front ends ------------------------------------------------------------------


def test_text_mode_says_why_about_the_run_a_bare_move_tries():
    # the whole run is what's refused, not the 7H tried after it
    g = board("klondike", tableau=["8S 7H", "5D"])
    t = g.ids_of("tableau")
    assert apply_text_command(g, f"{t[0]} {t[1]}") == (
        False,
        "illegal move: 8S doesn't go on 5D, which takes a black 4",
    )
    assert apply_text_command(g, f"{t[0]} {t[1]} 1") == (
        False,
        "illegal move: 7H doesn't go on 5D, which takes a black 4",
    )


def test_text_mode_says_why_with_the_letters_ascii_gives(capsys):
    g = deal("klondike", 1)
    textmode.run_text(g, False, "klondike", stream=io.StringIO("7 8\nq\n"))
    assert "illegal move: 8D doesn't go on 10D, which takes a black 9" in capsys.readouterr().out


@pytest.mark.parametrize("key", list(GAMES))
def test_both_front_ends_say_why_in_every_game(key):
    # each case a bare move makes from a slot the board can pick up from,
    # typed in text mode, and picked up and dropped in the full-screen game
    seen = 0
    for piles, move, want in CASES[key]:
        g = board(key, base=12 if key == "canfield" else None, **piles)
        src, dst, n = where(g, move)
        if n is not None or g.default_pickup(src) <= 0:
            continue
        assert apply_text_command(g.clone(), f"{src} {dst}") == (False, PREFIX + want)
        app = App(FakeScr(40, 120), symbols=False)
        app.start_game(key)
        for slot in g.slots:
            app.game.slots[slot.sid].cards = list(slot.cards)
        app.game.base_val = g.base_val
        app.select_here(src)
        app.drop_on(dst)
        assert app.message == PREFIX + want
        seen += 1
    assert seen
