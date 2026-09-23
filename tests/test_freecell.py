"""FreeCell and Eight Off: the cells, group moves and the foundations."""

import pytest

from soliterm.engine import Card
from helpers import clear_board, deal


def up(rank, suit):
    return Card(rank, suit, True)


@pytest.fixture
def freecell():
    g = deal("freecell", 1)
    clear_board(g)
    return g, g.ids_of("freecell"), g.ids_of("foundation"), g.ids_of("tableau")


def test_freecell_foundation_cards_are_out_of_play(freecell):
    g, c, f, t = freecell
    g.slots[f[0]].cards = [up(1, "S"), up(2, "S")]
    g.slots[t[0]].cards = [up(3, "H")]
    g.score = 2
    assert not g.can_pickup(f[0], 1)
    assert g.default_pickup(f[0]) == 0
    for dst in (t[0], t[1], c[0], f[1]):
        assert g.attempt_move(f[0], dst, 1) is False
    assert all(g.kind(src) != "foundation" for src, _, _ in g.legal_moves())
    assert [str(x) for x in g.cards(f[0])] == ["AS", "2S"]
    assert g.score == 2
