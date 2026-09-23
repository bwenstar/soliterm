"""Text mode: the board it prints and the commands it takes."""

import re

import pytest

from soliterm import textmode
from soliterm.engine import GAME_ORDER
from soliterm.textmode import render_text
from helpers import deal

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def played(key, seed, steps=40):
    """A game some hint moves in, so there are foundations, fans and 10s about."""
    g = deal(key, seed)
    for _ in range(steps):
        h = g.hint()
        if h is None:
            break
        if h[0] == h[1]:
            g.deal()
        else:
            g.attempt_move(*g.best_move())
    return g


def blocks(board):
    """The board's slot rows as (tag line, card lines), status line left out."""
    lines = board.splitlines()[1:-1]
    out, cur = [], []
    for line in lines + [""]:
        if line:
            cur.append(line)
        elif cur:
            out.append((cur[0], cur[1:]))
            cur = []
    return out


def ends(line):
    """Where each card token, tag or count on a line ends."""
    return [m.end() for m in re.finditer(r"\[[^\]]*\]|\S+", line)]


# -- the board ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("key", GAME_ORDER)
def test_cards_line_up_under_their_tags(key, seed):
    g = played(key, seed)
    board = ANSI.sub("", render_text(g, symbols=True, color=True))
    for tags, rows in blocks(board):
        edges = ends(tags)
        # a fan shows several cards in one slot, but the top one sits under the tag
        assert set(edges) <= set(ends(rows[0])), board
        for row in rows[1:]:
            assert set(ends(row)) <= set(edges), board
        for row in rows:
            assert all(len(t) == 5 for t in re.findall(r"\[[^\]]*\]", row)), board


KIND_TAG = {"stock": "stk", "waste": "wst", "foundation": "fnd", "freecell": "cel",
            "reserve": "rsv", "tableau": ""}


@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_slot_shows_its_id_and_kind(key):
    g = deal(key, 1)
    board = render_text(g, symbols=False)
    shown = {int(sid): kind for kind, sid in re.findall(r"([a-z]*)#(\d+)", board)}
    assert shown == {s.sid: KIND_TAG[s.kind] for s in g.slots}


@pytest.mark.parametrize("key", GAME_ORDER)
def test_a_hint_names_the_slots_as_the_board_does(key):
    g = deal(key, 1)
    tags = set(re.findall(r"[a-z]*#\d+", render_text(g, symbols=False)))
    for _ in range(30):
        h = g.hint()
        if h is None:
            break
        if h[0] == h[1]:
            g.deal()
            continue
        msg = textmode._hint_message(g)
        named = re.findall(r"[a-z]*#\d+", msg)
        assert named == [textmode.slot_tag(g, h[0]), textmode.slot_tag(g, h[1])], msg
        assert set(named) <= tags, msg
        g.attempt_move(*g.best_move())
