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
import functools
import os
import textwrap
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Callable

from .. import APP_NAME, camo, deals, history, saves, store, themes
from ..deals import Code, Deal
from ..engine import GAME_ORDER, GAMES, Solitaire
from ..themes import CHROME, CURSOR, MESSAGE
from .board import (
    CODE_GUTTER,
    MIN_COLS,
    BoardUI,
    can_draw_unicode,
    color_attr,
    draw_code_backdrop,
    draw_too_small,
)
from .cascade import FRAME_MS, MAX_S, Cascade
from .keys import BOSS_ACTIONS, PLAY_ACTIONS, help_lines

# What a play-screen handler returns to leave the game in play: back to the
# menu, or out of the program. None means keep playing.
MENU = "menu"
QUIT = "quit"

START_MESSAGE = "? help  h hint  m menu. Click or use arrows + Enter."
# shown after any move that leaves every card free to go up
FINISH_OFFER = "Every card can go up now. Press a to finish."
# The keys that change only how the board looks, and say so where the offer
# was. The offer still stands, so a short form of it follows their note.
LOOK_ACTIONS = ("color", "theme", "four_color", "view", "code_skin")
FINISH_REMINDER = "; a to finish"
UNDONE_ALL = "back at the deal: r redoes a move, R all of them"
# a save keeps only the newest undo steps, so U on a long resumed game stops
# short of the deal
UNDONE_KEPT = "back to the oldest move saved: r redoes a move, R all of them"
# the longest a finish takes to watch, and the longest one card of it takes
FINISH_S = 1.5
FINISH_STEP_MS = 80

# The most the pick-deal box takes. The board's title line, 46 characters
# at most, has to paste in whole, even copied with the spaces around it.
DEAL_TEXT_MAX = 64
DEAL_ERROR_W = 60  # where the pick-deal box wraps a long error
DEAL_ERROR_ROWS = 3  # the most an error about text that long wraps to

# What still works while "Terminal too small" hides the board: nothing that
# could make a move the player can't see. The mouse finds no cards to hit.
# The code skin and the view change the size the board needs, so the toggle
# that hid it can bring it back.
SMALL_SCREEN_ACTIONS = ("quit", "redraw", "boss", "mouse", "code_skin", "view")

# The mouse events the game asks for: the left button only. Asking for
# REPORT_MOUSE_POSITION as well would have the terminal report every move of
# the pointer, button or not.
MOUSE_MASK = (
    curses.BUTTON1_PRESSED
    | curses.BUTTON1_RELEASED
    | curses.BUTTON1_CLICKED
    | curses.BUTTON1_DOUBLE_CLICKED
)
# what counts as clicking a menu or banner choice
LEFT_CLICK = curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED
# A second click on the same slot this soon after the first is a
# double-click. ncurses is left to report every press straight away, since
# its own double-click wait would hold each single click back as long.
DOUBLE_CLICK_S = 0.4
clock = time.monotonic  # what the double-click timer and the game clock read


class GameClock:
    """The time a game has been played, kept the way AisleRiot keeps it.

    It sets off at the first move rather than at the deal, and stands still
    while another screen (help, statistics, boss mode, a dialog) hides the
    board.
    """

    def __init__(self) -> None:
        self.holds = 0  # screens open on top of the board
        self.reset()

    def reset(self) -> None:
        self.started = False
        self.banked = 0.0  # seconds run before the last stop
        self.since: float | None = None  # clock() when it last set off

    def start(self) -> None:
        if not self.started:
            self.started = True
            if not self.holds:
                self.since = clock()

    def resume(self, seconds: float) -> None:
        """Run on from the seconds a saved game had been played."""
        self.reset()
        self.banked = float(seconds)
        self.start()

    def elapsed(self) -> float:
        if self.since is None:
            return self.banked
        return self.banked + clock() - self.since

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Stop the clock while a with block shows another screen."""
        if self.since is not None:
            self.banked += clock() - self.since
            self.since = None
        self.holds += 1
        try:
            yield
        finally:
            self.holds -= 1
            if self.started and not self.holds:
                self.since = clock()


def light_background() -> bool:
    """True if the terminal says its background is white.

    rxvt, Konsole and a few others put the colour numbers of the text and
    the background in COLORFGBG, as "0;15" or "0;default;15", and 7 or 15
    last is white. Terminals that don't say are taken to be dark.
    """
    return os.environ.get("COLORFGBG", "").split(";")[-1] in ("7", "15")


def skip_mouse_event() -> None:
    """Take a mouse event the screen has no use for off ncurses' queue,
    where the next getmouse, on another screen, would find it."""
    try:
        curses.getmouse()
    except curses.error:
        pass


def win_note(before: dict, after: dict, seconds: int, name: str) -> str:
    """What the banner adds after the best time when a win in `seconds` is
    worth a word: the first of this game, or a better time than the best
    before. The best after has to be this win's own: the first win shared
    with AisleRiot brings in the games from before sharing, and a better
    time among them."""
    if after["wins"] == 1:
        return f"  (your first {name} win!)"
    secs = max(1, seconds)  # as the statistics keep a win's time
    if before["best"] and after["best"] == secs < before["best"]:
        return f"  (new best, was {store.fmt_time(before['best'])})"
    return ""


def hides_the_board(screen):
    """Stop the game clock while the screen a method shows is up."""

    @functools.wraps(screen)
    def show(self, *args, **kwargs):
        with self.clock.paused():
            return screen(self, *args, **kwargs)

    return show


class App:
    """One curses session: the menu, the dialogs and the game in play."""

    # the game in play, set up by start_game()
    key: str
    game: Solitaire
    ui: BoardUI

    def __init__(
        self,
        stdscr,
        start: str | Deal | None = None,
        *,
        color: bool | None = None,
        symbols: bool | None = None,
        animation: bool | None = None,
        theme: str | None = None,
    ):
        self.stdscr = stdscr
        # the game to go straight into, a key or a Deal, or None for the menu
        self.start = Deal(start) if isinstance(start, str) else start
        self.color = color  # --color / --no-color, None for neither
        self.cfg = store.load_config()
        # suit symbols and box-drawing cards, or plain letters (--ascii);
        # None means the saved setting. A terminal that can't show them
        # gets the letters whatever was asked for.
        if symbols is None:
            symbols = bool(self.cfg.get("symbols", True))
        self.symbols = symbols and can_draw_unicode(stdscr)
        # cards moving on their own (the finish, the win's cascade); None
        # means the saved setting. A dumb terminal never gets them.
        if animation is None:
            animation = bool(self.cfg.get("animation", True))
        self.animation = animation and os.environ.get("TERM") != "dumb"
        self.skip_cascade = False  # a key cut the finish short: no cascade either
        # Separate the terminal's colour CAPABILITY from the player's
        # PREFERENCE so colour can be toggled live (even if launched with
        # --no-color). setup_curses() fills both in; `has_color` is the live
        # "show colour" flag the renderer reads, and flips on toggle.
        self.color_capable = False
        self.has_color = False
        # the theme for this run, then the one t last picked; a name this
        # version doesn't know plays classic, and stays in the config
        self.theme = themes.by_name(theme or self.cfg.get("theme"))
        # green clubs and orange diamonds, on the 4 key
        self.four_color = bool(self.cfg.get("four_color", False))
        # the terminal says its background is light, so the theme may want
        # darker text; and whether -1, that background, can be used at all
        self.light = light_background()
        self.default_colours = True
        # what the screen being drawn has put up so far, held back until it
        # is known to fit (see begin_page), how far right the code skin put
        # it, and whether the last one fit
        self.page: list[tuple[int, int, str, int]] | None = None
        self.page_skinned = False
        self.page_dx = 0
        self.page_fits = True
        # a click or resize that came in just behind an Esc, for read_key
        # to hand out next
        self.pending_key: int | None = None
        # the saved games the menu offers, as saves.waiting() gives them
        self.waiting: dict[str, dict] = {}
        # per-game state, reset by start_game()
        self.clock = GameClock()
        self.selected: int | None = None
        self.selected_n = 1
        self.selected_exact = False  # True when the player split by clicking a card
        self.pressed: int | None = None  # the slot the left button went down on
        self.last_click: tuple[int, float] | None = None  # (slot, clock())
        self.cursor = 0
        self.hint: tuple[int, int, str] | None = None
        self.hint_n = 1  # how many cards the hint would move
        self.message = ""
        self.recorded = False  # counted, or put away in the saves folder
        # the end banner is up, so leaving now gives the game up
        self.ending = False
        # the player took back the move that left no moves: the banner
        # isn't shown again until they make another
        self.dead_end_undone = False

    def setup_curses(self) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            # vt100, ansi and the mono terminals can't hide the cursor;
            # play on with it showing rather than refuse to start
            pass
        self.stdscr.keypad(True)
        try:
            curses.mousemask(MOUSE_MASK)
            curses.mouseinterval(0)
        except curses.error:
            pass
        # We always initialise the colour pairs when the terminal supports
        # colour, so colour can come on later even if it starts off.
        # Colour for the session: --color or --no-color, then NO_COLOR, then
        # what the player last chose with v, then on. Neither the flag nor
        # NO_COLOR is saved, so the next plain launch has the saved choice.
        self.color_capable = curses.has_colors()
        if self.color is not None:
            want = self.color
        elif os.environ.get("NO_COLOR"):
            want = False
        else:
            want = bool(self.cfg.get("color", True))
        self.has_color = self.color_capable and want
        if self.color_capable:
            curses.start_color()
            # -1 is the terminal's own background. A few colour terminals
            # can't hand it over, and black stands in for it there.
            try:
                curses.use_default_colors()
            except curses.error:
                self.default_colours = False
            self.init_pairs()

    def init_pairs(self) -> None:
        """Set the colour pairs up for the theme. Cells already on screen
        change with them, so a new theme shows at once. A pair the terminal
        has no room for is left out, and color_attr draws another."""
        room = getattr(curses, "COLOR_PAIRS", 256)
        for n, fg, bg in themes.pair_colours(
            self.theme,
            getattr(curses, "COLORS", 8),
            self.light,
            self.default_colours,
            self.four_color,
        ):
            if n < room:
                curses.init_pair(n, fg, bg)

    def CP(self, n):
        return color_attr(n) if self.has_color else 0

    def safe_add(self, y, x, text, attr=0):
        if self.page is not None:
            self.page.append((y, x, text, attr))
            return
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    def begin_page(self) -> None:
        """Start drawing a screen other than the board.

        What the screen draws is held back for end_page, which shows it only
        if it fits. Under the code skin it goes in as a comment in the same
        code file the board sits in, so the menu, the dialogs and the
        banners don't give the game away either.
        """
        self.stdscr.erase()
        self.page_skinned = bool(self.cfg.get("code_skin", False))
        self.page = []
        self.page_dx = CODE_GUTTER if self.page_skinned else 0

    def end_page(self) -> None:
        """Put the screen begun with begin_page on the terminal, or if it
        needs more rows than the terminal has, say so instead of cutting
        off its last lines."""
        page, self.page = self.page, None
        assert page is not None, "end_page without begin_page"
        h, w = self.stdscr.getmaxyx()
        rows = [y for y, _, _, _ in page]
        need = (MIN_COLS, max(rows, default=0) + 1)
        self.page_fits = w >= need[0] and h >= need[1]
        if not self.page_fits:
            draw_too_small(self, "This screen", need, self.page_skinned)
        else:
            if self.page_skinned and rows:
                top, bottom = min(rows), max(rows)
                # a comment mark at the gutter down the rows the screen uses,
                # and its text after it, so the whole block reads as a comment
                draw_code_backdrop(
                    self, dict.fromkeys(range(top, bottom + 1), "#"), last_row=max(h - 2, bottom)
                )
            for y, x, text, attr in page:
                self.safe_add(y, x + self.page_dx, text, attr)
        self.stdscr.refresh()

    def page_key(self) -> int:
        """The next key on a screen drawn with begin_page, read as read_key
        reads it. While the screen doesn't fit, only q, the boss key and a
        resize act, as the player can't see what any other key would do."""
        k = self.read_key()
        if (
            self.page_fits
            or k in (-1, ord("q"), ord("Q"), curses.KEY_RESIZE)
            or PLAY_ACTIONS.get(k) == "boss"
        ):
            return k
        if k == curses.KEY_MOUSE:
            skip_mouse_event()
        return -1

    def wait_for_key(self, draw: Callable[[], None]) -> int:
        """Show a screen until a key is pressed, and return that key.

        The mouse doesn't count and a resize draws the screen again, so the
        pointer passing over it or a retiled window can't dismiss it. The
        boss key hides it and comes back to it.
        """
        while True:
            draw()
            k = self.page_key()
            if k == curses.KEY_MOUSE:
                skip_mouse_event()
            elif self.boss_key(k):
                continue
            elif k not in (-1, curses.KEY_RESIZE):
                return k

    def boss_key(self, k: int) -> bool:
        """If k is the boss key, go into boss mode until a key is pressed.

        Every screen passes its keys through here first, so the boss key
        works everywhere, not only on the board."""
        if PLAY_ACTIONS.get(k) != "boss":
            return False
        self.camouflage_screen()
        return True

    # ---- top loop ---- #
    def run(self) -> int:
        self.setup_curses()
        try:
            if self.start:
                self.waiting = saves.waiting()
                if self.play(self.start.key, self.start):
                    return 0
            while True:
                choice = self.chooser()
                if choice is None or choice == "__quit__":
                    return 0
                if choice == "__stats__":
                    self.stats_screen()
                    continue
                if isinstance(choice, Deal):
                    if self.play(choice.key, choice):
                        return 0
                elif self.play(choice):
                    return 0
        except KeyboardInterrupt:
            # Ctrl-C quits like q, with no traceback; play() has already
            # saved or counted the game
            return 130

    def say_waiting(self) -> None:
        """Say on the bottom line why the game has stopped, while another
        copy of it has the stats lock (store.lock_wait_note)."""
        h, w = self.stdscr.getmaxyx()
        try:
            # over all the line had, as any screen may be showing
            self.stdscr.addnstr(h - 1, 0, store.LOCK_WAIT.ljust(w), max(0, w - 1))
            self.stdscr.refresh()
        except curses.error:
            pass

    # ---- menu ---- #
    def last_game(self) -> str:
        """The game played last, or Klondike before there is one."""
        last = self.cfg.get("last_game")
        return last if last in GAME_ORDER else "klondike"

    def chooser(self) -> str | Deal | None:
        """The menu. Returns the key of the game picked, the Deal asked for
        under Daily deal or Play a deal, one of the other rows, or None for q."""
        CP, safe_add = self.CP, self.safe_add
        sel = GAME_ORDER.index(self.last_game())
        extra = ["__daily__", "__deal__", "__stats__", "__quit__"]
        labels = {
            "__daily__": "Daily deal",
            "__deal__": "Play a deal",
            "__stats__": "View statistics",
            "__quit__": "Quit",
        }
        items = GAME_ORDER + extra
        # every game picked here is a plain start, so each save is offered
        self.waiting = saves.waiting()
        while True:
            self.begin_page()
            safe_add(1, 4, f"{APP_NAME}  -  choose a game", CP(CHROME) | curses.A_BOLD)
            safe_add(2, 4, "solitaire for your terminal, AisleRiot-compatible", CP(CHROME))
            for i, key in enumerate(GAME_ORDER):
                cls = GAMES[key]
                marker = "> " if i == sel else "  "
                attr = (CP(CURSOR) | curses.A_BOLD) if i == sel else 0
                about = cls.short_blurb
                if key in self.waiting:
                    save = self.waiting[key]
                    which = "daily game" if save.get("daily") else "game"
                    about = f"Resume your {which}: {self.resume_text(save)}"
                safe_add(4 + i, 6, f"{marker}{cls.name:<16} {about}", attr)
            base = 4 + len(GAME_ORDER) + 1
            for j, key in enumerate(extra):
                i = len(GAME_ORDER) + j
                label = labels[key]
                marker = "> " if i == sel else "  "
                attr = (CP(CURSOR) | curses.A_BOLD) if i == sel else 0
                safe_add(base + j, 6, f"{marker}{label}", attr)
            safe_add(
                base + len(extra) + 1,
                6,
                "Up/Down move - Enter select - mouse click - q quit",
                CP(CHROME),
            )
            self.end_page()
            k = self.page_key()
            if self.boss_key(k):
                continue
            picked = None
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(items)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(items)
            elif k in (ord("q"), ord("Q")):
                return None
            elif k == curses.KEY_MOUSE:
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                if not bstate & LEFT_CLICK:
                    # a release, say of the click on the banner's Back to
                    # menu, which sits on the row of Quit here
                    continue
                idx = my - 4
                if 0 <= idx < len(GAME_ORDER):
                    sel = idx
                    picked = items[sel]
                else:
                    bidx = my - base
                    if 0 <= bidx < len(extra):
                        sel = len(GAME_ORDER) + bidx
                        picked = items[sel]
            elif k in (curses.KEY_ENTER, 10, 13):
                picked = items[sel]
            if picked == "__daily__":
                deal = self.daily_screen()
                if deal is not None:
                    return deal
            elif picked == "__deal__":
                code = self.pick_deal_screen(None)
                if code is not None:
                    return deals.deal_of(code, self.last_game())
            elif picked is not None:
                return picked

    @hides_the_board
    def daily_screen(self) -> Deal | None:
        """The list of today's daily deals, one a game. Returns the Deal
        picked, or None if the player went back."""
        CP, safe_add = self.CP, self.safe_add
        # read once, so a list left open over midnight deals the day it shows
        day = deals.today()
        number = deals.daily_number(day)
        sel = GAME_ORDER.index(self.last_game())
        while True:
            self.begin_page()
            safe_add(1, 4, f"Daily deals for {day.isoformat()}", CP(CHROME) | curses.A_BOLD)
            for i, key in enumerate(GAME_ORDER):
                marker = "> " if i == sel else "  "
                attr = (CP(CURSOR) | curses.A_BOLD) if i == sel else 0
                safe_add(3 + i, 6, f"{marker}{GAMES[key].name:<16} {key}:{number}", attr)
            safe_add(3 + len(GAME_ORDER) + 1, 6, "Up/Down move - Enter play - Esc back", CP(CHROME))
            self.end_page()
            k = self.page_key()
            if self.boss_key(k):
                continue
            picked = None
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(GAME_ORDER)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(GAME_ORDER)
            elif k in (27, ord("q"), ord("Q")):
                return None
            elif k == curses.KEY_MOUSE:
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                idx = my - 3
                if bstate & LEFT_CLICK and 0 <= idx < len(GAME_ORDER):
                    picked = sel = idx
            elif k in (curses.KEY_ENTER, 10, 13):
                picked = sel
            if picked is not None:
                return deals.daily(GAME_ORDER[picked], day)

    # ---- statistics dialog (AisleRiot fields) ---- #
    @hides_the_board
    def stats_screen(self, focus_key: str | None = None):
        streaks = history.streaks()  # read once, not again on each resize
        self.wait_for_key(lambda: self.draw_stats(focus_key, streaks))

    def draw_stats(self, focus_key: str | None, streaks: dict[str, history.Streak]):
        CP, safe_add = self.CP, self.safe_add
        self.begin_page()
        safe_add(1, 4, "Statistics", CP(CHROME) | curses.A_BOLD)
        safe_add(2, 4, "Wins / Total / Percentage / Best & Worst winning time", CP(CHROME))
        if store.syncing():
            safe_add(
                3, 4, "(shared with GNOME AisleRiot - sol)", CP(MESSAGE) if self.has_color else 0
            )
        y = 4
        header = (
            f"  {'Game':<16}{'Wins':>6}{'Total':>7}{'Win%':>7}{'Best':>8}{'Worst':>8}"
            f"{'Streak':>8}{'Longest':>8}"
        )
        safe_add(y, 4, header, CP(MESSAGE) | curses.A_BOLD)
        y += 1
        for key in GAME_ORDER:
            s = store.get_stat(key)
            pct = store.percentage(s)
            pcts = "N/A" if pct is None else f"{pct:.0f}%"
            best = "N/A" if s["best"] == 0 else store.fmt_time(s["best"])
            worst = "N/A" if s["worst"] == 0 else store.fmt_time(s["worst"])
            # only the games played here are in the history
            cur, longest = streaks.get(key, ("N/A", "N/A"))
            attr = (CP(CURSOR) | curses.A_BOLD) if key == focus_key else 0
            safe_add(
                y,
                4,
                f"  {GAMES[key].name:<16}{s['wins']:>6}{s['total']:>7}{pcts:>7}{best:>8}{worst:>8}"
                f"{cur:>8}{longest:>8}",
                attr,
            )
            y += 1
        safe_add(y + 1, 4, "Press any key to continue.", CP(CHROME))
        self.end_page()

    # ---- options dialog ---- #
    @hides_the_board
    def options_screen(self, key: str, current: dict) -> dict | None:
        """Let the player change the options, starting from `current`.

        Returns the options chosen with Enter, or None if Esc left them.
        """
        CP, safe_add = self.CP, self.safe_add
        cls = GAMES[key]
        spec = cls.option_spec()
        opts = dict(current)
        sel = 0
        while True:
            self.begin_page()
            safe_add(1, 4, f"{cls.name} - options", CP(CHROME) | curses.A_BOLD)
            for i, (okey, label, values) in enumerate(spec):
                cur = opts.get(okey, values[0])
                vals = "  ".join(f"[{v}]" if v == cur else f" {v} " for v in values)
                marker = "> " if i == sel else "  "
                attr = (CP(CURSOR) | curses.A_BOLD) if i == sel else 0
                safe_add(3 + i, 6, f"{marker}{label:<18} {vals}", attr)
            safe_add(
                3 + len(spec) + 1, 6, "Left/Right change - Enter/q accept - Esc cancel", CP(CHROME)
            )
            self.end_page()
            k = self.page_key()
            if self.boss_key(k):
                continue
            okey, label, values = spec[sel]
            cur = opts.get(okey, values[0])
            if k == curses.KEY_MOUSE:
                skip_mouse_event()
            elif k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(spec)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(spec)
            elif k in (curses.KEY_LEFT, curses.KEY_RIGHT, ord(" ")):
                idx = values.index(cur) if cur in values else 0
                idx = (idx + (1 if k != curses.KEY_LEFT else -1)) % len(values)
                opts[okey] = values[idx]
            elif k in (curses.KEY_ENTER, 10, 13, ord("q"), ord("Q")):
                return opts
            elif k == 27:
                return None

    @hides_the_board
    def pick_deal_screen(self, current: Solitaire | None) -> Code | None:
        """Ask for a deal number or a share code to play instead of
        `current`, or from the menu when that's None. Returns what was
        typed, read by deals.parse, or None if the player went back."""
        CP, safe_add = self.CP, self.safe_add
        text, error = "", ""
        while True:
            self.begin_page()
            safe_add(1, 4, "Play a deal", CP(CHROME) | curses.A_BOLD)
            if current is not None:
                this = f"daily {current.daily}" if current.daily else current.deal_number
                safe_add(3, 6, f"This deal   : {this}")
                safe_add(4, 6, f"Share code  : {deals.code_of(current)}")
                y = 6
            else:
                y = 3
            safe_add(y, 6, f"Type a deal number, or a share code like {deals.EXAMPLE}")
            if current is None:
                y += 1
                safe_add(y, 6, f"A number on its own plays {GAMES[self.last_game()].name}.")
            prompt, room = f"> {text}_", self.stdscr.getmaxyx()[1] - 7 - self.page_dx
            if len(prompt) > room:
                # a long code scrolls, so its end and the cursor stay in view
                prompt = "< " + prompt[len(prompt) - room + 2 :]
            safe_add(y + 1, 6, prompt, CP(CURSOR) | curses.A_BOLD)
            for i, line in enumerate(textwrap.wrap(error, DEAL_ERROR_W)[:DEAL_ERROR_ROWS]):
                safe_add(y + 2 + i, 6, line, CP(MESSAGE))
            safe_add(y + 2 + DEAL_ERROR_ROWS, 6, "Enter play - Esc back", CP(CHROME))
            self.end_page()
            k = self.page_key()
            # b is a letter here, so only F2 hides the box, unless it doesn't
            # fit and can't be typed in anyway
            if (k == curses.KEY_F2 or not self.page_fits) and self.boss_key(k):
                continue
            if k == curses.KEY_MOUSE:
                skip_mouse_event()
            elif k == 27 or (k in (ord("q"), ord("Q")) and not self.page_fits):
                return None
            elif k in (curses.KEY_ENTER, 10, 13):
                if not text:
                    return None
                try:
                    return deals.parse(text)
                except ValueError as exc:
                    error = str(exc)
            elif k in (curses.KEY_BACKSPACE, 127, 8):
                text, error = text[:-1], ""
            elif k == 21:  # Ctrl-U
                text, error = "", ""
            elif 32 <= k <= 126 and len(text) < DEAL_TEXT_MAX:
                text, error = text + chr(k), ""

    @hides_the_board
    def confirm(self, *lines: str) -> bool:
        """Ask a yes or no question: y is yes, n, Esc, q or Enter is no.

        Enter says no so that an Enter too many, after the one that closed
        the screen before, can't answer yes to giving a game up."""
        CP, safe_add = self.CP, self.safe_add
        while True:
            self.begin_page()
            for i, line in enumerate(lines):
                safe_add(2 + i, 6, line, (CP(MESSAGE) | curses.A_BOLD) if i == 0 else 0)
            safe_add(3 + len(lines), 6, "y  yes     n / Esc / Enter  no", CP(CHROME))
            self.end_page()
            k = self.page_key()
            if self.boss_key(k):
                continue
            if k == curses.KEY_MOUSE:
                skip_mouse_event()
            elif k in (ord("y"), ord("Y")):
                return True
            elif k in (ord("n"), ord("N"), ord("q"), ord("Q"), 27, curses.KEY_ENTER, 10, 13):
                return False

    # ---- help overlay ---- #
    @hides_the_board
    def help_screen(self):
        lines = [
            f"{APP_NAME} - controls",
            "",
            *help_lines(),
            "",
            "  Press any key to continue.",
        ]

        def draw():
            self.begin_page()
            for i, ln in enumerate(lines):
                self.safe_add(1 + i, 2, ln, curses.A_BOLD if i == 0 else 0)
            self.end_page()

        self.wait_for_key(draw)

    # ---- camouflage / boss mode ---- #
    @hides_the_board
    def camouflage_screen(self):
        """Hide the game behind live-scrolling fake 'work' output.

        Looks like an active build/test/log session. Any key returns to the
        game exactly where it was left; the mouse and a resized window don't.
        The theme comes from the config ('camo_theme'); cycle it live with
        Tab while in camo mode.
        """
        stdscr, cfg = self.stdscr, self.cfg
        theme = cfg.get("camo_theme", camo.DEFAULT_THEME)
        if theme not in camo.THEMES:
            theme = camo.DEFAULT_THEME
        gen = camo.stream(theme)
        h, w = stdscr.getmaxyx()
        buf: list[str] = []
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
                for i, ln in enumerate(buf[-(h - 1) :]):
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
                    if k == curses.KEY_MOUSE:
                        # a click to focus the window, the wheel or the
                        # pointer passing over must not give the game away
                        try:
                            curses.getmouse()
                        except curses.error:
                            pass
                        continue
                    if k == curses.KEY_RESIZE:
                        break  # draw the disguise again at the new size
                    if k != -1:
                        if BOSS_ACTIONS.get(k) == "next_disguise":
                            # cycle theme without leaving camo
                            idx = camo.THEMES.index(theme)
                            theme = camo.THEMES[(idx + 1) % len(camo.THEMES)]
                            cfg["camo_theme"] = theme
                            store.save_config(cfg)
                            gen = camo.stream(theme)
                            buf = []
                            break
                        return  # any other key exits camo mode
                    time.sleep(0.04)
                    slept += 0.04
        finally:
            stdscr.nodelay(False)

    # ---- play one game ---- #
    def play(self, key: str, deal: Deal | None = None) -> bool:
        """Play a game of `key` until the player leaves it: `deal` if given,
        or a random deal with the saved options.

        Returns True if they quit the program, False to go back to the menu.
        """
        try:
            self.start_game(key, deal)
            while True:
                self.game.update_status()
                self.draw()
                if self.game.is_won() and not self.recorded:
                    if self.finish(True):
                        continue
                    return False
                # stuck: no productive move and the player has actually started
                if (
                    self.clock.started
                    and not self.recorded
                    and not self.dead_end_undone
                    and self.game.is_stuck()
                ):
                    if self.finish(False):
                        continue
                    return False
                outcome = self.handle_key(self.read_key())
                if outcome is not None:
                    return outcome == QUIT
        except KeyboardInterrupt:
            # Ctrl-C, wherever in the game it comes, leaves the way q does,
            # but on the end banner there is nothing left to come back to
            if not hasattr(self, "game"):  # there is none before the first deal
                raise
            try:
                if self.ending:
                    self.give_up()
                else:
                    self.put_away()
            finally:
                # another Ctrl-C, say as it waited for another copy's lock
                if not self.recorded and (self.game.is_won() or self.under_way()):
                    store.cut_short(self.game.gamedef.name)
            raise

    def read_key(self, wait_ms: int = 1000) -> int:
        """The next key on the play screen or a dialog, or -1 for an Alt
        combination.

        A terminal sends Alt+key as Esc and the key together. An Esc with
        another key already queued behind it is not the Esc key, and neither
        half should act: Alt+n would otherwise deal a new hand. An Esc with
        a click or a resize behind it is, and both act in turn.

        With no key for wait_ms (a second unless the caller says) it returns
        -1 too, so play() draws the board again and the clock on the status
        line ticks.
        """
        if self.pending_key is not None:
            k, self.pending_key = self.pending_key, None
            return k
        self.stdscr.timeout(wait_ms)
        try:
            k = self.stdscr.getch()
        finally:
            self.stdscr.timeout(-1)  # the other screens wait for a key
        if k != 27:
            return k
        self.stdscr.nodelay(True)
        try:
            follow = self.stdscr.getch()
        finally:
            self.stdscr.nodelay(False)
        if follow in (curses.KEY_MOUSE, curses.KEY_RESIZE):
            # the next read hands it out, so a click is still taken off
            # ncurses' queue with getmouse rather than left for a later one
            self.pending_key = follow
            return 27
        return 27 if follow == -1 else -1

    def start_game(self, key: str, deal: Deal | None = None) -> None:
        """Deal a game of `key` (`deal` if given), or resume the one saved
        for it, and set the play screen up for it."""
        self.key = key
        deal = deal or Deal(key)
        # only a plain start, with no deal number or options, or a daily
        # over a save of the same daily, resumes
        resumes = deals.resumes(deal, self.waiting.get(key))
        listed = resumes and key in self.waiting
        # the menu listed it, but another window has had it since
        gone = listed and not os.path.exists(saves.save_path(key))
        # From the take on, a resumed game is out of the saves folder until
        # put_away puts it back, so a signal waits until it is set up
        with store.signals_held():
            resumed = saves.take(key) if resumes else None
            self.put_in_play(deal, resumed)
        if not os.path.exists(saves.save_path(key)):
            self.waiting.pop(key, None)  # taken or set aside, so there's room
        if resumed is not None:
            done = self.resume_text({"seconds": resumed[1], "moves": self.game.moves})
            self.message = f"Resumed your game ({done}). n deals a new hand."
            if self.game.finish_moves():
                self.message = FINISH_OFFER  # as after the move that left it so
        elif gone:
            self.message = "Your saved game was picked up somewhere else, so this is a new deal."
        elif listed:
            self.message = "Your saved game couldn't be read, so this is a new deal."
        else:
            self.message = self.unkept_note() or START_MESSAGE

    def put_in_play(self, deal: Deal, resumed: tuple[Solitaire, int] | None) -> None:
        """Put the resumed game in play, or else a new deal of `deal`, with
        the play screen set up for it."""
        if resumed is None:
            self.game = self.new_game(deal)
        else:
            self.game = resumed[0]
            self.game.symbols = self.symbols
        self.cfg["last_game"] = self.key
        store.save_config(self.cfg)
        self.ui = self.new_board()
        self.clock.reset()
        if resumed is not None:
            self.clock.resume(resumed[1])
        self.selected = None
        self.selected_n = 1
        self.selected_exact = False
        self.pressed = None
        self.last_click = None
        self.cursor = self.first_cursor()
        self.hint = None
        self.message = START_MESSAGE
        self.recorded = False
        self.dead_end_undone = False
        self.skip_cascade = False

    def unkept_note(self) -> str:
        """What a new deal says while a game of its kind is saved, as then
        leaving this one can't keep it too; "" when there's room for it.

        The slot is looked at again, for a game another window has saved
        since the menu, and the menu's list of saves is brought up to date.
        """
        saved = saves.waiting(self.key).get(self.key)
        if saved is None:
            self.waiting.pop(self.key, None)
            return ""
        self.waiting[self.key] = saved
        return f"a saved {GAMES[self.key].name} game is waiting, so this one won't be kept"

    @staticmethod
    def resume_text(save: dict) -> str:
        """How far a saved game got, as in 0:42, 31 moves."""
        return f"{store.fmt_time(save['seconds'])}, {store.moves_text(save['moves'])}"

    def new_game(self, deal: Deal) -> Solitaire:
        """Deal what `deal` asks for, over the saved options."""
        game = deals.deal_game(deal, store.game_options(self.cfg, deal.key))
        # so a hint names the cards the way the board draws them
        game.symbols = self.symbols
        return game

    def new_board(self) -> BoardUI:
        ui = BoardUI(
            self.stdscr,
            self.game,
            self.symbols,
            self.has_color,
            view=self.cfg.get("view", "expanded"),
        )
        ui.code_skin = bool(self.cfg.get("code_skin", False))
        return ui

    def first_cursor(self) -> int:
        """The first column with a face-up card on top, else the first
        column: Triple Peaks starts on its bottom row, not a face-down peak."""
        columns = self.game.ids_of("tableau")
        faced = [sid for sid in columns if any(c.face_up for c in self.game.cards(sid)[-1:])]
        return (faced or columns or [0])[0]

    def seconds(self) -> int:
        """The game time in whole seconds, rounded as AisleRiot rounds a win
        time, so the status line, the banner and the statistics agree."""
        return int(self.clock.elapsed() + 0.5)

    def draw(self) -> None:
        self.keep_cursor_on_a_card()
        self.ui.draw(
            self.selected,
            self.selected_n,
            self.cursor,
            self.hint,
            self.seconds(),
            self.message,
            self.hint_n,
        )

    def keep_cursor_on_a_card(self) -> None:
        """Move the cursor off a slot the board no longer draws, as a card
        played from a peak leaves, onto the nearest one it does: the nearest
        card that will play, if one will, else the nearest face-up card."""
        ui = self.ui
        if not ui.hidden(self.cursor):
            return
        cy, cx = ui.slot_origin.get(self.cursor, (ui.origin_y, 2))

        def away(sid: int) -> int:
            oy, ox = ui.slot_origin.get(sid, (0, 0))
            return abs(oy - cy) + abs(ox - cx)

        shown = [s.sid for s in self.game.slots if not ui.hidden(s.sid)]
        plays = {src for src, _dst, _n in self.game.legal_moves()}
        playable = [sid for sid in shown if sid in plays]
        face_up = [sid for sid in shown if any(c.face_up for c in self.game.cards(sid)[-1:])]
        self.cursor = min(playable or face_up or shown, key=away, default=self.cursor)

    def move_cursor(self, dr: int, dc: int):
        ui = self.ui
        cy, cx = ui.slot_origin.get(self.cursor, (ui.origin_y, 2))
        best = None
        bestcost = 1e9
        for s in self.game.slots:
            if s.sid == self.cursor or ui.hidden(s.sid):
                continue
            oy, ox = ui.slot_origin.get(s.sid, (0, 0))
            dy, dx = oy - cy, ox - cx
            if dr < 0 and dy >= 0:  # want up
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

    def select_here(self, sid: int, card_idx: int | None = None):
        """Select a run to move.

        With no card_idx (keyboard Enter / clicking the top), grab the
        largest legal run. With card_idx (clicking a specific card in a
        fanned column), split the stack: grab from that card to the bottom,
        so the player can move a sub-run just like in Spider.
        """
        game = self.game
        pile = game.cards(sid)
        if card_idx is not None and 0 <= card_idx < len(pile):
            want = len(pile) - card_idx  # from clicked card down
            if game.can_pickup(sid, want):
                self.selected = sid
                self.selected_n = want
                self.selected_exact = True
                # the card as the board shows it, with a suit symbol or not
                named = pile[card_idx].label(self.symbols)
                self.message = f"picked up {want} cards from {named}" if want > 1 else ""
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
            reason = self.game.no_foundation_reason(sid)
            self.message = reason or "no foundation move for that card"
        self.selected = None
        self.hint = None

    def click_stock(self, sid: int):
        # a deal clears what was said about the move before, as a move does
        ok = self.game.click(sid)
        self.message = "" if ok else self.game.deal_blocked_reason()

    def under_way(self) -> bool:
        # A game is under way from its first move, as in AisleRiot, even if
        # undo takes every move back, until it is counted or put away.
        # Restarting the deal (N, or Replay on the banner) is the exception.
        # AisleRiot's Restart deals the same hand again without touching the
        # statistics, and the next game on that hand counts from its own
        # first move.
        return self.clock.started and not self.recorded and not self.game.is_won()

    def give_up(self):
        """Count the game in play as lost, if it is under way."""
        if self.under_way():
            self.count(False, self.seconds())

    def put_away(self):
        """Keep the game in play for next time, on q, m, Ctrl-C, SIGHUP or
        SIGTERM. One that can't be kept counts as lost, and saves.keep has
        left a notice saying why. One won but not counted yet, as when
        Ctrl-C comes as the finish lands the last card, counts as won.

        Signals wait until it is done, so one can't land between a save
        that failed and the loss it leaves, and have the save tried again.
        A deal never started has nothing to keep, so it doesn't wait for
        the stats lock either.
        """
        won = self.game.is_won() and not self.recorded
        if not won and not self.under_way():
            return
        with store.signals_held():
            if won:
                self.count(True, self.seconds())
                return
            self.recorded = saves.keep(self.game, self.seconds())
            if not self.recorded:
                self.give_up()

    def count(self, won: bool, seconds: int) -> dict:
        """Count the game in play in the statistics, once, and return its
        statistics after. Every game the TUI counts comes through here."""
        with store.signals_held():
            stat = history.record(self.game, won, seconds)
            self.recorded = True
        return stat

    def reset_for(self, new_game_fn: Callable[[], object]):
        """Run a (re)deal and reset the per-game UI state."""
        new_game_fn()
        self.clock.reset()
        self.recorded = False
        self.dead_end_undone = False
        self.skip_cascade = False
        self.selected = None
        self.selected_exact = False
        self.pressed = None
        self.last_click = None
        self.hint = None
        self.cursor = self.first_cursor()

    def finish(self, won: bool) -> bool:
        """Show the end banner and act on the choice. Returns True to keep
        playing (undo, same or new deal chosen) or False to go back to the
        menu.

        A win is recorded at once, and the cards bounce off the board before
        the banner comes up. A game with no moves left is recorded as lost
        only when the player gives it up for a new deal or the menu. Undo
        plays on, and replaying the deal counts nothing, as AisleRiot's
        Restart doesn't (see under_way)."""
        seconds = self.seconds()
        note = ""
        if won and not self.recorded:
            before = store.get_stat(self.key)
            after = self.count(True, seconds)
            note = win_note(before, after, seconds, self.game.gamedef.name)
            # counted first, so Ctrl-C while the cards fly keeps the win
            self.win_cascade()
        # left set if Ctrl-C comes, for play() to see as it goes
        self.ending = True
        choice = self.end_banner(seconds, won, note)
        self.ending = False
        if choice == "undo":
            self.do_undo()
            self.dead_end_undone = True
            return True
        if choice == "same":
            self.reset_for(self.game.restart)
            self.message = "replaying the same deal"
            return True
        self.give_up()
        if choice == "new":
            self.reset_for(self.game.new_game)
            self.message = self.unkept_note() or "new deal"
            return True
        return False  # menu

    # ---- play-screen keys ---- #
    def handle_key(self, k: int) -> str | None:
        """Act on one key read on the play screen, as KEYMAP says.

        Returns MENU or QUIT when the key leaves the game, None otherwise.
        """
        action = PLAY_ACTIONS.get(k)
        if action is None:
            return None
        if action not in SMALL_SCREEN_ACTIONS and not self.ui.fits():
            return None
        moves = self.game.moves
        outcome = getattr(self, "do_" + action)()
        if self.game.moves > 0:
            self.clock.start()  # the game is under way
        if self.game.moves > moves:
            self.dead_end_undone = False
        if self.game.moves != moves and self.game.finish_moves():
            self.message = FINISH_OFFER
        elif action in LOOK_ACTIONS and self.game.finish_moves():
            self.message += FINISH_REMINDER
        return outcome

    def do_redraw(self):
        # terminal resized: nothing to do, the next frame redraws at the new
        # size (draw() reads getmaxyx() each frame and re-lays-out / guards
        # on size)
        return None

    def do_quit(self):
        self.put_away()
        return QUIT

    def do_menu(self):
        self.put_away()
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
        self.message = "code skin on" if ui.code_skin else "code skin off"

    def do_color(self):
        # toggle colour on/off live (persisted as the new default)
        if not self.color_capable:
            self.message = "this terminal has no colour support"
        else:
            self.has_color = not self.has_color
            self.ui.has_color = self.has_color
            self.cfg["color"] = self.has_color
            store.save_config(self.cfg)
            self.message = "colour on" if self.has_color else "colour off (monochrome)"

    def do_theme(self):
        # the next theme, on screen at once (cells change with their pairs)
        # and kept as the new default
        if not self.color_capable:
            self.message = "this terminal has no colour support"
            return
        self.theme = themes.next_theme(self.theme)
        self.init_pairs()
        self.cfg["theme"] = self.theme.name
        store.save_config(self.cfg)
        self.message = f"{self.theme.name} theme{self.colour_note()}"

    def do_four_color(self):
        # green clubs and orange diamonds on and off, kept as the new default
        if not self.color_capable:
            self.message = "this terminal has no colour support"
            return
        self.four_color = not self.four_color
        self.init_pairs()
        self.cfg["four_color"] = self.four_color
        store.save_config(self.cfg)
        state = "on" if self.four_color else "off"
        # kept all the same, for the next terminal, which may have the room
        short = self.four_color and getattr(curses, "COLOR_PAIRS", 256) <= themes.CLUB_FACE
        note = " (this terminal can't show it)" if short else self.colour_note()
        self.message = f"four-colour deck {state}{note}"

    def colour_note(self) -> str:
        """What keeps a change of colours from showing, to end a message with."""
        return "" if self.has_color else " (colour is off, v turns it on)"

    def do_view(self):
        # toggle the board view: expanded card boxes <-> legacy cells
        new_view = "legacy" if self.ui.view == "expanded" else "expanded"
        self.ui.set_view(new_view)
        self.cfg["view"] = new_view
        store.save_config(self.cfg)
        self.message = f"{new_view} view" + (
            " (compact)" if new_view == "legacy" else " (full cards)"
        )

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
            # the game says why, and whether an undo could still help
            self.message = self.game.no_hint_reason()
        else:
            hsrc, hdst, desc = self.hint
            self.hint_n = self.hinted_run(hsrc, hdst)
            # move the cursor to the suggested source for convenience
            self.cursor = hsrc
            self.message = f"Hint: {desc}"

    def hinted_run(self, src: int, dst: int) -> int:
        """How many cards the hint from src to dst would move: as many as
        best_move() says when the hint is that move, else the most dst takes."""
        mv = self.game.best_move()
        if mv is not None and mv[:2] == (src, dst):
            return mv[2]
        takes = [n for (s, d, n) in self.game.legal_moves() if (s, d) == (src, dst)]
        return max(takes, default=1)

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

    def do_lift_more(self):
        self.change_lift(1)

    def do_lift_fewer(self):
        self.change_lift(-1)

    def change_lift(self, step: int):
        """Hold one card more (step 1) or fewer (step -1) of the selected
        pile, so the keyboard can move part of a run as a click mid-stack
        does."""
        if self.selected is None:
            self.message = "pick up a run first, then + / - to change it"
            return
        pile = self.game.cards(self.selected)
        n = self.selected_n + step
        while 0 < n <= len(pile):
            if self.game.can_pickup(self.selected, n):
                self.selected_n = n
                self.selected_exact = True  # the player chose the size
                # named, as it may be in a row of cards sharing it
                named = pile[-n].label(self.symbols)
                self.message = f"holding {n} cards from {named}" if n > 1 else f"holding {named}"
                return
            n += step
        self.message = "can't lift any more cards" if step > 0 else "can't lift any fewer cards"

    def do_deal(self):
        self.hint = None
        ok = self.game.deal()
        self.message = "" if ok else self.game.deal_blocked_reason()
        self.selected = None

    def do_autoplay(self):
        self.hint = None
        self.selected = None
        moves = self.game.finish_moves()
        if moves:
            self.play_finish(len(moves))
            return
        n = self.game.autoplay()
        self.message = f"autoplayed {n}" if n else "nothing to autoplay"

    def play_finish(self, steps: int) -> None:
        """Send every card left up, one at a time, each foundation lit as a
        card lands on it. A key sends the rest up at once, skips the win's
        cascade, and is not passed on, except the boss key, which hides the
        screen straight after. The clock stands still while the cards land,
        so watching costs no time. On a terminal slow to draw, what is left
        once FINISH_S is up goes up at once."""
        wait = max(1, min(FINISH_STEP_MS, int(FINISH_S * 1000 / steps)))
        cut: list[int] = []
        self.message = ""  # the offer, which is being taken up
        started = clock()

        def land(src: int, dst: int) -> None:
            if cut or clock() - started >= FINISH_S:
                return
            self.hint = (-1, dst, "")  # lights the foundation only
            self.draw()
            k = self.read_key(wait)
            if self.cuts_short(k):
                cut.append(k)

        with self.clock.paused():
            n = self.game.finish(land if self.animation else None)
        self.hint = None
        self.message = f"autoplayed {n}"
        if cut:
            self.skip_cascade = True
            self.boss_key(cut[0])

    def cuts_short(self, k: int) -> bool:
        """True if k, read while the cards move on their own, should stop
        them: any key, a resize or a left click, but not the wheel, a button
        let go or a click ncurses can't report."""
        if k == -1:
            return False
        if k != curses.KEY_MOUSE:
            return True
        try:
            bstate = curses.getmouse()[4]
        except curses.error:
            return False
        return bool(bstate & LEFT_CLICK)

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

    def do_undo_all(self):
        if not self.game.undo_all():
            self.message = "nothing to undo"
        else:
            # each step back takes a move off, so only the deal is at 0
            self.message = UNDONE_KEPT if self.game.moves else UNDONE_ALL
        self.selected = None
        self.hint = None

    def do_redo_all(self):
        self.message = "" if self.game.redo_all() else "nothing to redo"
        self.selected = None
        self.hint = None

    def do_new_deal(self):
        # new deal: an abandoned game counts as a loss first
        self.give_up()
        self.reset_for(self.game.new_game)
        self.message = self.unkept_note() or "new deal"

    def do_restart(self):
        # restart THIS deal (replay the same shuffle); no loss recorded,
        # as in AisleRiot (see under_way)
        self.reset_for(self.game.restart)
        self.message = "restarted this deal"

    def do_pick_deal(self):
        code = self.pick_deal_screen(self.game)
        if code is None:
            self.message = "kept this deal"
            return
        if code.key is None:
            # a number on its own: this game, with the options in play
            deal = Deal(self.key, code.number, dict(self.game.options))
        else:
            deal = Deal(code.key, code.number, code.options)
        # the same share code is the same game, options and number
        label = deals.share_code(deal.key, code.number, deal.options)
        if label == deals.code_of(self.game):
            self.message = "that's the deal in play (N starts it over)"
            return
        if self.clock.started and not self.confirm(
            f"Leave this game for {label}?", "The game in play will count as lost."
        ):
            self.message = "kept this deal"
            return
        self.give_up()
        self.start_game(deal.key, deal)
        self.message = self.unkept_note() or f"playing {label}"

    def do_options(self):
        # Every option there is changes the deal (the draw, the suits), so
        # new options mean a new deal. The game in play is only given up
        # once something has changed, and after asking if it's under way.
        if not GAMES[self.key].option_spec():
            self.message = f"{self.game.gamedef.name} has no options"
            return
        newopts = self.options_screen(self.key, self.game.options)
        if newopts is None or newopts == self.game.options:
            self.message = "options unchanged"
            return
        if self.clock.started and not self.confirm(
            "Deal again with the new options?", "The game in play will count as lost."
        ):
            self.message = "options unchanged"
            return
        store.set_game_options(self.cfg, self.key, newopts)
        store.save_config(self.cfg)
        self.give_up()
        # the next deal, the way n deals it, so a session on a chosen deal
        # goes on to the next number
        self.game.new_game(options=newopts)
        self.ui = self.new_board()
        self.reset_for(lambda: None)  # already dealt, just above
        self.message = self.unkept_note() or "options applied"

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
        if not bstate & MOUSE_MASK:
            # the pointer moving, the wheel or another button: none of them
            # should shift the cursor or wipe the hint
            return
        target = self.ui.hit_test(y, x)
        if bstate & curses.BUTTON1_RELEASED:
            # A release only counts as the end of a press made on this board.
            # The click that started the game on the menu or the end banner
            # lets go over the new deal, and that must not touch it.
            # The press has done the click already, so letting go over the
            # same slot adds nothing; letting go over another slot drops the
            # cards the press picked up there, which makes a drag.
            pressed, self.pressed = self.pressed, None
            if (
                pressed is None
                or target is None
                or target[0] == pressed
                or self.selected != pressed
            ):
                return
            self.cursor = target[0]
            self.hint = None
            self.drop_on(target[0])
            # the press began a drag, not a double-click
            self.last_click = None
            return
        if bstate & curses.BUTTON1_PRESSED:
            self.pressed = target[0] if target else None
        if target is None:
            return
        tsid, tidx = target
        self.cursor = tsid
        self.hint = None
        dbl = bstate & curses.BUTTON1_DOUBLE_CLICKED
        clicked = bstate & LEFT_CLICK
        now = clock()
        if clicked and self.last_click is not None:
            last_sid, last_time = self.last_click
            dbl = dbl or (last_sid == tsid and now - last_time <= DOUBLE_CLICK_S)
        # the click after a double-click starts afresh
        self.last_click = None if dbl else (tsid, now)
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

    # ---- end of game ---- #
    def win_cascade(self) -> None:
        """Bounce the cards off the board after a win, as the old Windows
        Solitaire did, until they have gone, a few seconds are up or a key
        is pressed. The boss key hides the screen at once.

        It draws over the board play() has just drawn and never erases, so
        the cards leave trails. Not under the code skin, where flying cards
        would give the game away."""
        skip, self.skip_cascade = self.skip_cascade, False
        ui = self.ui
        if skip or not self.animation or ui.code_skin or not ui.fits():
            return
        piles = ui.cascade_piles()
        if not piles:
            return
        h, w = self.stdscr.getmaxyx()
        fall = Cascade(piles, h, w, ui.card_h, ui.card_w, seed=self.game.deal_number)
        started = clock()
        while not fall.done and clock() - started < MAX_S:
            for y, x, card in fall.step():
                ui.draw_card_at(y, x, card)
            self.stdscr.refresh()
            k = self.read_key(FRAME_MS)
            if self.cuts_short(k):
                self.boss_key(k)  # b or F2: the disguise, straight away
                return

    def banner_lines(self, seconds: int, won: bool, stat: dict, note: str = "") -> list[str]:
        """The rows of the end banner from row 4 down, "" for a blank one.
        The choices go under the last of them. The rows of the best time and
        the streak are there even when empty, so the choices don't move up.
        A note from win_note goes after the best time."""
        game = self.game
        pct = store.percentage(stat)
        pcts = "N/A" if pct is None else f"{pct:.0f}%"
        streak = history.streak_text(self.key) if won else ""
        deal = f"daily {game.daily}" if game.daily else game.deal_number
        return [
            f"Game        : {game.gamedef.name}",
            f"Deal        : {deal}   share code {deals.code_of(game)}",
            f"Time        : {store.fmt_time(seconds)}",
            f"Score       : {game.score}",
            f"Moves       : {game.moves}",
            "",
            f"Wins/Total  : {stat['wins']}/{stat['total']}  ({pcts})",
            f"Best time   : {store.fmt_time(stat['best'])}{note}" if stat["best"] else "",
            f"Streak      : {streak}" if streak else "",
        ]

    @hides_the_board
    def end_banner(self, seconds: int, won: bool, note: str = "") -> str:
        """Show the end-of-game banner with choices. Returns one of:
        'undo' (take the last move back, when no moves are left), 'same'
        (replay this deal), 'new' (fresh deal), 'menu'. The note goes after
        the best time."""
        CP, safe_add = self.CP, self.safe_add
        game = self.game
        s = store.get_stat(self.key)
        if not self.recorded:
            # a loss is recorded on leaving the banner for a new deal or the
            # menu, so count it already, as the statistics will then
            s = {**s, "total": s["total"] + 1}
        lines = self.banner_lines(seconds, won, s, note)
        top = 4 + len(lines) + 1  # the row of the first choice
        share = ""  # the line a daily leaves to paste to friends
        if game.daily:
            share = deals.share_line(game.gamedef.name, game.daily, won, seconds, game.moves)
        choices = [("same", "Replay this deal"), ("new", "New deal"), ("menu", "Back to menu")]
        keys = "s/n/m"
        can_undo = not won and game.can_undo()
        if can_undo:
            choices.insert(0, ("undo", "Undo move"))
            keys = "u/" + keys
        sel = 0
        while True:
            self.begin_page()
            if won:
                safe_add(2, 6, "*** YOU WIN! ***", CP(MESSAGE) | curses.A_BOLD)
            else:
                safe_add(2, 6, "No moves left - game over.", CP(MESSAGE) | curses.A_BOLD)
            for i, line in enumerate(lines):
                if line:
                    safe_add(4 + i, 6, line)
            for i, (_, label) in enumerate(choices):
                marker = "> " if i == sel else "  "
                attr = (CP(CURSOR) | curses.A_BOLD) if i == sel else 0
                safe_add(top + i, 6, f"{marker}{label}", attr)
            footer = top + len(choices) + 1
            safe_add(footer, 6, f"Up/Down + Enter, or {keys}. Click to choose.", CP(CHROME))
            h, w = self.stdscr.getmaxyx()
            # only on a row the terminal has, as the banner fits without it
            if share and footer + 2 < h:
                # plain, to copy, and nearer the edge if the margin would clip it
                x = 6 if self.page_dx + 6 + len(share) <= w - 1 else 2
                safe_add(footer + 2, x, share)
            self.end_page()
            k = self.page_key()
            if self.boss_key(k):
                continue
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(choices)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(choices)
            elif k in (ord("u"), ord("U")) and can_undo:
                return "undo"
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
                # only a left click on a choice's text takes it, never the
                # pointer passing over it, the wheel or a stray release
                row, col = my - top, mx - self.page_dx
                if (
                    bstate & LEFT_CLICK
                    and 0 <= row < len(choices)
                    and 6 <= col < 6 + len("> " + choices[row][1])
                ):
                    return choices[row][0]


def run(stdscr, start: str | Deal | None = None, **options):
    """Run a session on stdscr. The settings go on to App by name, so a new
    one only has to be added there."""
    app = App(stdscr, start, **options)
    # a wait for another copy of the game is told of on the screen
    with store.lock_wait_note(app.say_waiting):
        return app.run()


def main(start: str | Deal | None = None, **options) -> int:
    # After an Esc, ncurses waits ESCDELAY ms (a whole second by default) to
    # see whether a key sequence follows, so the Esc key felt dead. It reads
    # the variable when curses starts; a value the player set is kept.
    os.environ.setdefault("ESCDELAY", "25")
    try:
        return curses.wrapper(run, start, **options)
    except curses.error as exc:
        import sys

        print(f"curses error: {exc}", file=sys.stderr)
        return 1
