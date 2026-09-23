"""soliterm.tui.board - draws a Solitaire board and maps clicks back to cards.

Layout mirrors AisleRiot's board: slots are positioned on a grid derived from
each game's slot rows; cards in "down" slots fan vertically, "right" slots fan
horizontally, and single slots show only the top card. The status bar shows the
score, the clock, and the game's status message - the same chrome AisleRiot
shows.
"""

from __future__ import annotations

import curses
from typing import Dict, List, Optional, Tuple

from .. import APP_NAME, camo, store
from ..engine import SUIT_SYMBOL, Card, Solitaire


# Geometry of a rendered card. Cards are drawn as multi-line boxes that overlap
# vertically (and horizontally for waste fans), AisleRiot-style: the top card of
# a pile shows full-size, covered cards peek out with their rank+suit corner.
CARD_H = 4          # full card box height in rows
PEEK_Y = 2          # rows a covered card shows in a down-fan when there's room
PEEK_X = 4          # cols a covered card shows in a right-fan (border + label)
MIN_CARD_W = 5      # narrowest card (interior fits "10S")
MAX_CARD_W = 8      # widest card (lots of horizontal room)
COL_GAP = 1         # blank columns between piles in a row
ROW_GAP = 1         # blank rows between slot-rows
MAX_RIGHT_FAN = 6   # most cards shown in a right-expanding fan (waste/reserve)
MIN_COLS = 40       # below this width/height the board can't lay out cleanly
MIN_ROWS = 14

# Box-drawing glyphs: unicode for a real card look, ASCII fallback for --ascii.
_GLYPHS = {
    True:  dict(tl="┌", tr="┐", bl="└", br="┘", h="─", v="│", back="▒"),
    False: dict(tl="+", tr="+", bl="+", br="+", h="-", v="|", back="#"),
}


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
        self._code = camo.code_lines(200, seed=1)
        self._gutter = 5            # width of the " 12  " line-number gutter
        # how far down / right the board sits inside the file when skinned
        self._code_top = 7
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
            self.min_cw = 4           # "[A♠]" / "[10S]" compact cell
            self.max_cw = 4
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
            return self.CP(6) | curses.A_BOLD
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
            # label hugs the top-left like a real card index
            line1 = gl["v"] + (" " + label).ljust(inner) + gl["v"]
            mid = gl["v"] + " " * inner + gl["v"]
            # echo the suit bottom-right on a full card for a card-y look
            suit = (SUIT_SYMBOL[card.suit] if self.symbols else card.suit)
            line3 = gl["v"] + suit.rjust(inner) + gl["v"]
            rows = [top, line1, mid, line3, bot][:max(self.card_h, 2)]
            if self.card_h == 4:
                rows = [top, line1, mid, bot]
        return rows if full else rows[:2]      # peek = top border + label

    def _card_width(self, screen_w: int, base_x: int) -> int:
        """Pick a card width that lets the widest row fit on screen.

        Tries from wide to narrow; a wider card is nicer, a narrower one keeps
        a 13-column game (Bakers Dozen) or a long waste fan on an 80-col screen.
        """
        rows = {}
        for s in self.game.slots:
            rows.setdefault(s.row, []).append(s)
        for w in range(self.max_cw, self.min_cw - 1, -1):
            peek_x = min(self.peek_x, w - 1)
            ok = True
            for sids in rows.values():
                need = base_x
                for s in sids:
                    need += w + COL_GAP
                    if s.expand == "right":
                        shown = min(len(s.cards), MAX_RIGHT_FAN)
                        need += max(0, shown - 1) * peek_x
                if need > screen_w:
                    ok = False
                    break
            if ok:
                return w
        return self.min_cw

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
                        selected_n, hint_src, hint_dst):
        """A tableau column: covered cards peek above the full-size top card."""
        n = len(slot.cards)
        peek = self._down_peek(sy, n)
        sel_start = n - selected_n if sel_here else n
        # precompute each card's top row (rounded) so cards stack consistently
        ys = [sy + int(round(i * peek)) for i in range(n)]
        for i, card in enumerate(slot.cards):
            cy = ys[i]
            is_top = i == n - 1
            is_sel = sel_here and i >= sel_start
            is_hint = (sid == hint_dst and is_top) or \
                      (sid == hint_src and i >= n - 1)
            is_cur = cur_here and is_top
            attr = self.card_attr(card, is_sel, is_hint and not is_sel,
                                  cursor=is_cur)
            # full box for the top card, just the peek (border+label) for covered
            self._blit_card(cy, sx, card, cw, is_top, attr)
            # clickable band: from this card's top row to the next card's top
            # (its exposed strip), or the full box for the top card. Later cards
            # overwrite earlier rows in the hit map, so each exposed strip maps
            # to its own card - even a 1-row strip stays individually clickable.
            band = self.card_h if is_top else max(1, ys[i + 1] - cy)
            self._register_hit(cy, sx, band, cw, sid, i)

    def _draw_right_fan(self, slot, sid, sy, sx, cw, sel_here, cur_here,
                        hint_src, hint_dst):
        """A waste/reserve fan: cards overlap leftward, top card full-width."""
        peek_x = min(self.peek_x, cw - 1)
        cards = slot.cards
        start = max(0, len(cards) - MAX_RIGHT_FAN)
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
    def _columns_in_row(self, row: int) -> List[int]:
        return [s.sid for s in self.game.slots if s.row == row]

    def _down_peek(self, sy: int, n: int) -> float:
        """Rows each COVERED card shows in a down-column (its 'peek').

        Normally PEEK_Y rows (the top border + the rank label - so every card's
        identity is visible and individually clickable). For a tall pile (a long
        Spider / Yukon column) that would run past the status bar, the peek
        shrinks - below 1 if necessary, so cards overlap more tightly and the
        full-size top card always stays on screen and clickable.
        """
        if n <= 1:
            return float(self.peek_y)
        h = self.stdscr.getmaxyx()[0]
        # rows available from the column top down to just above the status bar,
        # reserving card_h for the full-size top card
        avail = (h - 3) - sy - self.card_h
        if avail < 1:
            return 0.0
        return max(0.0, min(float(self.peek_y), avail / (n - 1)))

    def _slot_height(self, sid: int, sy: int) -> int:
        """Screen rows the slot's rendering occupies (for row stacking)."""
        slot = self.game.slots[sid]
        if slot.expand == "down" and len(slot.cards) > 1:
            n = len(slot.cards)
            peek = self._down_peek(sy, n)
            return int(round((n - 1) * peek)) + self.card_h
        return self.card_h

    def compute_positions(self) -> Dict[int, Tuple[int, int]]:
        """Assign each slot a top-left (y, x). Returns slot_id -> (y, x).

        Also sets self._cw (the chosen card width for this frame).
        """
        positions: Dict[int, Tuple[int, int]] = {}
        rows = sorted({s.row for s in self.game.slots})
        # In code-skin mode the board sits lower and indented, inside the file.
        y = (self._code_top if self.code_skin else self.origin_y)
        base_x = (self._gutter + self._code_indent if self.code_skin
                  else self.origin_x)
        w = self.stdscr.getmaxyx()[1]
        self._cw = self._card_width(w, base_x)
        peek_x = min(self.peek_x, self._cw - 1)
        for row in rows:
            sids = self._columns_in_row(row)
            x = base_x
            row_h = self.card_h
            for sid in sids:
                positions[sid] = (y, x)
                slot = self.game.slots[sid]
                x += self._cw + COL_GAP
                if slot.expand == "right":
                    shown = min(len(slot.cards), MAX_RIGHT_FAN)
                    x += max(0, shown - 1) * peek_x
                row_h = max(row_h, self._slot_height(sid, y))
            y += row_h + ROW_GAP
        return positions

    def _draw_code_skin(self):
        """Paint a code-editor backdrop the board will be drawn on top of.

        A line-number gutter down the left, source lines filling the screen,
        and a header that reads as an open file. The rows where the board sits
        are left mostly blank (the board overwrites them anyway), wrapped with
        comment lines so they look like a snapshot embedded in the source.
        """
        h, w = self.stdscr.getmaxyx()
        dim = self.CP(4)
        code_attr = self.CP(2) if self.has_color else 0   # plain source text
        # editor-style header / tab bar
        self.safe_add(0, 0, " solver.py  -  ~/work/render-core/engine "
                      .ljust(w - 1), self.CP(5) if self.has_color else curses.A_REVERSE)
        board_rows = self._board_row_span()
        board_top = min(board_rows) if board_rows else -1
        for screen_y in range(1, h - 1):
            lineno = screen_y          # 1-based line numbers down the file
            gutter = f"{lineno:>3}  "
            self.safe_add(screen_y, 0, gutter, dim)
            if screen_y in board_rows:
                # leave the interior for the board; mark the embedded snapshot
                if screen_y == board_top:
                    self.safe_add(screen_y, self._gutter,
                                  "    # --- board snapshot (live) ---", dim)
                continue
            # otherwise fill with a stable line of source
            idx = lineno % len(self._code)
            self.safe_add(screen_y, self._gutter, self._code[idx], code_attr)

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
        return w >= MIN_COLS and h >= MIN_ROWS

    def draw(self, selected_slot: Optional[int], selected_n: int,
             cursor_slot: Optional[int], hint: Optional[Tuple[int, int, str]],
             elapsed: float, message: str):
        self.stdscr.erase()
        self.hit.clear()
        if not self.fits():
            # Terminal too small to lay the board out cleanly: say so plainly
            # instead of drawing a clipped, unplayable mess.
            h, w = self.stdscr.getmaxyx()
            self.safe_add(0, 0, "Terminal too small.")
            self.safe_add(1, 0, f"Need >= {MIN_COLS}x{MIN_ROWS}, have {w}x{h}.")
            self.safe_add(2, 0, "Resize, or press q.")
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
                                     selected_n, hint_src, hint_dst)
            elif slot.expand == "right":
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
                    self.safe_add(sy + self.card_h, sx, f" {n:>2}", chrome)

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

    def _slot_label(self, slot) -> str:
        kindmap = {"stock": "Stock", "waste": "Waste", "foundation": "Fnd",
                   "tableau": "", "reserve": "Res", "freecell": "Cell"}
        return kindmap.get(slot.kind, "")

    def hit_test(self, y, x) -> Optional[Tuple[int, int]]:
        return self.hit.get((y, x))
