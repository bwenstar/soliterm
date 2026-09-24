"""soliterm.tui - the curses front-end (keyboard + mouse).

Layout mirrors AisleRiot's board: slots are positioned on a grid derived from
each game's slot rows; cards in "down" slots fan vertically, "right" slots fan
horizontally, and single slots show only the top card. The status bar shows the
score, the clock, and the game's status message - the same chrome AisleRiot
shows. Statistics use AisleRiot's Wins/Total/Percentage/Best/Worst model.
"""

from __future__ import annotations

import curses
import time
from typing import Dict, List, Optional, Tuple

from . import APP_NAME, camo, engine, store
from .engine import GAME_ORDER, GAMES, SUIT_SYMBOL, Card, Solitaire


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


class _Quit(Exception):
    pass


class BoardUI:
    """Renders a Solitaire board and maps screen coords back to (slot, index)."""

    def __init__(self, stdscr, game: Solitaire, symbols: bool, has_color: bool,
                 view: str = "expanded"):
        self.stdscr = stdscr
        self.game = game
        self.symbols = symbols
        game.symbols = symbols      # so hints name cards as this board draws them
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

    def draw(self, selected_slot: Optional[int], selected_n: int,
             cursor_slot: Optional[int], hint: Optional[Tuple[int, int, str]],
             elapsed: float, message: str):
        self.stdscr.erase()
        self.hit.clear()
        h, w = self.stdscr.getmaxyx()
        if w < MIN_COLS or h < MIN_ROWS:
            # Terminal too small to lay the board out cleanly: say so plainly
            # instead of drawing a clipped, unplayable mess.
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


def selected_n_for_hint(g, hint):
    # used only to highlight a hint's source run; default 1 card
    return 1


def run(stdscr, start_key: Optional[str] = None, seed: Optional[int] = None,
        color: bool = True):
    curses.curs_set(0)
    stdscr.keypad(True)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    except curses.error:
        pass
    # Separate the terminal's colour CAPABILITY from the player's PREFERENCE so
    # colour can be toggled live (even if launched with --no-color). We always
    # initialise the colour pairs when the terminal supports colour; `has_color`
    # is the live "show colour" flag the renderer reads, and flips on toggle.
    color_capable = curses.has_colors()
    has_color = color_capable and bool(color)
    cfg = store.load_config()
    # a saved preference (from a previous toggle) overrides the launch default
    if "color" in cfg:
        has_color = color_capable and bool(cfg["color"])
    if color_capable:
        curses.start_color()
        curses.use_default_colors()
        # Face-up cards are drawn like real cards: a white card face with the
        # suit colour as the text - red for hearts/diamonds, true black for
        # spades/clubs - so black suits read as black, not white, on any
        # terminal background.
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_WHITE)     # red card face
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)   # black card face
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)   # selection
        curses.init_pair(4, curses.COLOR_CYAN, -1)                    # chrome
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # cursor
        curses.init_pair(6, curses.COLOR_YELLOW, -1)                  # hint/msg
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)    # card back
        curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_GREEN)   # red card, selected

    def CP(n):
        return curses.color_pair(n) if has_color else 0

    def safe_add(y, x, text, attr=0):
        h, w = stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    # ---- menu ---- #
    def chooser() -> Optional[str]:
        sel = GAME_ORDER.index(cfg.get("last_game", "klondike")) \
            if cfg.get("last_game") in GAME_ORDER else 0
        extra = ["__stats__", "__quit__"]
        items = GAME_ORDER + extra
        while True:
            stdscr.erase()
            safe_add(1, 4, f"{APP_NAME}  -  choose a game", CP(4) | curses.A_BOLD)
            safe_add(2, 4, "solitaire for your terminal, AisleRiot-compatible", CP(4))
            for i, key in enumerate(GAME_ORDER):
                cls = GAMES[key]
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(4 + i, 6, f"{marker}{cls.name:<16} {cls.blurb}", attr)
            base = 4 + len(GAME_ORDER) + 1
            for j, key in enumerate(extra):
                i = len(GAME_ORDER) + j
                label = "View statistics" if key == "__stats__" else "Quit"
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(base + j, 6, f"{marker}{label}", attr)
            safe_add(base + len(extra) + 1, 6,
                     "Up/Down move - Enter select - mouse click - q quit", CP(4))
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(items)
            elif key in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(items)
            elif key in (ord("q"), ord("Q")):
                return None
            elif key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                idx = my - 4
                if 0 <= idx < len(GAME_ORDER):
                    sel = idx
                    if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                        return items[sel]
                else:
                    bidx = my - base
                    if 0 <= bidx < len(extra):
                        sel = len(GAME_ORDER) + bidx
                        if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                            return items[sel]
            elif key in (curses.KEY_ENTER, 10, 13):
                return items[sel]

    # ---- statistics dialog (AisleRiot fields) ---- #
    def stats_screen(focus_key: Optional[str] = None):
        stdscr.erase()
        safe_add(1, 4, "Statistics", CP(4) | curses.A_BOLD)
        safe_add(2, 4, "Wins / Total / Percentage / Best & Worst winning time", CP(4))
        if store.syncing():
            safe_add(3, 4, "(shared with GNOME AisleRiot - sol)",
                     CP(6) if has_color else 0)
        y = 4
        header = f"  {'Game':<16}{'Wins':>6}{'Total':>7}{'Win%':>7}{'Best':>8}{'Worst':>8}"
        safe_add(y, 4, header, CP(6) | curses.A_BOLD)
        y += 1
        for key in GAME_ORDER:
            s = store.get_stat(key)
            pct = store.percentage(s)
            pcts = "N/A" if pct is None else f"{pct:.0f}%"
            best = "N/A" if s["best"] == 0 else store.fmt_time(s["best"])
            worst = "N/A" if s["worst"] == 0 else store.fmt_time(s["worst"])
            attr = (CP(5) | curses.A_BOLD) if key == focus_key else 0
            safe_add(y, 4,
                     f"  {GAMES[key].name:<16}{s['wins']:>6}{s['total']:>7}"
                     f"{pcts:>7}{best:>8}{worst:>8}", attr)
            y += 1
        safe_add(y + 1, 4, "Press any key to continue.", CP(4))
        stdscr.refresh()
        stdscr.getch()

    # ---- options dialog ---- #
    def options_screen(key: str) -> dict:
        cls = GAMES[key]
        spec = cls.option_spec()
        opts = {**cls.default_options(), **store.game_options(cfg, key)}
        if not spec:
            return opts
        sel = 0
        while True:
            stdscr.erase()
            safe_add(1, 4, f"{cls.name} - options", CP(4) | curses.A_BOLD)
            for i, (okey, label, values) in enumerate(spec):
                cur = opts.get(okey, values[0])
                vals = "  ".join(f"[{v}]" if v == cur else f" {v} " for v in values)
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(3 + i, 6, f"{marker}{label:<18} {vals}", attr)
            safe_add(3 + len(spec) + 1, 6,
                     "Left/Right change - Enter/q accept (saved)", CP(4))
            stdscr.refresh()
            k = stdscr.getch()
            okey, label, values = spec[sel]
            cur = opts.get(okey, values[0])
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(spec)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(spec)
            elif k in (curses.KEY_LEFT, curses.KEY_RIGHT, ord(" ")):
                idx = values.index(cur) if cur in values else 0
                idx = (idx + (1 if k != curses.KEY_LEFT else -1)) % len(values)
                opts[okey] = values[idx]
            elif k in (curses.KEY_ENTER, 10, 13, ord("q"), ord("Q")):
                store.set_game_options(cfg, key, opts)
                store.save_config(cfg)
                return opts

    # ---- help overlay ---- #
    def help_screen():
        lines = [
            f"{APP_NAME} - controls",
            "",
            "  Arrow keys          move the cursor between slots",
            "  Enter / Space       pick up the cursor's run; press again to drop",
            "  Mouse click         click a card to pick it up; click a target",
            "                      to drop. Click a card mid-stack to split the",
            "                      pile and lift it plus the cards below it.",
            "  Mouse double-click   send a card to a foundation; deal on stock",
            "  Esc                 cancel the current selection / clear hint",
            "  d                   deal from the stock (where applicable)",
            "  a                   autoplay safe cards to the foundations",
            "  f                   send the selected/cursor card to a foundation",
            "  h                   show a hint (highlights a legal move)",
            "  b / F2              boss mode: hide the game behind 'work' output",
            "                      (any key returns; Tab cycles the disguise)",
            "  c                   code skin: keep playing inside a code file",
            "  v                   toggle colour on / off (monochrome)",
            "  x                   toggle view: full cards <-> compact cells",
            "  n  new deal   N  restart this deal   u  undo   r  redo",
            "  o  options    s  statistics   ?  help   m  menu   q  quit",
            "",
            "  Foundations build up by suit; tableau rules vary by game.",
            "  Press any key to continue.",
        ]
        stdscr.erase()
        for i, ln in enumerate(lines):
            safe_add(1 + i, 2, ln, curses.A_BOLD if i == 0 else 0)
        stdscr.refresh()
        stdscr.getch()

    # ---- camouflage / boss mode ---- #
    def camouflage_screen():
        """Hide the game behind live-scrolling fake 'work' output.

        Looks like an active build/test/log session. ANY key returns to the
        game exactly where it was left. The theme comes from the config
        ('camo_theme'); cycle it live with Tab/space while in camo mode.
        """
        theme = cfg.get("camo_theme", camo.DEFAULT_THEME)
        if theme not in camo.THEMES:
            theme = camo.DEFAULT_THEME
        gen = camo.stream(theme)
        h, w = stdscr.getmaxyx()
        buf: List[str] = []
        # Make a key wait briefly so the screen scrolls on its own, like a
        # live session, but returns instantly when the player taps a key.
        stdscr.nodelay(True)
        try:
            stdscr.erase()
            while True:
                h, w = stdscr.getmaxyx()
                # add a few new lines per tick so it visibly scrolls
                for _ in range(2):
                    buf.append(next(gen))
                if len(buf) > h:
                    buf = buf[-h:]
                stdscr.erase()
                for i, ln in enumerate(buf[-(h - 1):]):
                    # plain default colour - looks like an ordinary terminal
                    try:
                        stdscr.addnstr(i, 0, ln, w - 1)
                    except curses.error:
                        pass
                stdscr.refresh()
                # poll for a keypress while the output "runs"
                slept = 0.0
                while slept < 0.22:
                    k = stdscr.getch()
                    if k != -1:
                        if k in (ord("\t"),):
                            # cycle theme without leaving camo
                            idx = camo.THEMES.index(theme)
                            theme = camo.THEMES[(idx + 1) % len(camo.THEMES)]
                            cfg["camo_theme"] = theme
                            store.save_config(cfg)
                            gen = camo.stream(theme)
                            buf = []
                            break
                        return        # any other key exits camo mode
                    time.sleep(0.04)
                    slept += 0.04
        finally:
            stdscr.nodelay(False)

    # ---- play one game ---- #
    def play(key: str):
        nonlocal has_color           # the colour toggle ('v') flips this live
        opts = {**GAMES[key].default_options(), **store.game_options(cfg, key)}
        game = engine.new_solitaire(key, seed=seed, options=opts)
        cfg["last_game"] = key
        store.save_config(cfg)
        ui = BoardUI(stdscr, game, cfg.get("symbols", True), has_color,
                     view=cfg.get("view", "expanded"))
        ui.code_skin = bool(cfg.get("code_skin", False))

        start = time.time()
        selected: Optional[int] = None
        selected_n = 1
        selected_exact = False        # True when the player split by clicking a card
        cursor = game.ids_of("tableau")[0] if game.ids_of("tableau") else 0
        hint = None
        message = "? help  h hint  m menu. Click or use arrows + Enter."
        recorded = False

        def order_for_cursor() -> List[int]:
            return [s.sid for s in game.slots]

        def move_cursor(dr: int, dc: int):
            nonlocal cursor
            slots = game.slots
            cy, cx = ui.slot_origin.get(cursor, (ui.origin_y, 2))
            best = None
            bestcost = 1e9
            for s in slots:
                if s.sid == cursor:
                    continue
                oy, ox = ui.slot_origin.get(s.sid, (0, 0))
                dy, dx = oy - cy, ox - cx
                if dr < 0 and dy >= 0:   # want up
                    continue
                if dr > 0 and dy <= 0:
                    continue
                if dc < 0 and dx >= 0:
                    continue
                if dc > 0 and dx <= 0:
                    continue
                cost = abs(dy) * (1 if dr else 4) + abs(dx) * (1 if dc else 4)
                if cost < bestcost:
                    bestcost, best = cost, s.sid
            if best is not None:
                cursor = best

        def select_here(sid: int, card_idx: Optional[int] = None):
            """Select a run to move.

            With no card_idx (keyboard Enter / clicking the top), grab the
            largest legal run. With card_idx (clicking a specific card in a
            fanned column), split the stack: grab from that card to the bottom,
            so the player can move a sub-run just like in Spider.
            """
            nonlocal selected, selected_n, selected_exact, message
            pile = game.cards(sid)
            if card_idx is not None and 0 <= card_idx < len(pile):
                want = len(pile) - card_idx          # from clicked card down
                if game.can_pickup(sid, want):
                    selected = sid
                    selected_n = want
                    selected_exact = True
                    message = (f"picked up {want} card(s) from {pile[card_idx]}"
                               if want > 1 else "")
                    return
                # that exact split isn't movable as a unit; fall through to auto
                message = "those cards can't be lifted together"
            n = game.default_pickup(sid)
            if n <= 0:
                message = "nothing to pick up there"
                selected = None
                return
            selected = sid
            selected_n = n
            selected_exact = False
            message = ""

        def drop_on(sid: int):
            nonlocal selected, selected_exact, message, hint
            if selected is None:
                return
            ok = game.attempt_move(selected, sid, selected_n)
            if not ok and not selected_exact:
                # The default selection grabs the largest movable run, but the
                # whole run may not legally land here while a SUB-run does (e.g.
                # the pile top is 4S-3S and you drop on 4H: 4S-3S won't go, but
                # the 3S alone will). Try smaller sub-runs, largest first, and
                # use the first that lands legally.
                for n in range(selected_n - 1, 0, -1):
                    if game.attempt_move(selected, sid, n):
                        ok = True
                        break
            message = "" if ok else "illegal move"
            selected = None
            selected_exact = False
            hint = None

        def to_foundation(sid: int):
            nonlocal selected, message, hint
            if game.double_click(sid):
                message = ""
            else:
                message = "no foundation move for that card"
            selected = None
            hint = None

        def maybe_record_loss():
            # A started-but-unfinished game counts as a loss (AisleRiot does the
            # same: any game you start moving in counts in the total).
            nonlocal recorded
            if not recorded and not game.is_won() and game.moves > 0:
                store.record_result(key, False, time.time() - start)
                recorded = True

        def reset_for(new_game_fn):
            """Run a (re)deal and reset the per-game UI state."""
            nonlocal start, recorded, selected, selected_exact, hint, cursor, message
            new_game_fn()
            start = time.time()
            recorded = False
            selected = None
            selected_exact = False
            hint = None
            cursor = game.ids_of("tableau")[0] if game.ids_of("tableau") else 0

        def finish(won: bool) -> bool:
            """Record the result and show the end banner. Returns True to keep
            playing (same/new deal chosen) or False to go back to the menu."""
            nonlocal recorded, message
            if not recorded:
                store.record_result(key, won, time.time() - start)
                recorded = True
            choice = end_banner(key, game, time.time() - start, won)
            if choice == "same":
                reset_for(game.restart)
                message = "replaying the same deal"
                return True
            if choice == "new":
                reset_for(game.new_game)
                message = "new deal"
                return True
            return False        # menu

        while True:
            game.update_status()
            ui.draw(selected, selected_n, cursor, hint, time.time() - start, message)
            if game.is_won() and not recorded:
                if finish(True):
                    continue
                return
            # stuck: no productive move and the player has actually started
            if game.moves > 0 and not recorded and game.is_stuck():
                if finish(False):
                    continue
                return
            k = stdscr.getch()
            if k == curses.KEY_RESIZE:
                # terminal resized: just loop to redraw at the new size (draw()
                # reads getmaxyx() each frame and re-lays-out / guards on size)
                continue
            if k in (ord("q"), ord("Q")):
                maybe_record_loss()
                raise _Quit()
            if k in (ord("m"), ord("M")):
                maybe_record_loss()
                return
            if k == ord("?"):
                help_screen(); continue
            if k in (ord("b"), ord("B"), curses.KEY_F2):
                # boss / camouflage mode: hide the game behind fake work output
                camouflage_screen()
                message = ""
                continue
            if k in (ord("c"), ord("C")):
                # code skin: keep playing with the board wrapped in source
                ui.code_skin = not ui.code_skin
                cfg["code_skin"] = ui.code_skin
                store.save_config(cfg)
                message = ("code skin on" if ui.code_skin else "code skin off")
                continue
            if k in (ord("v"), ord("V")):
                # toggle colour on/off live (persisted as the new default)
                if not color_capable:
                    message = "this terminal has no colour support"
                else:
                    has_color = not has_color
                    ui.has_color = has_color
                    cfg["color"] = has_color
                    store.save_config(cfg)
                    message = ("colour on" if has_color else "colour off "
                               "(monochrome)")
                continue
            if k in (ord("x"), ord("X")):
                # toggle the board view: expanded card boxes <-> legacy cells
                new_view = "legacy" if ui.view == "expanded" else "expanded"
                ui.set_view(new_view)
                cfg["view"] = new_view
                store.save_config(cfg)
                message = (f"{new_view} view"
                           + (" (compact)" if new_view == "legacy"
                              else " (full cards)"))
                continue
            if k == 27:
                selected = None; hint = None; message = ""; continue
            if k in (curses.KEY_UP, ord("k")):
                hint = None; move_cursor(-1, 0); continue
            if k in (curses.KEY_DOWN, ord("j")):
                hint = None; move_cursor(1, 0); continue
            if k == curses.KEY_LEFT:
                hint = None; move_cursor(0, -1); continue
            if k in (curses.KEY_RIGHT, ord("l")):
                hint = None; move_cursor(0, 1); continue
            if k in (ord("h"), ord("H")):
                hint = game.hint()
                if hint is None:
                    message = game.no_hint_reason()
                else:
                    hsrc, hdst, desc = hint
                    # move the cursor to the suggested source for convenience
                    cursor = hsrc
                    message = f"Hint: {desc}"
                continue
            if k in (curses.KEY_ENTER, 10, 13, ord(" ")):
                hint = None
                if selected is None:
                    if game.kind(cursor) == "stock":
                        if not game.click(cursor):
                            message = game.deal_blocked_reason()
                    else:
                        select_here(cursor)
                else:
                    if cursor == selected:
                        selected = None
                    else:
                        drop_on(cursor)
                continue
            if k in (ord("d"), ord("D")):
                hint = None
                if not game.deal():
                    message = game.deal_blocked_reason()
                selected = None; continue
            if k in (ord("a"), ord("A")):
                hint = None
                n = game.autoplay()
                message = f"autoplayed {n}" if n else "nothing to autoplay"
                selected = None; continue
            if k in (ord("f"), ord("F")):
                to_foundation(selected if selected is not None else cursor)
                continue
            if k in (ord("u"), ord("U")):
                message = "" if game.undo() else "nothing to undo"
                selected = None; hint = None; continue
            if k in (ord("r"), ord("R")):
                message = "" if game.redo() else "nothing to redo"
                selected = None; hint = None; continue
            if k == ord("n"):
                # new deal: an abandoned game counts as a loss first
                maybe_record_loss()
                reset_for(game.new_game)
                message = "new deal"
                continue
            if k in (ord("N"),):
                # restart THIS deal (replay the same shuffle); no loss recorded
                # since it's the same hand continuing
                reset_for(game.restart)
                message = "restarted this deal"
                continue
            if k in (ord("o"), ord("O")):
                maybe_record_loss()
                newopts = options_screen(key)
                game = engine.new_solitaire(key, seed=seed, options=newopts)
                ui = BoardUI(stdscr, game, cfg.get("symbols", True), has_color,
                             view=cfg.get("view", "expanded"))
                ui.code_skin = bool(cfg.get("code_skin", False))
                reset_for(lambda: None)   # game already dealt by new_solitaire
                message = "options applied"; continue
            if k in (ord("s"), ord("S")):
                stats_screen(key); continue
            if k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                target = ui.hit_test(my, mx)
                if target is None:
                    continue
                tsid, tidx = target
                cursor = tsid
                hint = None
                dbl = bstate & curses.BUTTON1_DOUBLE_CLICKED
                clicked = bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED |
                                    curses.BUTTON1_RELEASED)
                if dbl:
                    # double-clicking the stock is the natural "just deal"
                    # gesture; elsewhere it sends the card to a foundation
                    if game.kind(tsid) == "stock":
                        if not game.click(tsid):
                            message = game.deal_blocked_reason()
                    else:
                        to_foundation(tsid)
                elif clicked:
                    if selected is None:
                        if game.kind(tsid) == "stock":
                            if not game.click(tsid):
                                message = game.deal_blocked_reason()
                        else:
                            # split the stack at the exact card the user clicked
                            select_here(tsid, tidx)
                    else:
                        if tsid == selected:
                            selected = None
                            selected_exact = False
                        else:
                            drop_on(tsid)
                continue

    def end_banner(key: str, game: Solitaire, elapsed: float, won: bool) -> str:
        """Show the end-of-game banner with choices. Returns one of:
        'same' (replay this deal), 'new' (fresh deal), 'menu'."""
        s = store.get_stat(key)
        pct = store.percentage(s)
        choices = [("same", "Replay this deal"),
                   ("new", "New deal"),
                   ("menu", "Back to menu")]
        sel = 0
        while True:
            stdscr.erase()
            if won:
                safe_add(2, 6, "*** YOU WIN! ***", CP(6) | curses.A_BOLD)
            else:
                safe_add(2, 6, "No moves left - game over.",
                         CP(6) | curses.A_BOLD)
            safe_add(4, 6, f"Game        : {game.gamedef.name}")
            safe_add(5, 6, f"Time        : {store.fmt_time(elapsed)}")
            safe_add(6, 6, f"Score       : {game.score}")
            safe_add(7, 6, f"Moves       : {game.moves}")
            pcts = "N/A" if pct is None else f"{pct:.0f}%"
            safe_add(9, 6, f"Wins/Total  : {s['wins']}/{s['total']}  ({pcts})")
            if s["best"]:
                safe_add(10, 6, f"Best time   : {store.fmt_time(s['best'])}")
            for i, (_, label) in enumerate(choices):
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(12 + i, 6, f"{marker}{label}", attr)
            safe_add(12 + len(choices) + 1, 6,
                     "Up/Down + Enter, or s/n/m. Click to choose.", CP(4))
            stdscr.refresh()
            k = stdscr.getch()
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(choices)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(choices)
            elif k in (ord("s"), ord("S")):
                return "same"
            elif k in (ord("n"), ord("N")):
                return "new"
            elif k in (ord("m"), ord("M"), ord("q"), ord("Q")):
                return "menu"
            elif k in (curses.KEY_ENTER, 10, 13, ord(" ")):
                return choices[sel][0]
            elif k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                row = my - 12
                if 0 <= row < len(choices):
                    return choices[row][0]

    # ---- top loop ---- #
    try:
        if start_key:
            play(start_key)
        while True:
            choice = chooser()
            if choice is None or choice == "__quit__":
                return 0
            if choice == "__stats__":
                stats_screen()
                continue
            play(choice)
    except _Quit:
        return 0


def main(start_key: Optional[str] = None, seed: Optional[int] = None,
         color: bool = True) -> int:
    try:
        return curses.wrapper(run, start_key, seed, color)
    except curses.error as exc:
        import sys
        print(f"curses error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # tui is the curses view, not the entry point: the launcher (cli) sets
    # up config, colour, stats sharing, and text-mode fallback. Defer to it
    # so there is one supported way to start the game.
    from . import cli
    raise SystemExit(cli.main())
