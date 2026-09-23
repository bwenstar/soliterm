"""soliterm.tui.app - the curses session: menu, dialogs and the play loop.

App holds what the screens share: the config and the colour flags, and for
the game in play the board, the cursor, the selection, the hint, the clock
and the message line. Every screen is a method, and the play screen handles
each key or click in a small method of its own, so a test can drive a game
on a fake window without a terminal.

Statistics use AisleRiot's Wins/Total/Percentage/Best/Worst model.
"""

from __future__ import annotations

import curses
import time
from typing import Callable, List, Optional, Tuple

from .. import APP_NAME, camo, engine, store
from ..engine import GAME_ORDER, GAMES, Solitaire
from .board import BoardUI

# What a play-screen handler returns to leave the game in play: back to the
# menu, or out of the program. None means keep playing.
MENU = "menu"
QUIT = "quit"

START_MESSAGE = "? help  h hint  m menu. Click or use arrows + Enter."


class App:
    """One curses session: the menu, the dialogs and the game in play."""

    # the game in play, set up by start_game()
    key: str
    game: Solitaire
    ui: BoardUI

    def __init__(self, stdscr, start_key: Optional[str] = None,
                 seed: Optional[int] = None, color: bool = True):
        self.stdscr = stdscr
        self.start_key = start_key
        self.seed = seed
        self.color = color
        self.cfg = store.load_config()
        # Separate the terminal's colour CAPABILITY from the player's
        # PREFERENCE so colour can be toggled live (even if launched with
        # --no-color). setup_curses() fills both in; `has_color` is the live
        # "show colour" flag the renderer reads, and flips on toggle.
        self.color_capable = False
        self.has_color = False
        # per-game state, reset by start_game()
        self.start = 0.0
        self.selected: Optional[int] = None
        self.selected_n = 1
        self.selected_exact = False   # True when the player split by clicking a card
        self.cursor = 0
        self.hint: Optional[Tuple[int, int, str]] = None
        self.message = ""
        self.recorded = False

    def setup_curses(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except curses.error:
            pass
        # We always initialise the colour pairs when the terminal supports
        # colour, so colour can come on later even if it starts off.
        self.color_capable = curses.has_colors()
        self.has_color = self.color_capable and bool(self.color)
        # a saved preference (from a previous toggle) overrides the launch default
        if "color" in self.cfg:
            self.has_color = self.color_capable and bool(self.cfg["color"])
        if self.color_capable:
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

    def CP(self, n):
        return curses.color_pair(n) if self.has_color else 0

    def safe_add(self, y, x, text, attr=0):
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    # ---- top loop ---- #
    def run(self) -> int:
        self.setup_curses()
        if self.start_key and self.play(self.start_key):
            return 0
        while True:
            choice = self.chooser()
            if choice is None or choice == "__quit__":
                return 0
            if choice == "__stats__":
                self.stats_screen()
                continue
            if self.play(choice):
                return 0

    # ---- menu ---- #
    def chooser(self) -> Optional[str]:
        stdscr, cfg, CP, safe_add = self.stdscr, self.cfg, self.CP, self.safe_add
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
    def stats_screen(self, focus_key: Optional[str] = None):
        stdscr, CP, safe_add = self.stdscr, self.CP, self.safe_add
        stdscr.erase()
        safe_add(1, 4, "Statistics", CP(4) | curses.A_BOLD)
        safe_add(2, 4, "Wins / Total / Percentage / Best & Worst winning time", CP(4))
        if store.syncing():
            safe_add(3, 4, "(shared with GNOME AisleRiot - sol)",
                     CP(6) if self.has_color else 0)
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
    def options_screen(self, key: str) -> dict:
        stdscr, cfg, CP, safe_add = self.stdscr, self.cfg, self.CP, self.safe_add
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
    def help_screen(self):
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
        self.stdscr.erase()
        for i, ln in enumerate(lines):
            self.safe_add(1 + i, 2, ln, curses.A_BOLD if i == 0 else 0)
        self.stdscr.refresh()
        self.stdscr.getch()

    # ---- camouflage / boss mode ---- #
    def camouflage_screen(self):
        """Hide the game behind live-scrolling fake 'work' output.

        Looks like an active build/test/log session. ANY key returns to the
        game exactly where it was left. The theme comes from the config
        ('camo_theme'); cycle it live with Tab/space while in camo mode.
        """
        stdscr, cfg = self.stdscr, self.cfg
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
    def play(self, key: str) -> bool:
        """Play a game of `key` until the player leaves it.

        Returns True if they quit the program, False to go back to the menu.
        """
        self.start_game(key)
        while True:
            self.game.update_status()
            self.draw()
            if self.game.is_won() and not self.recorded:
                if self.finish(True):
                    continue
                return False
            # stuck: no productive move and the player has actually started
            if self.game.moves > 0 and not self.recorded and self.game.is_stuck():
                if self.finish(False):
                    continue
                return False
            outcome = self.handle_key(self.stdscr.getch())
            if outcome is not None:
                return outcome == QUIT

    def start_game(self, key: str) -> None:
        """Deal a game of `key` and set the play screen up for it."""
        opts = {**GAMES[key].default_options(), **store.game_options(self.cfg, key)}
        self.key = key
        self.game = engine.new_solitaire(key, seed=self.seed, options=opts)
        self.cfg["last_game"] = key
        store.save_config(self.cfg)
        self.ui = self.new_board()
        self.start = time.time()
        self.selected = None
        self.selected_n = 1
        self.selected_exact = False
        self.cursor = self.first_cursor()
        self.hint = None
        self.message = START_MESSAGE
        self.recorded = False

    def new_board(self) -> BoardUI:
        ui = BoardUI(self.stdscr, self.game, self.cfg.get("symbols", True),
                     self.has_color, view=self.cfg.get("view", "expanded"))
        ui.code_skin = bool(self.cfg.get("code_skin", False))
        return ui

    def first_cursor(self) -> int:
        return self.game.ids_of("tableau")[0] if self.game.ids_of("tableau") else 0

    def elapsed(self) -> float:
        return time.time() - self.start

    def draw(self) -> None:
        self.ui.draw(self.selected, self.selected_n, self.cursor, self.hint,
                     self.elapsed(), self.message)

    def move_cursor(self, dr: int, dc: int):
        ui = self.ui
        cy, cx = ui.slot_origin.get(self.cursor, (ui.origin_y, 2))
        best = None
        bestcost = 1e9
        for s in self.game.slots:
            if s.sid == self.cursor:
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
            self.cursor = best

    def select_here(self, sid: int, card_idx: Optional[int] = None):
        """Select a run to move.

        With no card_idx (keyboard Enter / clicking the top), grab the
        largest legal run. With card_idx (clicking a specific card in a
        fanned column), split the stack: grab from that card to the bottom,
        so the player can move a sub-run just like in Spider.
        """
        game = self.game
        pile = game.cards(sid)
        if card_idx is not None and 0 <= card_idx < len(pile):
            want = len(pile) - card_idx          # from clicked card down
            if game.can_pickup(sid, want):
                self.selected = sid
                self.selected_n = want
                self.selected_exact = True
                self.message = (f"picked up {want} card(s) from {pile[card_idx]}"
                                if want > 1 else "")
                return
            # that exact split isn't movable as a unit; fall through to auto
            self.message = "those cards can't be lifted together"
        n = game.default_pickup(sid)
        if n <= 0:
            self.message = "nothing to pick up there"
            self.selected = None
            return
        self.selected = sid
        self.selected_n = n
        self.selected_exact = False
        self.message = ""

    def drop_on(self, sid: int):
        if self.selected is None:
            return
        game = self.game
        ok = game.attempt_move(self.selected, sid, self.selected_n)
        if not ok and not self.selected_exact:
            # The default selection grabs the largest movable run, but the
            # whole run may not legally land here while a SUB-run does (e.g.
            # the pile top is 4S-3S and you drop on 4H: 4S-3S won't go, but
            # the 3S alone will). Try smaller sub-runs, largest first, and
            # use the first that lands legally.
            for n in range(self.selected_n - 1, 0, -1):
                if game.attempt_move(self.selected, sid, n):
                    ok = True
                    break
        self.message = "" if ok else "illegal move"
        self.selected = None
        self.selected_exact = False
        self.hint = None

    def to_foundation(self, sid: int):
        if self.game.double_click(sid):
            self.message = ""
        else:
            self.message = "no foundation move for that card"
        self.selected = None
        self.hint = None

    def click_stock(self, sid: int):
        if not self.game.click(sid):
            self.message = self.game.deal_blocked_reason()

    def maybe_record_loss(self):
        # A started-but-unfinished game counts as a loss (AisleRiot does the
        # same: any game you start moving in counts in the total).
        if not self.recorded and not self.game.is_won() and self.game.moves > 0:
            store.record_result(self.key, False, self.elapsed())
            self.recorded = True

    def reset_for(self, new_game_fn: Callable[[], object]):
        """Run a (re)deal and reset the per-game UI state."""
        new_game_fn()
        self.start = time.time()
        self.recorded = False
        self.selected = None
        self.selected_exact = False
        self.hint = None
        self.cursor = self.first_cursor()

    def finish(self, won: bool) -> bool:
        """Record the result and show the end banner. Returns True to keep
        playing (same/new deal chosen) or False to go back to the menu."""
        if not self.recorded:
            store.record_result(self.key, won, self.elapsed())
            self.recorded = True
        choice = self.end_banner(self.elapsed(), won)
        if choice == "same":
            self.reset_for(self.game.restart)
            self.message = "replaying the same deal"
            return True
        if choice == "new":
            self.reset_for(self.game.new_game)
            self.message = "new deal"
            return True
        return False        # menu

    # ---- play-screen keys ---- #
    def handle_key(self, k: int) -> Optional[str]:
        """Act on one key read on the play screen.

        Returns MENU or QUIT when the key leaves the game, None otherwise.
        """
        if k == curses.KEY_RESIZE:
            return self.do_redraw()
        if k in (ord("q"), ord("Q")):
            return self.do_quit()
        if k in (ord("m"), ord("M")):
            return self.do_menu()
        if k == ord("?"):
            return self.do_help()
        if k in (ord("b"), ord("B"), curses.KEY_F2):
            return self.do_boss()
        if k in (ord("c"), ord("C")):
            return self.do_code_skin()
        if k in (ord("v"), ord("V")):
            return self.do_color()
        if k in (ord("x"), ord("X")):
            return self.do_view()
        if k == 27:
            return self.do_cancel()
        if k in (curses.KEY_UP, ord("k")):
            return self.do_up()
        if k in (curses.KEY_DOWN, ord("j")):
            return self.do_down()
        if k == curses.KEY_LEFT:
            return self.do_left()
        if k in (curses.KEY_RIGHT, ord("l")):
            return self.do_right()
        if k in (ord("h"), ord("H")):
            return self.do_hint()
        if k in (curses.KEY_ENTER, 10, 13, ord(" ")):
            return self.do_select()
        if k in (ord("d"), ord("D")):
            return self.do_deal()
        if k in (ord("a"), ord("A")):
            return self.do_autoplay()
        if k in (ord("f"), ord("F")):
            return self.do_foundation()
        if k in (ord("u"), ord("U")):
            return self.do_undo()
        if k in (ord("r"), ord("R")):
            return self.do_redo()
        if k == ord("n"):
            return self.do_new_deal()
        if k == ord("N"):
            return self.do_restart()
        if k in (ord("o"), ord("O")):
            return self.do_options()
        if k in (ord("s"), ord("S")):
            return self.do_stats()
        if k == curses.KEY_MOUSE:
            return self.do_mouse()
        return None

    def do_redraw(self):
        # terminal resized: nothing to do, the next frame redraws at the new
        # size (draw() reads getmaxyx() each frame and re-lays-out / guards
        # on size)
        return None

    def do_quit(self):
        self.maybe_record_loss()
        return QUIT

    def do_menu(self):
        self.maybe_record_loss()
        return MENU

    def do_help(self):
        self.help_screen()

    def do_boss(self):
        # boss / camouflage mode: hide the game behind fake work output
        self.camouflage_screen()
        self.message = ""

    def do_code_skin(self):
        # code skin: keep playing with the board wrapped in source
        ui = self.ui
        ui.code_skin = not ui.code_skin
        self.cfg["code_skin"] = ui.code_skin
        store.save_config(self.cfg)
        self.message = ("code skin on" if ui.code_skin else "code skin off")

    def do_color(self):
        # toggle colour on/off live (persisted as the new default)
        if not self.color_capable:
            self.message = "this terminal has no colour support"
        else:
            self.has_color = not self.has_color
            self.ui.has_color = self.has_color
            self.cfg["color"] = self.has_color
            store.save_config(self.cfg)
            self.message = ("colour on" if self.has_color else "colour off "
                            "(monochrome)")

    def do_view(self):
        # toggle the board view: expanded card boxes <-> legacy cells
        new_view = "legacy" if self.ui.view == "expanded" else "expanded"
        self.ui.set_view(new_view)
        self.cfg["view"] = new_view
        store.save_config(self.cfg)
        self.message = (f"{new_view} view"
                        + (" (compact)" if new_view == "legacy"
                           else " (full cards)"))

    def do_cancel(self):
        self.selected = None
        self.hint = None
        self.message = ""

    def do_up(self):
        self.hint = None
        self.move_cursor(-1, 0)

    def do_down(self):
        self.hint = None
        self.move_cursor(1, 0)

    def do_left(self):
        self.hint = None
        self.move_cursor(0, -1)

    def do_right(self):
        self.hint = None
        self.move_cursor(0, 1)

    def do_hint(self):
        self.hint = self.game.hint()
        if self.hint is None:
            self.message = self.game.no_hint_reason()
        else:
            hsrc, hdst, desc = self.hint
            # move the cursor to the suggested source for convenience
            self.cursor = hsrc
            self.message = f"Hint: {desc}"

    def do_select(self):
        self.hint = None
        if self.selected is None:
            if self.game.kind(self.cursor) == "stock":
                self.click_stock(self.cursor)
            else:
                self.select_here(self.cursor)
        elif self.cursor == self.selected:
            self.selected = None
        else:
            self.drop_on(self.cursor)

    def do_deal(self):
        self.hint = None
        if not self.game.deal():
            self.message = self.game.deal_blocked_reason()
        self.selected = None

    def do_autoplay(self):
        self.hint = None
        n = self.game.autoplay()
        self.message = f"autoplayed {n}" if n else "nothing to autoplay"
        self.selected = None

    def do_foundation(self):
        self.to_foundation(self.selected if self.selected is not None else self.cursor)

    def do_undo(self):
        self.message = "" if self.game.undo() else "nothing to undo"
        self.selected = None
        self.hint = None

    def do_redo(self):
        self.message = "" if self.game.redo() else "nothing to redo"
        self.selected = None
        self.hint = None

    def do_new_deal(self):
        # new deal: an abandoned game counts as a loss first
        self.maybe_record_loss()
        self.reset_for(self.game.new_game)
        self.message = "new deal"

    def do_restart(self):
        # restart THIS deal (replay the same shuffle); no loss recorded
        # since it's the same hand continuing
        self.reset_for(self.game.restart)
        self.message = "restarted this deal"

    def do_options(self):
        self.maybe_record_loss()
        newopts = self.options_screen(self.key)
        self.game = engine.new_solitaire(self.key, seed=self.seed, options=newopts)
        self.ui = self.new_board()
        self.reset_for(lambda: None)   # game already dealt by new_solitaire
        self.message = "options applied"

    def do_stats(self):
        self.stats_screen(self.key)

    # ---- play-screen mouse ---- #
    def do_mouse(self):
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return None
        return self.mouse_at(my, mx, bstate)

    def mouse_at(self, y: int, x: int, bstate: int):
        """Act on a mouse event at screen cell (y, x) with button state bstate."""
        target = self.ui.hit_test(y, x)
        if target is None:
            return None
        tsid, tidx = target
        self.cursor = tsid
        self.hint = None
        dbl = bstate & curses.BUTTON1_DOUBLE_CLICKED
        clicked = bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED |
                            curses.BUTTON1_RELEASED)
        if dbl:
            # double-clicking the stock is the natural "just deal"
            # gesture; elsewhere it sends the card to a foundation
            if self.game.kind(tsid) == "stock":
                self.click_stock(tsid)
            else:
                self.to_foundation(tsid)
        elif clicked:
            if self.selected is None:
                if self.game.kind(tsid) == "stock":
                    self.click_stock(tsid)
                else:
                    # split the stack at the exact card the user clicked
                    self.select_here(tsid, tidx)
            elif tsid == self.selected:
                self.selected = None
                self.selected_exact = False
            else:
                self.drop_on(tsid)
        return None

    # ---- end of game ---- #
    def end_banner(self, elapsed: float, won: bool) -> str:
        """Show the end-of-game banner with choices. Returns one of:
        'same' (replay this deal), 'new' (fresh deal), 'menu'."""
        stdscr, CP, safe_add = self.stdscr, self.CP, self.safe_add
        game = self.game
        s = store.get_stat(self.key)
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


def run(stdscr, start_key: Optional[str] = None, seed: Optional[int] = None,
        color: bool = True):
    return App(stdscr, start_key, seed, color).run()


def main(start_key: Optional[str] = None, seed: Optional[int] = None,
         color: bool = True) -> int:
    try:
        return curses.wrapper(run, start_key, seed, color)
    except curses.error as exc:
        import sys
        print(f"curses error: {exc}", file=sys.stderr)
        return 1
