"""FreeCell and Eight Off: the cells, group moves and the foundations."""

import pytest

from soliterm.engine import Card

from helpers import clear_board, deal


def up(rank, suit):
    return Card(rank, suit, True)


def test_the_deal_is_microsofts():
    # Microsoft FreeCell's deal 617, read across a row at a time (T is a ten)
    g = deal("freecell", 617)
    columns = [[str(c).replace("10", "T") for c in g.cards(t)] for t in g.ids_of("tableau")]
    rows = [" ".join(col[i] for col in columns if i < len(col)) for i in range(7)]
    assert rows == [
        "7D AD 5C 3S 5S 8C 2D AH",
        "TD 7S QD AC 6D 8H AS KH",
        "TH QC 3H 9D 6S 8D 3D TC",
        "KD 5H 9S 3C 8S 7H 4D JS",
        "4C QS 9C 9H 7C 6H 2C 2S",
        "4S TS 2H 5D JC 6C JH QH",
        "JD KS KC 4H",
    ]


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


@pytest.fixture
def eightoff():
    g = deal("eightoff", 1)
    clear_board(g)
    return g, g.ids_of("freecell"), g.ids_of("tableau")


def test_eightoff_moves_a_group_of_free_cells_plus_one(eightoff):
    # one free cell and two empty columns: two cards at most, since an
    # empty column only takes a King and can't hold part of the group
    g, c, t = eightoff
    for i in range(7):
        g.slots[c[i]].cards = [up(2 + i, "C")]
    for x in t[3:]:
        g.slots[x].cards = [up(9, "S")]
    g.slots[t[0]].cards = [up(5, "D"), up(13, "H"), up(12, "H"), up(11, "H")]
    assert not g.can_pickup(t[0], 3)
    assert g.default_pickup(t[0]) == 2
    assert g.attempt_move(t[0], t[1], 3) is False
    assert max(n for _, _, n in g.legal_moves()) == 1
    g.slots[t[0]].cards = [up(5, "D"), up(13, "H"), up(12, "H")]
    assert g.attempt_move(t[0], t[1], 2)
    assert [str(x) for x in g.cards(t[1])] == ["KH", "QH"]


def test_eightoff_group_grows_with_the_free_cells(eightoff):
    g, _c, t = eightoff
    for x in t[2:]:
        g.slots[x].cards = [up(9, "S")]
    g.slots[t[0]].cards = [up(5, "D")] + [up(r, "H") for r in range(13, 3, -1)]
    assert g.default_pickup(t[0]) == 9  # eight free cells, plus one
    assert g.attempt_move(t[0], t[1], 10) is False
    assert g.attempt_move(t[0], t[1], 9) is False  # a Queen can't lead
    g.slots[t[0]].cards = [up(5, "D")] + [up(r, "H") for r in range(13, 4, -1)]
    assert g.attempt_move(t[0], t[1], 9)
