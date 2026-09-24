"""Drawing the board with BoardUI: card art, both views, the code skin,
monochrome, and layouts that have to squeeze onto small screens.

The hit map ((y, x) -> (slot, card index)) is what clicks go through, so most
checks here are about which cards end up clickable.
"""

import curses
import re

import pytest

from soliterm import camo, tui
from soliterm.engine import GAME_ORDER, Card
from soliterm.textmode import render_text

from helpers import FakeScr, clear_board, deal


def draw(g, h=40, w=120, symbols=False, view="expanded", code_skin=False, hint=None):
    scr = FakeScr(h, w)
    ui = tui.BoardUI(scr, g, symbols=symbols, has_color=False, view=view)
    ui.code_skin = code_skin
    cursor = g.ids_of("tableau")[0] if g.ids_of("tableau") else 0
    ui.draw(None, 1, cursor, hint, 1.0, "x")
    return ui, scr


def clickable(ui, sid):
    """Card indexes of slot sid that have at least one hit cell."""
    return {idx for (s, idx) in ui.hit.values() if s == sid}


# -- card art ----------------------------------------------------------------------

@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_game_draws_card_boxes(key):
    _ui, scr = draw(deal(key, 3))
    assert "+--" in scr.text()


def test_unicode_mode_draws_box_borders():
    _ui, scr = draw(deal("klondike", 1), symbols=True)
    assert "┌" in scr.text() and "│" in scr.text()


@pytest.fixture
def fanned_column():
    """A Klondike board with just KS QH JS 10H down the first column."""
    g = deal("klondike", 1)
    clear_board(g)
    col = g.ids_of("tableau")[0]
    g.slots[col].cards = [Card(13, "S", True), Card(12, "H", True),
                          Card(11, "S", True), Card(10, "H", True)]
    return g, col


def test_covered_cards_show_their_rank(fanned_column):
    g, _col = fanned_column
    _ui, scr = draw(g)
    for label in ("KS", "QH", "JS", "10H"):
        assert label in scr.text()


def test_every_card_in_a_roomy_column_is_clickable(fanned_column):
    g, col = fanned_column
    ui, _scr = draw(g)
    assert clickable(ui, col) == {0, 1, 2, 3}


def test_every_card_in_a_short_waste_fan_is_clickable():
    g = deal("fortythieves", 1)
    waste = g.ids_of("waste")[0]
    g.slots[waste].cards = [Card((i % 13) + 1, "SHDC"[i % 4], True) for i in range(5)]
    ui, _scr = draw(g, h=30, w=120)
    assert len(clickable(ui, waste)) == 5


def waste_row(ui, scr, waste):
    """The screen text across the waste's label row, from the waste on."""
    y, x = ui.slot_origin[waste]
    return scr.text().splitlines()[y + 1][x:]


def test_klondike_drawing_three_fans_the_last_three_cards():
    # as AisleRiot does, and it keeps them fanned through an undo
    g = deal("klondike", 1, draw=3)
    waste = g.ids_of("waste")[0]
    g.deal()
    g.deal()
    g.undo()
    g.redo()
    cards = g.cards(waste)
    assert len(cards) == 6
    ui, scr = draw(g)
    assert clickable(ui, waste) == {3, 4, 5}
    row = waste_row(ui, scr, waste)
    assert all(str(c) in row for c in cards[3:])
    assert not any(str(c) in row for c in cards[:3])


def test_klondike_drawing_one_shows_only_the_top_of_the_waste():
    g = deal("klondike", 1)
    waste = g.ids_of("waste")[0]
    g.deal()
    g.deal()
    ui, _scr = draw(g)
    assert clickable(ui, waste) == {1}


@pytest.mark.parametrize("draw_n", [1, 3])
def test_text_mode_shows_only_the_top_of_the_klondike_waste(draw_n):
    # the fan is the board's alone: text mode keeps one card to a slot on
    # the top row, so the foundations stay where their tags say
    g = deal("klondike", 3, draw=draw_n)
    for _ in range(4):
        g.deal()
    waste = g.ids_of("waste")[0]
    assert len(g.cards(waste)) > 3
    row = render_text(g, symbols=False).splitlines()[2]
    top = g.cards(waste)[-1].label(False)
    assert re.findall(r"\[[^]]*\]", row) == ["[###]", f"[{top:>3}]"] + ["[   ]"] * 4


def box_text(ui, scr, sid):
    """The screen text inside the box of slot sid's top card."""
    y, x = ui.slot_origin[sid]
    lines = scr.text().splitlines()
    return [lines[y + dy][x:x + ui._cw] for dy in range(ui.card_h)]


@pytest.mark.parametrize("view", ["expanded", "legacy"])
@pytest.mark.parametrize("key", ["canfield", "klondike", "spider"])
def test_the_stock_count_shows_on_the_stock(key, view):
    # below it, Canfield's reserve label wrote over it
    g = deal(key, 1)
    stock = g.ids_of("stock")[0]
    n = len(g.cards(stock))
    ui, scr = draw(g, h=40, w=120, view=view)
    assert any(str(n) in row for row in box_text(ui, scr, stock))
    if key == "canfield":
        reserve = g.ids_of("reserve")[0]
        y, x = ui.slot_origin[reserve]
        assert scr.text().splitlines()[y - 1][x:].startswith("Res")


# -- squeezing onto the screen ------------------------------------------------------

@pytest.mark.parametrize("h, w", [(24, 100), (24, 110)])
def test_a_tall_column_keeps_its_top_card_clickable(h, w):
    g = deal("spider", 1)
    col = g.ids_of("tableau")[0]
    g.slots[col].cards = [Card((i % 13) + 1, "S", True) for i in range(34)]
    ui, _scr = draw(g, h=h, w=w)
    top = len(g.slots[col].cards) - 1
    rows = [y for (y, x), (sid, idx) in ui.hit.items() if sid == col and idx == top]
    assert rows
    assert max(rows) < h - 3               # clear of the status bar


def column_text(ui, scr, sid):
    """The screen text down the column slot sid is drawn in."""
    x = ui.slot_origin[sid][1]
    return [line[x:x + ui._cw] for line in scr.text().splitlines()]


RUN = [Card(r, "SH"[r % 2], True) for r in range(13, 3, -1)]    # KS QH ... 4H


# at 80x24 a Klondike column has 8 rows for its covered cards
@pytest.mark.parametrize("down, up", [(6, 7), (0, 9), (4, 9)])
def test_a_squeezed_column_still_shows_every_face_up_rank(down, up):
    g = deal("klondike", 1)
    clear_board(g)
    col = g.ids_of("tableau")[0]
    g.slots[col].cards = [Card(1, "C", False)] * down + RUN[:up]
    ui, scr = draw(g, h=24, w=80)
    text = "\n".join(column_text(ui, scr, col))
    for card in RUN[:up]:
        assert str(card) in text
    assert clickable(ui, col) >= set(range(down, down + up))


# 2 face-down cards squeezed to a row each; 1 on a row of its own, as in
# the Yukon opening; 6 counted on one row
@pytest.mark.parametrize("down, up", [(2, 4), (1, 9), (6, 9)])
def test_a_face_down_card_squeezed_to_one_row_shows_its_back(down, up):
    # its top edge alone read as the top of the card on it
    g = deal("klondike", 1)
    clear_board(g)
    col = g.ids_of("tableau")[0]
    g.slots[col].cards = [Card(1, "C", False)] * down + RUN[:up]
    ui, scr = draw(g, h=24, w=80)
    top, x = ui.slot_origin[col]
    lines = scr.text().splitlines()
    backs = [lines[y][x:x + ui._cw] for y in range(top, 21)
             if ui.hit_test(y, x + 1) in {(col, i) for i in range(down)}]
    assert backs and all("#" in row for row in backs)


KING_TO_ACE = [Card(r, "SH"[r % 2], True) for r in range(13, 0, -1)]
DEALT = [Card(9, "H", True), Card(4, "S", True), Card(7, "H", True), Card(2, "S", True)]


def rows_of_their_own(ui, scr, sid):
    """Indexes of slot sid's cards with a row to themselves above the status
    line: the row shows the card's rank and suit, and a click on it picks
    that card."""
    top, x = ui.slot_origin[sid]
    lines = scr.text().splitlines()
    cards = ui.game.cards(sid)
    own = set()
    for y in range(top, ui.stdscr.getmaxyx()[0] - 3):
        hit = ui.hit_test(y, x + 1)
        text = lines[y][x:x + ui._cw].strip("|│ ")
        if hit and hit[0] == sid and text == cards[hit[1]].label(ui.symbols):
            own.add(hit[1])
    return own


@pytest.mark.parametrize("symbols", [False, True])
@pytest.mark.parametrize("code_skin", [False, True])
@pytest.mark.parametrize("key, down, up", [
    ("klondike", 6, KING_TO_ACE),              # as long as a Klondike column gets
    ("klondike", 0, KING_TO_ACE),
    ("spider", 5, KING_TO_ACE + DEALT[:2]),
    ("spider", 0, KING_TO_ACE + DEALT[:3]),
])
def test_every_face_up_card_of_a_long_column_has_a_row_at_80x24(key, down, up,
                                                                code_skin, symbols):
    g = deal(key, 1)
    clear_board(g)
    col = g.ids_of("tableau")[0]
    g.slots[col].cards = [Card(1, "C", False)] * down + up
    ui, scr = draw(g, h=24, w=80, code_skin=code_skin, symbols=symbols)
    assert rows_of_their_own(ui, scr, col) >= set(range(down, down + len(up)))
    all_on_screen(ui, g, 24, 80)


def test_the_slot_labels_give_way_before_cards_share_a_row():
    # a third dealt card is one row too many with the labels above the board
    g = deal("spider", 1)
    clear_board(g)
    col = g.ids_of("tableau")[0]
    up = KING_TO_ACE + DEALT[:3]
    g.slots[col].cards = [Card(1, "C", False)] * 5 + up
    ui, scr = draw(g, h=24, w=80)
    assert rows_of_their_own(ui, scr, col) >= set(range(5, 5 + len(up)))
    assert "Fnd" not in scr.text()
    all_on_screen(ui, g, 24, 80)


@pytest.mark.parametrize("code_skin", [False, True])
def test_a_column_too_long_for_the_screen_says_how_many_cards_share_a_row(code_skin):
    g = deal("spider", 1)
    clear_board(g)
    col = g.ids_of("tableau")[0]
    cards = [Card(1, "C", False)] * 5 + KING_TO_ACE + DEALT
    g.slots[col].cards = cards
    ui, scr = draw(g, h=24, w=80, code_skin=code_skin)
    all_on_screen(ui, g, 24, 80)
    top, x = ui.slot_origin[col]
    lines = scr.text().splitlines()
    first_row = {}               # card index -> the first row a click picks it on
    for y in range(top, 21):
        hit = ui.hit_test(y, x + 1)
        if hit and hit[0] == col:
            first_row.setdefault(hit[1], y)
    starts = sorted(first_row)
    assert starts[0] == 0
    shared = []
    for a, b in zip(starts, starts[1:] + [len(cards)]):
        text = lines[first_row[a]][x:x + ui._cw]
        if b - a > 1 and cards[a].face_up:
            assert text.strip("| ") == f"+{b - a}"
            shared.append(a)
        elif b - a > 1:
            assert text.strip("|#") == str(b - a)
    # the run's King and the cards on top of the column keep their own rows
    assert shared
    assert rows_of_their_own(ui, scr, col) >= {5, len(cards) - 2, len(cards) - 1}


def message_line(dealt, message, code_skin):
    """The message line at 80x24 under a Spider column of five face-down
    cards, King to Ace and `dealt` cards on it."""
    g = deal("spider", 1)
    clear_board(g)
    col = g.ids_of("tableau")[0]
    g.slots[col].cards = [Card(1, "C", False)] * 5 + KING_TO_ACE + DEALT[:dealt]
    scr = FakeScr(24, 80)
    ui = tui.BoardUI(scr, g, symbols=False, has_color=False)
    ui.code_skin = code_skin
    ui.draw(None, 1, None, None, 1.0, message)
    return scr.text().splitlines()[22]


@pytest.mark.parametrize("code_skin", [False, True])
def test_the_message_line_says_when_cards_share_a_row(code_skin):
    assert ("some cards share a row; a taller terminal shows them all"
            in message_line(4, "", code_skin))
    assert "share" not in message_line(2, "", code_skin)
    # a message from the game comes first
    line = message_line(4, "nothing to pick up there", code_skin)
    assert "nothing to pick up there" in line and "share" not in line


@pytest.mark.parametrize("code_skin", [False, True])
@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_face_up_rank_of_an_opening_deal_shows_at_80x24(key, code_skin):
    # the code skin sits the board no lower than the plain screen does, so
    # it squeezes no column harder
    for seed in range(1, 6):
        g = deal(key, seed)
        ui, scr = draw(g, h=24, w=80, code_skin=code_skin)
        for sid in g.ids_of("tableau"):
            cards = g.cards(sid)
            text = "\n".join(column_text(ui, scr, sid)[ui.slot_origin[sid][0]:21])
            assert all(str(c) in text for c in cards if c.face_up)
            assert clickable(ui, sid) >= {i for i, c in enumerate(cards) if c.face_up}


def test_a_long_waste_leaves_the_foundations_on_screen():
    g = deal("fortythieves", 1)
    waste = g.ids_of("waste")[0]
    g.slots[waste].cards = [Card((i % 13) + 1, "SHDC"[i % 4], True) for i in range(40)]
    ui, _scr = draw(g, h=40, w=80)
    on_screen = {sid for (y, x), (sid, idx) in ui.hit.items() if x < 80}
    for f in g.ids_of("foundation"):
        assert f in on_screen


def test_thirteen_columns_fit_in_80_columns():
    g = deal("bakersdozen", 1)
    ui, _scr = draw(g, h=40, w=80)
    cols = set(g.ids_of("tableau"))
    on = {sid for (y, x), (sid, idx) in ui.hit.items() if sid in cols and x < 80}
    assert on == cols
    assert tui.MIN_CARD_W <= ui._cw <= tui.MAX_CARD_W


@pytest.mark.parametrize("symbols", [False, True])
@pytest.mark.parametrize("view", ["expanded", "legacy"])
def test_a_ten_fits_inside_the_narrowest_card(view, symbols):
    g = deal("klondike", 1)
    clear_board(g)
    a, b = g.ids_of("tableau")[:2]
    g.slots[a].cards = [Card(10, "H", True)]
    g.slots[b].cards = [Card(10, "S", True)]
    ui, scr = draw(g, w=45, symbols=symbols, view=view)
    assert ui._cw == ui.min_cw
    xa, xb = ui.slot_origin[a][1], ui.slot_origin[b][1]
    ten = Card(10, "H", True).label(symbols)
    row = next(line for line in scr.text().splitlines() if ten in line)
    # the box closes after the ten, and the gap to the next column stays
    assert row[xa + ui._cw - 1] in "|│]"
    assert row[xa + ui._cw:xb].strip() == ""


def fill_the_fans(g):
    """Give every right-fanned slot more cards than it shows."""
    for s in g.slots:
        if s.expand == "right":
            s.cards = [Card((i % 13) + 1, "SHDC"[i % 4], True) for i in range(12)]
    return g


def all_on_screen(ui, g, h, w):
    """Every slot is drawn, and nothing past the last column curses writes
    or into the status line."""
    assert {sid for sid, _ in ui.hit.values()} == {s.sid for s in g.slots}
    assert max(x for _, x in ui.hit) < w - 1
    assert max(y for y, _ in ui.hit) < h - 3


@pytest.mark.parametrize("code_skin", [False, True])
@pytest.mark.parametrize("view", ["expanded", "legacy"])
@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_game_fits_on_an_80x24_screen(key, view, code_skin):
    g = fill_the_fans(deal(key, 1))
    ui, _scr = draw(g, h=24, w=80, view=view, code_skin=code_skin)
    all_on_screen(ui, g, 24, 80)


@pytest.mark.parametrize("code_skin", [False, True])
@pytest.mark.parametrize("view", ["expanded", "legacy"])
@pytest.mark.parametrize("key", GAME_ORDER)
def test_a_board_fits_in_just_the_size_it_asks_for(key, view, code_skin):
    g = fill_the_fans(deal(key, 1))
    ui, _ = draw(g, view=view, code_skin=code_skin)
    w, h = ui.needed_size()
    ui, scr = draw(g, h=h, w=w, view=view, code_skin=code_skin)
    all_on_screen(ui, g, h, w)
    for smaller in ((h - 1, w), (h, w - 1)):
        ui, scr = draw(g, *smaller, view=view, code_skin=code_skin)
        assert not ui.hit
        assert f"needs {w}x{h}" in scr.text()


@pytest.mark.parametrize("key, h, w", [("fortythieves", 24, 60), ("klondike", 15, 80)])
def test_a_board_too_big_for_the_terminal_is_not_drawn_off_it(key, h, w):
    ui, scr = draw(deal(key, 1), h=h, w=w)
    assert "Terminal too small." in scr.text()
    assert not ui.hit and not ui.fits()


def test_the_foundations_stay_put_as_the_waste_grows():
    g = deal("fortythieves", 1)
    ui = tui.BoardUI(FakeScr(40, 120), g, symbols=False, has_color=False)
    before = ui.compute_positions()
    fill_the_fans(g)
    assert ui.compute_positions() == before


def test_a_tiny_terminal_gets_a_message_instead_of_a_board():
    ui, scr = draw(deal("klondike", 1), h=8, w=30)
    assert "Terminal too small." in scr.text()
    assert not ui.hit


# -- expanded and legacy views -----------------------------------------------------------

@pytest.fixture
def dealt_klondike():
    g = deal("klondike", 5)
    g.deal()
    return g


def test_expanded_draws_boxes_and_legacy_draws_cells(dealt_klondike):
    g = dealt_klondike
    ui_e, scr_e = draw(g, h=36, symbols=True, view="expanded", hint=g.hint())
    ui_l, scr_l = draw(g, h=36, symbols=True, view="legacy", hint=g.hint())
    assert ui_e.card_h == 4 and "┌" in scr_e.text()
    assert ui_l.card_h == 1 and "┌" not in scr_l.text() and "[" in scr_l.text()


def test_both_views_have_the_same_click_targets(dealt_klondike):
    g = dealt_klondike
    ui_e, _ = draw(g, h=36, symbols=True, view="expanded", hint=g.hint())
    ui_l, _ = draw(g, h=36, symbols=True, view="legacy", hint=g.hint())
    assert set(ui_e.hit.values()) == set(ui_l.hit.values())


def test_set_view_switches_geometry_and_rejects_garbage():
    ui, _ = draw(deal("klondike", 5))
    ui.set_view("legacy")
    assert ui.view == "legacy" and ui.card_h == 1
    ui.set_view("expanded")
    assert ui.view == "expanded" and ui.card_h == 4
    ui.set_view("nonsense")
    assert ui.view == "expanded"


@pytest.mark.parametrize("view", ["expanded", "legacy"])
@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_game_draws_in_both_views(key, view):
    g = deal(key, 2)
    ui, _ = draw(g, h=36, symbols=True, view=view, hint=g.hint())
    assert ui.hit


# -- monochrome ------------------------------------------------------------------------

@pytest.mark.parametrize("key", GAME_ORDER)
def test_monochrome_uses_no_colour_pairs(key):
    g = deal(key, 2)
    ui = tui.BoardUI(FakeScr(), g, symbols=True, has_color=False)
    assert ui.CP(1) == 0 and ui.CP(8) == 0
    cursor = g.ids_of("tableau")[0] if g.ids_of("tableau") else 0
    ui.draw(None, 1, cursor, g.hint(), 5.0, "colour off")
    ui.code_skin = True
    ui.draw(None, 1, cursor, None, 5.0, "mono code skin")


# -- code skin -------------------------------------------------------------------------------

def test_code_lines_are_repeatable_and_read_as_source():
    a = camo.code_lines(120, seed=1)
    assert a == camo.code_lines(120, seed=1)
    assert len(a) == 120
    joined = "\n".join(a)
    assert "def " in joined and "import" in joined


@pytest.mark.parametrize("key", GAME_ORDER)
def test_the_code_skin_keeps_the_board_clickable(key):
    g = deal(key, 3)
    ui, _ = draw(g, h=40, w=140, code_skin=True, hint=g.hint())
    assert ui.hit
    assert min(x for (_, x) in ui.hit) >= ui._gutter
    for sid, _idx in ui.hit.values():
        assert 0 <= sid < len(g.slots)


def test_the_code_skin_looks_like_an_editor(dealt_klondike):
    # 44 rows leaves room for source above and below the board
    _ui, scr = draw(dealt_klondike, h=44, w=100, code_skin=True)
    screen = scr.text()
    assert "solver.py" in screen           # editor header
    assert "def " in screen                # source around the board
    assert "  1  " in screen               # line-number gutter
    assert "board snapshot" in screen
    assert "+--" in screen                 # and the cards themselves


class AttrScr(FakeScr):
    """A FakeScr that also keeps the attribute every cell was drawn with."""

    def erase(self):
        super().erase()
        self.attrs = [[0] * self.w for _ in range(self.h)]

    def addnstr(self, y, x, text, n, attr=0):
        super().addnstr(y, x, text, n, attr)
        for i in range(min(len(text), n)):
            if 0 <= y < self.h and 0 <= x + i < self.w:
                self.attrs[y][x + i] = attr


def test_the_code_skin_source_is_in_the_terminal_colours(monkeypatch):
    # not on the white of a card face, which shows as bars on a dark screen
    monkeypatch.setattr(curses, "color_pair", lambda n: n << 8)
    scr = AttrScr(44, 100)
    ui = tui.BoardUI(scr, deal("klondike", 1), symbols=False, has_color=True)
    ui.code_skin = True
    ui.draw(None, 1, 0, None, 1.0, "")
    source = [(y, line) for y, line in enumerate(scr.text().splitlines())
              if line[ui._gutter:].startswith(("import", "def ", "from "))]
    assert source
    for y, line in source:
        assert set(scr.attrs[y][ui._gutter:len(line)]) == {0}


def test_the_code_skin_moves_the_board_into_the_file():
    ui = tui.BoardUI(FakeScr(), deal("klondike", 1), symbols=False, has_color=False)
    off = ui.compute_positions()
    ui.code_skin = True
    on = ui.compute_positions()
    sid = next(iter(on))
    assert on[sid][1] > off[sid][1]        # indented further right
    assert on[sid][0] >= off[sid][0]       # and no higher
