"""soliterm.tui.board - draws a Solitaire board and maps clicks back to cards.

Layout mirrors AisleRiot's board: slots are positioned on a grid derived from
each game's slot rows; cards in "down" slots fan vertically, "right" slots fan
horizontally, and single slots show only the top card. The status bar shows the
score, the clock, and the game's status message - the same chrome AisleRiot
shows.
"""

from __future__ import annotations

import curses
import locale
from typing import Dict, Iterator, List, Optional, Tuple

from .. import APP_NAME, camo, store
from ..engine import SUIT_SYMBOL, Card, Solitaire


# Geometry of a rendered card. Cards are drawn as multi-line boxes that overlap
# vertically (and horizontally for waste fans), AisleRiot-style: the top card of
# a pile shows full-size, covered cards peek out with their rank+suit corner.
CARD_H = 4          # full card box height in rows
PEEK_Y = 2          # rows a covered card shows in a down-fan when there's room
PEEK_X = 4          # cols a covered card shows in a right-fan (border + label)
MIN_CARD_W = 5      # narrowest card (interior fits "10S" with no margin)
MAX_CARD_W = 8      # widest card (lots of horizontal room)
COL_GAP = 1         # blank columns between piles in a row
ROW_GAP = 1         # blank rows between slot-rows
MAX_RIGHT_FAN = 6   # most cards shown in a right-expanding fan (waste/reserve)
                    # unless the game fans fewer (see fan_room)
MIN_COLS = 40       # the smallest terminal any board is drawn on; a wide
MIN_ROWS = 14       # game needs more (see BoardUI.needed_size)

# Box-drawing glyphs: unicode for a real card look, ASCII fallback for --ascii.
_GLYPHS = {
    True:  dict(tl="┌", tr="┐", bl="└", br="┘", h="─", v="│", back="▒"),
    False: dict(tl="+", tr="+", bl="+", br="+", h="-", v="|", back="#"),
}
# the legacy view's card back is the one unicode glyph not in _GLYPHS
_UNICODE = "".join(_GLYPHS[True].values()) + "░" + "".join(SUIT_SYMBOL.values())


def can_draw_unicode(stdscr) -> bool:
    """True if the terminal's encoding has the card art and the suits.

    Under LC_ALL=C curses can't encode them and refuses every string they
    are in, which leaves the board blank, so the cards fall back to ASCII.
    """
    enc = getattr(stdscr, "encoding", None) or locale.getpreferredencoding(False)
    try:
        _UNICODE.encode(enc)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


# The code skin's file: the width of its " 12  " line-number gutter, and the
# source it shows around whatever sits in it
CODE_GUTTER = 5
_CODE = camo.code_lines(200, seed=1)


def draw_code_backdrop(ui, notes: Dict[int, str],
                       last_row: Optional[int] = None) -> None:
    """Paint the code-editor backdrop a skinned screen is drawn on top of.

    A line-number gutter down the left, source lines filling the screen,
    and a header that reads as an open file. The rows in `notes` are kept
    for the screen and show only their note, from the gutter on. The file
    runs to `last_row`, the screen's last row but one unless given. `ui` is
    the BoardUI or the App; this needs its stdscr, has_color, CP and
    safe_add.
    """
    h, w = ui.stdscr.getmaxyx()
    dim = ui.CP(4)
    code_attr = 0              # source text in the terminal's own colours
    # editor-style header / tab bar
    ui.safe_add(0, 0, " solver.py  -  ~/work/render-core/engine "
                .ljust(w - 1), ui.CP(5) if ui.has_color else curses.A_REVERSE)
    for screen_y in range(1, (h - 2 if last_row is None else last_row) + 1):
        lineno = screen_y          # 1-based line numbers down the file
        gutter = f"{lineno:>3}  "
        ui.safe_add(screen_y, 0, gutter, dim)
        if screen_y in notes:
            if notes[screen_y]:
                ui.safe_add(screen_y, CODE_GUTTER, notes[screen_y], dim)
            continue
        # otherwise fill with a stable line of source
        idx = lineno % len(_CODE)
        ui.safe_add(screen_y, CODE_GUTTER, _CODE[idx], code_attr)


def draw_too_small(ui, what: str, need: Tuple[int, int], code_skin: bool) -> None:
    """Say the terminal is smaller than the (width, height) `what` needs,
    in place of drawing it cut off. `ui` is as for draw_code_backdrop."""
    h, w = ui.stdscr.getmaxyx()
    notice = ["Terminal too small.",
              f"{what} needs {need[0]}x{need[1]}, have {w}x{h}.",
              "Resize, or press q."]
    if code_skin:
        # as a comment in the file, so the notice gives nothing away
        draw_code_backdrop(ui, {1 + i: f"# {line}" for i, line in enumerate(notice)})
    else:
        for i, line in enumerate(notice):
            ui.safe_add(i, 0, line)


class BoardUI:
    """Renders a Solitaire board and maps screen coords back to (slot, index)."""

    def __init__(self, stdscr, game: Solitaire, symbols: bool, has_color: bool,
                 view: str = "expanded"):
        self.stdscr = stdscr
        self.game = game
        self.symbols = symbols
        self.has_color = has_color
        # hit map: (y, x) cell -> (slot_id, card_index) for click/drag mapping
        self.hit: Dict[Tuple[int, int], Tuple[int, int]] = {}
        self.slot_origin: Dict[int, Tuple[int, int]] = {}
        self.origin_y = 4
        self.origin_x = 2
        self.set_view(view)
        # code-skin play mode: wrap the live board in plausible source so the
        # screen reads as a code editor while the game stays fully playable.
        self.code_skin = False
        self._gutter = CODE_GUTTER
        # how far down / right the board sits inside the file when skinned;
        # no lower than without the skin, which would squeeze the columns
        # harder (a FreeCell deal at 80x24 would lose ranks)
        self._code_top = self.origin_y
        self._code_indent = 9

    def set_view(self, view: str) -> None:
        """Configure rendering geometry for the chosen view.

        "expanded" - full multi-row card boxes; the top card of a pile shows
                     full size and covered cards peek with their rank visible.
        "legacy"   - the original compact view: every card is a single-line
                     [ A♠] cell, one row per card in a column.
        All the layout / hit-test maths is driven by these attributes, so both
        views share the same code path.
        """
        self.view = view if view in ("expanded", "legacy") else "expanded"
        if self.view == "legacy":
            self.card_h = 1           # one row per card
            self.peek_y = 1           # covered cards step down one row
            self.peek_x = 1           # waste fan steps one column
            self.min_cw = 5           # "[ A♠]" / "[10♠]" compact cell
            self.max_cw = 5
        else:
            self.card_h = CARD_H
            self.peek_y = PEEK_Y
            self.peek_x = PEEK_X
            self.min_cw = MIN_CARD_W
            self.max_cw = MAX_CARD_W

    # -- colour helpers -- #
    def CP(self, n):
        return curses.color_pair(n) if self.has_color else 0

    def card_attr(self, card: Optional[Card], selected: bool, hinted: bool,
                  cursor: bool = False) -> int:
        """Attribute for a card given its highlight state.

        Priority: selected > cursor > hint > plain. Every state has a DISTINCT
        look in BOTH colour and monochrome modes, so without colour the cursor
        (where you are), the selection (what you picked up) and a hint can still
        be told apart - reverse / bold / underline respectively.
        """
        if not self.has_color:
            if selected:
                return curses.A_REVERSE
            if cursor:
                return curses.A_BOLD
            if hinted:
                return curses.A_UNDERLINE
            return curses.A_NORMAL
        red = card is not None and card.face_up and card.is_red
        if selected:
            # both colours sit on a green selection background; red cards use a
            # white foreground (red-on-green just muddies into brown), black use
            # black-on-green - so a selected card always reads as green.
            return (self.CP(8) if red else self.CP(3)) | curses.A_BOLD
        if cursor:
            return self.CP(5) | curses.A_BOLD     # black-on-yellow cursor
        if hinted:
            return self.CP(9) | curses.A_BOLD     # black-on-cyan hint
        if card is None:
            return self.CP(4)                 # empty slot: chrome
        if not card.face_up:
            return self.CP(7)                 # face-down: blue card back
        return self.CP(1) if red else self.CP(2)   # white face, red/black text

    # -- card-box rendering ------------------------------------------------ #
    def _card_rows(self, card: Optional[Card], w: int, full: bool) -> List[str]:
        """The character rows of a card box, width `w`.

        full=True returns all CARD_H rows (top card / single card); full=False
        returns the 'peek' a covered card shows above the card overlapping it:
        a top border and the rank/suit label line, so every covered card's
        identity stays visible and clickable.
        """
        if self.view == "legacy":
            # the original compact view: one single-line [ A♠] cell per card
            inner = w - 2
            if card is None:
                body = " " * inner
            elif not card.face_up:
                body = ("#" * inner) if not self.symbols else ("░" * inner)
            else:
                body = card.label(self.symbols).rjust(inner)
            return ["[" + body + "]"]
        gl = _GLYPHS[bool(self.symbols)]
        inner = w - 2
        top = gl["tl"] + gl["h"] * inner + gl["tr"]
        bot = gl["bl"] + gl["h"] * inner + gl["br"]
        if card is None:                       # empty slot: a dashed frame
            blank = gl["v"] + " " * inner + gl["v"]
            rows = [top] + [blank] * (self.card_h - 2) + [bot]
        elif not card.face_up:                 # face-down: patterned back
            back = gl["v"] + (gl["back"] * inner) + gl["v"]
            rows = [top] + [back] * (self.card_h - 2) + [bot]
        else:
            label = card.label(self.symbols)
            # label hugs the top-left like a real card index, with a margin
            # when there's room for one (a ten fills the narrowest card)
            if len(label) < inner:
                label = " " + label
            line1 = gl["v"] + label.ljust(inner) + gl["v"]
            mid = gl["v"] + " " * inner + gl["v"]
            # echo the suit bottom-right on a full card for a card-y look
            suit = (SUIT_SYMBOL[card.suit] if self.symbols else card.suit)
            line3 = gl["v"] + suit.rjust(inner) + gl["v"]
            rows = [top, line1, mid, line3, bot][:max(self.card_h, 2)]
            if self.card_h == 4:
                rows = [top, line1, mid, bot]
        return rows if full else rows[:2]      # peek = top border + label

    def _layouts(self) -> Iterator[Tuple[int, int, int, int]]:
        """Every layout to try, roomiest first, as (card width, fan step,
        column gap, code-skin indent).

        A wider card is nicer, so the cards narrow first, then the skinned
        board moves out to the gutter, then the fans close up, and only as a
        last resort do the columns lose their gap. That keeps a 13-column
        game (Bakers Dozen) or a two-deck top row on an 80-col screen.
        """
        indent = self._code_indent if self.code_skin else 0
        for cw in range(self.max_cw, self.min_cw - 1, -1):
            yield cw, min(self.peek_x, cw - 1), COL_GAP, indent
        cw = self.min_cw
        step = min(self.peek_x, cw - 1)
        for less in range(indent - 1, -1, -1):
            yield cw, step, COL_GAP, less
        for closer in range(step - 1, 1, -1):     # down to two columns a card
            yield cw, closer, COL_GAP, 0
        yield cw, min(step, 2), 0, 0

    def _rows(self) -> List[List]:
        """The slots on each display row, top row first."""
        rows: Dict[int, List] = {}
        for s in self.game.slots:
            rows.setdefault(s.row, []).append(s)
        return [rows[r] for r in sorted(rows)]

    def _row_width(self, slots, cw: int, step: int, gap: int) -> int:
        """Columns a row of slots takes, room for full fans included."""
        return (sum(cw + (self.fan_room(s) - 1) * step for s in slots)
                + gap * (len(slots) - 1))

    def _choose_layout(self, screen_w: int) -> None:
        """Set the card width, fan step, gap and indent for this frame: the
        roomiest layout whose widest row fits on screen, or the tightest."""
        base_x = self._gutter if self.code_skin else self.origin_x
        rows = self._rows()
        for layout in self._layouts():
            cw, step, gap, indent = layout
            right = base_x + indent + max(self._row_width(r, cw, step, gap)
                                          for r in rows)
            # curses never writes the last column (see safe_add)
            if right < screen_w:
                break
        self._cw, self._step, self._gap, self._indent = layout

    def needed_size(self) -> Tuple[int, int]:
        """The smallest terminal, as (columns, rows), the board fits on.

        The width is the widest row laid out as tightly as it goes. The
        height has every row one card high, as the columns can squeeze
        (only the last row holds columns in any game), and the status and
        message lines below.
        """
        cw, step, gap, indent = list(self._layouts())[-1]
        base_x = self._gutter if self.code_skin else self.origin_x
        rows = self._rows()
        w = base_x + indent + max(self._row_width(r, cw, step, gap)
                                  for r in rows) + 1
        top = self._code_top if self.code_skin else self.origin_y
        h = top + len(rows) * (self.card_h + ROW_GAP) - ROW_GAP + 3
        return max(MIN_COLS, w), max(MIN_ROWS, h)

    def safe_add(self, y, x, text, attr=0):
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    def _blit_card(self, y, x, card, w, full, attr):
        """Draw a card box (full or peek) at (y,x) with the given attribute."""
        for dy, line in enumerate(self._card_rows(card, w, full)):
            self.safe_add(y + dy, x, line, attr)

    def _register_hit(self, y, x, height, w, sid, idx):
        """Map every cell of a (height x w) card box back to (slot, card idx)."""
        for dy in range(height):
            for dx in range(w):
                self.hit[(y + dy, x + dx)] = (sid, idx)

    def _draw_down_pile(self, slot, sid, sy, sx, cw, sel_here, cur_here,
                        selected_n, hint_src, hint_dst, hint_n):
        """A tableau column: covered cards peek above the full-size top card."""
        n = len(slot.cards)
        sel_start = n - selected_n if sel_here else n
        # each card's top row, so cards stack consistently
        ys = [sy + dy for dy in self._down_rows(slot.cards, sy)]
        for i, card in enumerate(slot.cards):
            cy = ys[i]
            is_top = i == n - 1
            is_sel = sel_here and i >= sel_start
            is_hint = (sid == hint_dst and is_top) or \
                      (sid == hint_src and i >= n - hint_n)
            is_cur = cur_here and is_top
            attr = self.card_attr(card, is_sel, is_hint and not is_sel,
                                  cursor=is_cur)
            # full box for the top card, just the peek (border+label) for
            # covered ones, and a face-up card's label alone when only one
            # row of it shows
            lines = self._card_rows(card, cw, is_top)
            if not is_top and card.face_up and ys[i + 1] - cy == 1:
                lines = lines[-1:]
            for dy, line in enumerate(lines):
                self.safe_add(cy + dy, sx, line, attr)
            # clickable band: from this card's top row to the next card's top
            # (its exposed strip), or the full box for the top card. Later cards
            # overwrite earlier rows in the hit map, so each exposed strip maps
            # to its own card - even a 1-row strip stays individually clickable.
            band = self.card_h if is_top else max(1, ys[i + 1] - cy)
            self._register_hit(cy, sx, band, cw, sid, i)

    def _draw_right_fan(self, slot, sid, sy, sx, cw, sel_here, cur_here,
                        hint_src, hint_dst):
        """A waste/reserve fan: cards overlap leftward, top card full-width."""
        peek_x = self._step
        cards = slot.cards
        start = len(cards) - self.fan_shown(slot)
        last = len(cards) - 1
        for i in range(start, len(cards)):
            card = cards[i]
            cx = sx + (i - start) * peek_x
            is_top = i == last
            is_sel = sel_here and is_top
            is_hint = (sid in (hint_dst, hint_src)) and is_top
            attr = self.card_attr(card, is_sel, is_hint, cursor=cur_here and is_top)
            width = cw if is_top else peek_x + 1
            self._blit_card(sy, cx, card, width, True, attr)
            self._register_hit(sy, cx, self.card_h, width, sid, i)

    # -- layout -- #
    def fan_room(self, slot) -> int:
        """How many cards the board makes room for in a slot: the most a
        right-fanned one shows, so the slots beside it don't move as it
        grows, and one for any other. A game can fan a slot that text mode
        shows as one card, as the Klondike waste drawing three."""
        if slot.expand == "down":
            return 1
        limit = self.game.gamedef.fan_limit(self.game, slot.sid)
        if slot.expand == "right":
            return limit or MAX_RIGHT_FAN
        return limit or 1

    def fan_shown(self, slot) -> int:
        """How many of a right-fanned slot's cards the board shows."""
        return min(len(slot.cards), self.fan_room(slot))

    def _columns_in_row(self, row: int) -> List[int]:
        return [s.sid for s in self.game.slots if s.row == row]

    def _down_rows(self, cards: List[Card], sy: int) -> List[int]:
        """Each card's top row in a down-column, counted from the column top.

        A covered card shows PEEK_Y rows (the top border and the rank label)
        when there's room. A tall pile (a long Spider / Yukon column) that
        would run past the status bar squeezes its face-down cards to a row
        each first, since they have no rank to show, then the face-up ones to
        a row showing just the label, then lets the face-down cards overlap
        more tightly still. Only when even that won't fit do face-up cards go
        below a row each, over face-down cards hidden entirely. The full-size
        top card always stays on screen and clickable.
        """
        covered = cards[:-1]
        if not covered:
            return [0] * len(cards)
        h = self.stdscr.getmaxyx()[0]
        # rows available from the column top down to just above the status bar,
        # reserving card_h for the full-size top card
        avail = max(0, (h - 3) - sy - self.card_h)
        up = sum(1 for c in covered if c.face_up)
        down = len(covered) - up
        py = self.peek_y
        if (up + down) * py <= avail:
            step_up = step_down = float(py)
        elif up * py + down <= avail:
            step_up, step_down = float(py), 1.0
        elif up + down <= avail:
            step_up = step_down = 1.0
        elif up <= avail:
            step_up, step_down = 1.0, (avail - up) / down
        else:
            step_up, step_down = avail / up, 0.0
        rows, at = [0], 0.0
        for c in covered:
            at += step_up if c.face_up else step_down
            # floor, not round, so a face-up card after a squeezed run of
            # face-down ones still gets its whole row
            rows.append(int(at + 1e-9))
        return rows

    def _slot_height(self, sid: int, sy: int) -> int:
        """Screen rows the slot's rendering occupies (for row stacking)."""
        slot = self.game.slots[sid]
        if slot.expand == "down" and len(slot.cards) > 1:
            return self._down_rows(slot.cards, sy)[-1] + self.card_h
        return self.card_h

    def compute_positions(self) -> Dict[int, Tuple[int, int]]:
        """Assign each slot a top-left (y, x). Returns slot_id -> (y, x).

        Also sets self._cw (the chosen card width for this frame).
        """
        positions: Dict[int, Tuple[int, int]] = {}
        rows = sorted({s.row for s in self.game.slots})
        # In code-skin mode the board sits lower and indented, inside the file.
        y = (self._code_top if self.code_skin else self.origin_y)
        self._choose_layout(self.stdscr.getmaxyx()[1])
        base_x = (self._gutter + self._indent if self.code_skin
                  else self.origin_x)
        for row in rows:
            sids = self._columns_in_row(row)
            x = base_x
            row_h = self.card_h
            for sid in sids:
                positions[sid] = (y, x)
                slot = self.game.slots[sid]
                x += self._cw + self._gap + (self.fan_room(slot) - 1) * self._step
                row_h = max(row_h, self._slot_height(sid, y))
            y += row_h + ROW_GAP
        return positions

    def _draw_code_skin(self):
        """Paint the code-editor backdrop the board will be drawn on top of.

        The rows where the board sits are left mostly blank (the board
        overwrites them anyway), with a comment line on top so they look
        like a snapshot embedded in the source.
        """
        board_rows = self._board_row_span()
        notes = {y: "" for y in board_rows}
        if board_rows:
            notes[min(board_rows)] = "    # --- board snapshot (live) ---"
        draw_code_backdrop(self, notes)

    def _board_row_span(self):
        """The set of screen rows the board occupies (for the code skin)."""
        positions = self.compute_positions()
        if not positions:
            return set()
        top = min(y for y, _ in positions.values()) - 1
        bottom = top
        for sid, (sy, _sx) in positions.items():
            bottom = max(bottom, sy + self._slot_height(sid, sy))
        return set(range(top, bottom + 2))

    def fits(self) -> bool:
        """False while the terminal is too small to lay the board out."""
        h, w = self.stdscr.getmaxyx()
        need_w, need_h = self.needed_size()
        return w >= need_w and h >= need_h

    def draw(self, selected_slot: Optional[int], selected_n: int,
             cursor_slot: Optional[int], hint: Optional[Tuple[int, int, str]],
             elapsed: float, message: str, hint_n: int = 1):
        """hint_n is how many cards the hint would move from its source."""
        self.stdscr.erase()
        self.hit.clear()
        if not self.fits():
            # Terminal too small to lay the board out cleanly: say so plainly
            # instead of drawing a clipped, unplayable mess.
            draw_too_small(self, self.game.gamedef.name, self.needed_size(),
                           self.code_skin)
            self.stdscr.refresh()
            return
        chrome = self.CP(4)
        g = self.game
        if self.code_skin:
            self._draw_code_skin()
        else:
            title = f"{APP_NAME}  -  {g.gamedef.name}"
            self.safe_add(0, 2, title, chrome | curses.A_BOLD)
            self.safe_add(1, 2, g.gamedef.blurb, chrome)

        positions = self.compute_positions()
        self.slot_origin = positions
        hint_src = hint[0] if hint else None
        hint_dst = hint[1] if hint else None

        cw = self._cw
        for sid, (sy, sx) in positions.items():
            slot = g.slots[sid]
            if not self.code_skin:
                # clip the slot label to the card width so narrow (legacy) cells
                # don't run their labels together
                self.safe_add(sy - 1, sx, self._slot_label(slot)[:cw], chrome)

            sel_here = selected_slot == sid
            cur_here = cursor_slot == sid

            if slot.empty:
                attr = self.card_attr(None, sel_here, sid == hint_dst,
                                      cursor=cur_here)
                self._blit_card(sy, sx, None, cw, True, attr)
                self._register_hit(sy, sx, self.card_h, cw, sid, 0)
                continue

            if slot.expand == "down":
                self._draw_down_pile(slot, sid, sy, sx, cw, sel_here, cur_here,
                                     selected_n, hint_src, hint_dst, hint_n)
            elif slot.expand == "right" or self.fan_room(slot) > 1:
                self._draw_right_fan(slot, sid, sy, sx, cw, sel_here, cur_here,
                                     hint_src, hint_dst)
            else:  # "none": stock / single-card slots show just the top card
                n = len(slot.cards)
                card = slot.top
                attr = self.card_attr(card, sel_here, sid in (hint_dst, hint_src),
                                      cursor=cur_here)
                self._blit_card(sy, sx, card, cw, True, attr)
                self._register_hit(sy, sx, self.card_h, cw, sid, n - 1)
                if slot.kind == "stock":
                    self._draw_stock_count(sy, sx, cw, n, attr)

        # status bar
        h, w = self.stdscr.getmaxyx()
        sy = h - 3
        won = " *** YOU WIN! ***" if g.is_won() else ""
        if self.code_skin:
            # render the status + message as trailing source comments so the
            # bottom of the screen still reads as code. Pad to the screen width
            # so the code background underneath these rows is fully cleared.
            dim = self.CP(4)
            pad = w - self._gutter - 1
            stat = (f"    # score={g.score} moves={g.moves} "
                    f"t={store.fmt_time(elapsed)}  {g.status}{won}")
            self.safe_add(sy, self._gutter, stat.ljust(pad)[:pad], dim)
            note = message if message else "code-skin mode (c to toggle)"
            self.safe_add(sy + 1, self._gutter, f"    # {note}".ljust(pad)[:pad], dim)
        else:
            self.safe_add(sy, 2,
                          f"Score {g.score}   Time {store.fmt_time(elapsed)}   "
                          f"Moves {g.moves}   {g.status}{won}", chrome)
            self.safe_add(sy + 1, 2, message[: w - 4],
                          self.CP(6) if self.has_color else 0)
        self.stdscr.refresh()

    def _draw_stock_count(self, sy, sx, cw, n, attr) -> None:
        """Write how many cards are left on the stock's back. Under the box
        is the next row's labels, which would write over it."""
        num = str(n)
        inner = cw - 2
        if self.view == "legacy":
            y, x = sy, sx + 1 + max(0, inner - len(num))
        else:
            if len(num) + 2 <= inner:
                num = f" {num} "
            y, x = sy + self.card_h - 2, sx + 1 + max(0, (inner - len(num)) // 2)
        self.safe_add(y, x, num[:inner], attr | curses.A_BOLD)

    def _slot_label(self, slot) -> str:
        kindmap = {"stock": "Stock", "waste": "Waste", "foundation": "Fnd",
                   "tableau": "", "reserve": "Res", "freecell": "Cell"}
        return kindmap.get(slot.kind, "")

    def hit_test(self, y, x) -> Optional[Tuple[int, int]]:
        return self.hit.get((y, x))
