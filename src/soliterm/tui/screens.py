"""soliterm.tui.screens - the screens other than the board.

The menu, the daily deals, the statistics and each game's records, the
options, the pick-deal box, the yes-or-no question, the help, the pause,
boss mode and the end banner, and what they share to put a page up, read
its keys and copy a share code. They are methods of Screens, which App
takes in, so that each reaches the config, the colours and the game in
play just as the play screen does.
"""

from __future__ import annotations

import curses
import functools
import textwrap
import time
from typing import TYPE_CHECKING, Any, Callable

from .. import APP_NAME, camo, clipboard, deals, history, records, saves, store
from ..deals import Code, Deal
from ..engine import GAME_ORDER, GAMES, Solitaire
from ..themes import CHROME, CURSOR, MESSAGE
from .board import CODE_GUTTER, MIN_COLS, draw_code_backdrop, draw_too_small, drawn_attr
from .keys import BOSS_ACTIONS, PLAY_ACTIONS, help_lines

if TYPE_CHECKING:
    from .app import GameClock

# The most the pick-deal box takes. The board's title line, 46 characters
# at most, has to paste in whole, even copied with the spaces around it.
DEAL_TEXT_MAX = 64
DEAL_ERROR_W = 60  # where the pick-deal box wraps a long error
DEAL_ERROR_ROWS = 3  # the most an error about text that long wraps to

# what counts as clicking a menu or banner choice
LEFT_CLICK = curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED
# The wheel, one notch up or down. Python before 3.10 has no BUTTON5
# constants; this is where ncurses 6 and PDCurses both put it.
WHEEL_UP = curses.BUTTON4_PRESSED
WHEEL_DOWN = getattr(curses, "BUTTON5_PRESSED", 0x200000)

# The fewest rows a list of games scrolls in. With fewer to spare, its
# screen says the terminal is too small, as one that doesn't scroll does.
LIST_MIN = 3


def skip_mouse_event() -> None:
    """Take a mouse event the screen has no use for off ncurses' queue,
    where the next getmouse, on another screen, would find it."""
    try:
        curses.getmouse()
    except curses.error:
        pass


def days_text(n: int) -> str:
    """A count of days as it reads in a sentence: 1 day, 2 days."""
    return "1 day" if n == 1 else f"{n} days"


def daily_streak_text(streak: history.Streak, won_today: bool) -> str:
    """The daily list's line about the days in a row with a daily won."""
    if not streak.current:
        if not streak.longest:
            return "Daily streak: none yet, win a daily to start one"
        longest = days_text(streak.longest)
        return f"Daily streak: none now (longest {longest}), win a daily to start one"
    text = f"Daily streak: {days_text(streak.current)}"
    if streak.longest > streak.current:
        text += f" (longest {streak.longest})"
    # it runs to yesterday until one of today's is won
    return text if won_today else text + ", win one today to keep it"


def hides_the_board(screen):
    """Stop the game clock while the screen a method shows is up."""

    @functools.wraps(screen)
    def show(self, *args, **kwargs):
        with self.clock.paused():
            return screen(self, *args, **kwargs)

    return show


class Scroll:
    """A list of rows to pick from, drawn in the rows a screen has for it.

    When they are too few for the whole list, a line where the hidden
    rows would be says how many there are, and the list scrolls to keep
    the row picked in view. It never starts one row down, as the line
    saying so would hide just the row it stands for.

    The rows picked from can go on past the list, as the menu's go on
    to the rows under its games, which don't scroll.
    """

    def __init__(self, count: int, sel: int, stay: int = 0) -> None:
        self.count = count  # the rows in the list
        self.total = count + stay  # and the rows after it to pick from
        self.sel = sel  # the row picked
        self.top = 0  # the first row in view
        self.room = count  # the rows of the screen the list takes

    def fit(self, room: int) -> None:
        """Give the list `room` rows of the screen, or LIST_MIN if that's
        fewer, and scroll it so the row picked is in view."""
        self.room = min(self.count, max(LIST_MIN, room))
        last = self.count - self.room + 1 if self.count > self.room else 0
        self.top = min(self.top, last)
        if self.top == 1:
            self.top = 0
        if not 0 <= self.sel < self.count:
            return
        if self.sel < self.top:
            self.top = 0 if self.sel < 2 else self.sel
        while self.sel not in self.shown():
            self.top = 2 if self.top == 0 else self.top + 1

    def shown(self) -> range:
        """The rows in view."""
        n = self.room - (self.top > 0)
        if self.top + n < self.count:
            n -= 1  # for the line saying there are more below
        return range(self.top, self.top + n)

    def lines(self) -> list[int | str]:
        """What goes on each of the list's rows of the screen, from the
        first down: a row of the list, or a line saying how many more
        there are above or below."""
        shown = self.shown()
        below = self.count - shown.stop
        return [
            *([f"^ {self.top} more above"] if self.top else []),
            *shown,
            *([f"v {below} more below"] if below else []),
        ]

    def key(self, k: int) -> bool:
        """Move the pick as key k does, if it's one that moves it: Up and
        Down go round from one end to the other, PgUp and PgDn go a page
        and Home and End to the ends."""
        last = self.total - 1
        if k in (curses.KEY_UP, ord("k")):
            self.sel = (self.sel - 1) % self.total
        elif k in (curses.KEY_DOWN, ord("j")):
            self.sel = (self.sel + 1) % self.total
        elif k in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            page = len(self.shown())
            step = page if k == curses.KEY_NPAGE else -page
            if self.sel < self.count:
                # the list turns the page as well, so the pick stays
                # where it was among the rows in view
                self.top = max(0, self.top + step)
            self.sel = min(last, max(0, self.sel + step))
        elif k == curses.KEY_HOME:
            self.sel = 0
        elif k == curses.KEY_END:
            self.sel = last
        else:
            return False
        return True

    def mouse(self, bstate: int, dy: int) -> int | None:
        """Act on a mouse event dy rows below the top of the list: the
        wheel moves the pick a row, stopping at the ends, and a left click
        on a line saying there are more turns the page. A left click on a
        row of the list picks it, and returns it; anything else returns
        None."""
        if bstate & WHEEL_UP:
            self.sel = max(0, self.sel - 1)
        elif bstate & WHEEL_DOWN:
            self.sel = min(self.total - 1, self.sel + 1)
        elif bstate & LEFT_CLICK and 0 <= dy < self.room:
            at = self.lines()[dy]
            if isinstance(at, int):
                self.sel = at
                return at
            self.key(curses.KEY_PPAGE if dy == 0 else curses.KEY_NPAGE)
        return None


class Reader(Scroll):
    """Lines to read rather than rows to pick from, as on the help. The
    keys that move the pick on a Scroll, and the wheel, move the lines in
    view here, and stop at the ends."""

    def __init__(self, count: int) -> None:
        super().__init__(count, -1)  # no row picked

    def scrolls(self) -> bool:
        """Whether the lines are too many for their rows of the screen."""
        return self.count > self.room

    def key(self, k: int) -> bool:
        """Move the lines in view as key k does, if it's one that moves
        them: Up and Down a line, PgUp and PgDn a page and Home and End to
        the ends."""
        last = self.count - self.room + 1 if self.scrolls() else 0
        if k in (curses.KEY_UP, ord("k")):
            top = self.top - 1
        elif k in (curses.KEY_DOWN, ord("j")):
            top = self.top + 1
        elif k in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            page = len(self.shown())
            top = self.top + (page if k == curses.KEY_NPAGE else -page)
        elif k == curses.KEY_HOME:
            top = 0
        elif k == curses.KEY_END:
            top = last
        else:
            return False
        if top == 1:
            # not one line down, where the line saying so would hide it
            top = 2 if self.top == 0 else 0
        self.top = min(last, max(0, top))
        return True

    def mouse(self, bstate: int, dy: int) -> int | None:
        """Act on a mouse event dy rows below the top of the lines: the
        wheel moves them a line, and a left click on a line saying there
        are more turns the page. There's nothing to pick, so it returns
        None."""
        if bstate & WHEEL_UP:
            self.key(curses.KEY_UP)
        elif bstate & WHEEL_DOWN:
            self.key(curses.KEY_DOWN)
        elif bstate & LEFT_CLICK and 0 <= dy < self.room and isinstance(self.lines()[dy], str):
            self.key(curses.KEY_PPAGE if dy == 0 else curses.KEY_NPAGE)
        return None


# The widest line of a game's records, which fits 80 columns under the
# code skin with the page's indent and the room draw_list leaves for a mark
RECORDS_W = 68


def option_words(key: str, options: dict) -> str:
    """The options a record was set with, as "draw 3, redeals standard", or
    "" for a game with none."""
    given = {**GAMES[key].default_options(), **options}
    return ", ".join(f"{name} {given[name]}" for name, _, _ in GAMES[key].option_spec())


def deal_text(key: str, best: records.Best) -> str:
    """The deal a record was set on: the day of a daily, or the share code
    that plays it again."""
    if best.daily:
        return f"daily {best.daily}"
    return "" if best.deal is None else deals.share_code(key, best.deal, best.options)


def score_text(key: str, best: records.Best) -> str:
    """A best score, with "a win" or how far short of one it came, as 38 of
    52, or on its own for a game whose wins score differently."""
    full = records.WIN_SCORE.get(key)
    if full is None:
        return str(best.score)
    return f"{best.score}, a win" if best.won else f"{best.score} of {full}"


def names_in(names: list[str], room: int) -> str:
    """names as a sentence lists them, "A, B and C", or as many of them as
    fit in `room` with how many more there are, "A, B and 7 more"."""

    def listed(shown: list[str], more: int) -> str:
        items = [*shown, f"{more} more"] if more else shown
        return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else items[0]

    for n in range(len(names), 0, -1):
        text = listed(names[:n], len(names) - n)
        if len(text) <= room:
            return text
    return listed([], len(names))


class Screens:
    """The screens other than the board, for App to take in."""

    # what they use of App's, set up in App.__init__ and start_game()
    stdscr: Any
    cfg: dict
    has_color: bool
    numpad: dict[int, int]
    waiting: dict[str, dict]
    clock: GameClock
    key: str
    game: Solitaire
    recorded: bool
    page: list[tuple[int, int, str, int]] | None
    page_skinned: bool
    page_dx: int
    page_fits: bool

    if TYPE_CHECKING:

        def CP(self, n: int) -> int: ...

        def read_key(self, wait_ms: int = 1000) -> int: ...

        def keep_setting(self, **changes: object) -> None: ...

        def seconds(self) -> int: ...

        @staticmethod
        def resume_text(save: dict) -> str: ...

    def safe_add(self, y, x, text, attr=0):
        if self.page is not None:
            self.page.append((y, x, text, attr))
            return
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.stdscr.addnstr(y, x, text, max(0, w - x - 1), drawn_attr(attr))
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

    def draw_list(
        self,
        rows: Scroll,
        y: int,
        x: int,
        row: Callable[[int], str],
        marked: bool = True,
        look: Callable[[int], int] | None = None,
    ) -> None:
        """Draw the rows of the list in view from row y down at column x,
        row(i) giving the text of row i, and look(i), if given, how it looks
        when it isn't picked. The row picked is lit up and, unless `marked`
        is False, has a > before it. The lines saying there are more go
        under the text of the rows."""
        CP = self.CP
        for dy, at in enumerate(rows.lines()):
            if isinstance(at, str):
                self.safe_add(y + dy, x + 2, at, CP(CHROME))
                continue
            picked = at == rows.sel
            mark = "> " if picked and marked else "  "
            attr = (CP(CURSOR) | curses.A_BOLD) if picked else look(at) if look else 0
            self.safe_add(y + dy, x, mark + row(at), attr)

    def boss_key(self, k: int) -> bool:
        """If k is the boss key, go into boss mode until a key is pressed.

        Every screen passes its keys through here first, so the boss key
        works everywhere, not only on the board."""
        if PLAY_ACTIONS.get(k) != "boss":
            return False
        self.camouflage_screen()
        return True

    # ---- menu ---- #
    def last_game(self) -> str:
        """The game played last, or Klondike before there is one."""
        last = self.cfg.get("last_game")
        return last if last in GAME_ORDER else "klondike"

    def chooser(self) -> str | Deal | None:
        """The menu. Returns the key of the game picked, the Deal asked for
        under Daily deal or Play a deal, one of the other rows, or None for q."""
        CP, safe_add = self.CP, self.safe_add
        extra = ["__daily__", "__deal__", "__stats__", "__quit__"]
        labels = {
            "__daily__": "Daily deal",
            "__deal__": "Play a deal",
            "__stats__": "View statistics",
            "__quit__": "Quit",
        }
        items = GAME_ORDER + extra
        # the games scroll, and the rows under them stay where they are
        rows = Scroll(len(GAME_ORDER), GAME_ORDER.index(self.last_game()), len(extra))
        # every game picked here is a plain start, so each save is offered
        self.waiting = saves.waiting()

        def game_row(i: int) -> str:
            key = GAME_ORDER[i]
            cls = GAMES[key]
            about = cls.short_blurb
            if key in self.waiting:
                save = self.waiting[key]
                which = "daily game" if save.get("daily") else "game"
                about = f"Resume your {which}: {self.resume_text(save)}"
            return f"{cls.name:<16} {about}"

        while True:
            self.begin_page()
            safe_add(1, 4, f"{APP_NAME}  -  choose a game", CP(CHROME) | curses.A_BOLD)
            safe_add(2, 4, "solitaire for your terminal, AisleRiot-compatible", CP(CHROME))
            # under the games a gap, the other rows, a gap and the footer
            rows.fit(self.stdscr.getmaxyx()[0] - 4 - (len(extra) + 3))
            self.draw_list(rows, 4, 6, game_row)
            base = 4 + rows.room + 1
            for j, key in enumerate(extra):
                i = len(GAME_ORDER) + j
                label = labels[key]
                marker = "> " if i == rows.sel else "  "
                attr = (CP(CURSOR) | curses.A_BOLD) if i == rows.sel else 0
                safe_add(base + j, 6, f"{marker}{label}", attr)
            safe_add(
                base + len(extra) + 1,
                6,
                "Up/Down move - Enter select - mouse click - q quit",
                CP(CHROME),
            )
            self.end_page()
            k = self.page_key()
            if self.boss_key(k) or rows.key(k):
                continue
            picked = None
            if k in (curses.KEY_ENTER, 10, 13):
                picked = items[rows.sel]
            elif k == curses.KEY_MOUSE:
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                at = rows.mouse(bstate, my - 4)
                if at is not None:
                    picked = items[at]
                elif bstate & LEFT_CLICK and 0 <= my - base < len(extra):
                    # only a left click: a release, say of the click on the
                    # banner's Back to menu, sits on the row of Quit here
                    rows.sel = len(GAME_ORDER) + my - base
                    picked = items[rows.sel]
            elif k in (ord("q"), ord("Q")):
                return None
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
        """The list of today's daily deals, one a game, with how each went
        today and the streak of days with one won. Returns the Deal picked,
        or None if the player went back. A daily won or lost is dealt again
        all the same."""
        CP, safe_add = self.CP, self.safe_add
        # read once, so a list left open over midnight deals the day it shows
        day = deals.today()
        number = deals.daily_number(day)
        # and the history once each time it opens, not on each key or resize
        entries = history.games()
        results = records.dailies(entries, day)
        won_today = any(r.result == "won" for r in results.values())
        streak = daily_streak_text(records.daily_streak(entries, day), won_today)
        # the codes line up, and what came of each after them
        width = max(len(f"{key}:{number}") for key in GAME_ORDER)
        rows = Scroll(len(GAME_ORDER), GAME_ORDER.index(self.last_game()))

        def how_it_went(key: str) -> str:
            done, save = results[key], self.waiting.get(key)
            if done.best is not None:
                return f"won in {store.time_and_moves(done.best.seconds, done.best.moves)}"
            # which Enter resumes, as the menu does
            if save is not None and save.get("daily") == day.isoformat():
                return f"saved at {self.resume_text(save)}"
            return "played, not won yet" if done.result == "lost" else ""

        def game_row(i: int) -> str:
            key = GAME_ORDER[i]
            code = f"{key}:{number}"
            return f"{GAMES[key].name:<16} {code:<{width}}  {how_it_went(key)}".rstrip()

        while True:
            self.begin_page()
            safe_add(1, 4, f"Daily deals for {day.isoformat()}", CP(CHROME) | curses.A_BOLD)
            safe_add(2, 4, streak)
            rows.fit(self.stdscr.getmaxyx()[0] - 4 - 2)  # a gap and the footer under it
            self.draw_list(rows, 4, 6, game_row)
            safe_add(4 + rows.room + 1, 6, "Up/Down move - Enter play - Esc back", CP(CHROME))
            self.end_page()
            k = self.page_key()
            if self.boss_key(k) or rows.key(k):
                continue
            picked = None
            if k in (curses.KEY_ENTER, 10, 13):
                picked = rows.sel
            elif k == curses.KEY_MOUSE:
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                picked = rows.mouse(bstate, my - 4)
            elif k in (27, ord("q"), ord("Q")):
                return None
            if picked is not None:
                return deals.daily(GAME_ORDER[picked], day)

    # ---- statistics dialog (AisleRiot fields) ---- #
    @hides_the_board
    def stats_screen(self, focus_key: str | None = None):
        """The statistics of every game, the row of focus_key picked out,
        or of the first game if there's none. The keys that move the pick
        on the menu and the wheel move it here, Enter opens the records of
        the game picked, as a click on its row does once it's picked, and
        any other key leaves."""
        # the history, read once for the streaks and every game's records,
        # not again on each key or resize
        entries = history.games()
        found = records.records(entries)
        got = records.achievements(entries)
        days = records.daily_streak(entries)
        # only the games played here are in the history
        streaks = {key: r.streak for key, r in found.items() if r.played}
        start = GAME_ORDER.index(focus_key) if focus_key in GAME_ORDER else 0
        rows = Scroll(len(GAME_ORDER), start)
        while True:
            self.draw_stats(rows, streaks)
            k = self.page_key()
            if self.boss_key(k) or rows.key(k):
                continue
            opened = None
            if k in (curses.KEY_ENTER, 10, 13):
                opened = rows.sel
            elif k == curses.KEY_MOUSE:
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                before = rows.sel
                at = rows.mouse(bstate, my - 5)
                # a click picks a row, and one on the row picked opens it,
                # so a double-click, two presses, does too
                if at is not None and at == before:
                    opened = at
            elif k not in (-1, curses.KEY_RESIZE):
                return
            if opened is not None:
                rows.sel = self.records_screen(opened, found, got, days)

    def draw_stats(self, rows: Scroll, streaks: dict[str, history.Streak]):
        CP, safe_add = self.CP, self.safe_add
        self.begin_page()
        safe_add(1, 4, "Statistics", CP(CHROME) | curses.A_BOLD)
        safe_add(2, 4, "Wins / Total / Percentage / Best & Worst winning time", CP(CHROME))
        if store.syncing():
            if store.sharing_waits():
                shared = "(will be shared with GNOME AisleRiot once sol has run)"
            else:
                shared = "(shared with GNOME AisleRiot - sol)"
            safe_add(3, 4, shared, CP(MESSAGE) if self.has_color else 0)
        header = (
            f"  {'Game':<16}{'Wins':>6}{'Total':>7}{'Win%':>7}{'Best':>8}{'Worst':>8}"
            f"{'Streak':>8}{'Longest':>8}"
        )
        safe_add(4, 4, header, CP(MESSAGE) | curses.A_BOLD)

        def game_row(i: int) -> str:
            key = GAME_ORDER[i]
            s = store.get_stat(key)
            pcts = store.percent_text(s)
            best = "N/A" if s["best"] == 0 else store.fmt_time(s["best"])
            worst = "N/A" if s["worst"] == 0 else store.fmt_time(s["worst"])
            # only the games played here are in the history
            cur, longest = streaks.get(key, ("N/A", "N/A"))
            return (
                f"{GAMES[key].name:<16}{s['wins']:>6}{s['total']:>7}{pcts:>7}{best:>8}{worst:>8}"
                f"{cur:>8}{longest:>8}"
            )

        rows.fit(self.stdscr.getmaxyx()[0] - 5 - 2)  # a gap and the footer under it
        # lit up, and without colour marked as well, as on the menu
        self.draw_list(rows, 5, 4, game_row, marked=not self.has_color)
        footer = "Up/Down move - Enter records - Press any other key to continue."
        safe_add(5 + rows.room + 1, 4, footer, CP(CHROME))
        self.end_page()

    # ---- a game's records ---- #
    @hides_the_board
    def records_screen(
        self,
        at: int,
        found: dict[str, records.Records],
        got: records.Achievements,
        days: history.Streak,
    ) -> int:
        """The records and achievements of game `at` of GAME_ORDER, from
        the history the statistics read. Left and Right, and h and l, go to
        the game before and after it, and any other key goes back, as the
        mouse doesn't. Where the page is too long for the terminal, the keys
        that scroll the help scroll it. Returns the game last shown, for the
        statistics to pick."""
        lines = self.records_lines(GAME_ORDER[at], found, got, days)
        rows = Reader(len(lines))
        while True:
            self.draw_records(GAME_ORDER[at], lines, rows)
            k = self.page_key()
            if self.boss_key(k) or (rows.scrolls() and rows.key(k)):
                continue
            if k in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("h"), ord("l")):
                step = -1 if k in (curses.KEY_LEFT, ord("h")) else 1
                at = (at + step) % len(GAME_ORDER)
                lines = self.records_lines(GAME_ORDER[at], found, got, days)
                rows = Reader(len(lines))
            elif k == curses.KEY_MOUSE:
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                rows.mouse(bstate, my - 2)
            elif k not in (-1, curses.KEY_RESIZE):
                return at

    def draw_records(self, key: str, lines: list[tuple[str, int]], rows: Reader) -> None:
        """Draw the records of `key`, `lines` being what records_lines gives."""
        CP, safe_add = self.CP, self.safe_add
        self.begin_page()
        safe_add(1, 4, f"{GAMES[key].name} - records", CP(CHROME) | curses.A_BOLD)
        # the lines right under the title, then a gap and the footer
        rows.fit(self.stdscr.getmaxyx()[0] - 2 - 2)
        self.draw_list(rows, 2, 4, lambda i: lines[i][0], False, lambda i: lines[i][1])
        footer = "Left/Right other games - any other key goes back"
        if rows.scrolls():
            footer = "Up/Down scroll - " + footer
        safe_add(2 + rows.room + 1, 4, footer, CP(CHROME))
        self.end_page()

    def records_lines(
        self,
        key: str,
        found: dict[str, records.Records],
        got: records.Achievements,
        days: history.Streak,
    ) -> list[tuple[str, int]]:
        """The lines of the records page of `key`, each with how it looks.
        Each fits in RECORDS_W, at the widest a record can be: a time of
        99999:59, 99999 moves and the longest share code there is."""
        note, head = self.CP(CHROME), self.CP(MESSAGE) | curses.A_BOLD
        r, name = found[key], GAMES[key].name
        # the history began with Soliterm 1.0, and has none of AisleRiot's games
        lines = [
            ("Only the games played here in Soliterm count, so these can be fewer", note),
            ("than the Wins and Total, which count AisleRiot's games when shared.", note),
            ("", 0),
        ]
        if not r.played:
            lines += [(f"No games of {name} played here yet.", 0), ("", 0)]
        else:
            since = (r.since or "")[:10]
            lines += [
                (f"{'Played':<14}{r.played} since {since}, and won {r.won}", 0),
                (f"{'Win streak':<14}{r.streak.current} now, longest {r.streak.longest}", 0),
                ("", 0),
            ]
            if r.fastest is None or r.fewest is None:
                lines += [
                    (f"{'Fastest win':<14}no win yet", 0),
                    (f"{'Fewest moves':<14}no win yet", 0),
                ]
            else:
                lines.append((f"{'':<14}{'Time':>8}  {'Moves':>5}  {'Deal':<25}  Date", head))
                plain = option_words(key, {})
                for label, b in (("Fastest win", r.fastest), ("Fewest moves", r.fewest)):
                    time_ = store.fmt_time(b.seconds)
                    deal = deal_text(key, b)
                    lines.append(
                        (f"{label:<14}{time_:>8}  {b.moves:>5}  {deal:<25}  {b.at[:10]}", 0)
                    )
                    words = option_words(key, b.options)
                    if words != plain:
                        lines.append((f"{'':<31}{words}", 0))
            if r.best_scores:
                lines.append(("", 0))
            for n, b in enumerate(r.best_scores):
                # one for each set of options, or the deal of a game with none
                label = "Best score" if n == 0 else ""
                what = option_words(key, b.options) or deal_text(key, b)
                lines.append((f"{label:<14}{score_text(key, b):<17}{what:<25}  {b.at[:10]}", 0))
            lines.append(("", 0))
        clean, every, week = got.clean[key], got.every_game, got.seven_dailies

        def achieved(label: str, a: records.Achievement, so_far: str, what: str) -> tuple[str, int]:
            return (f"{label:<14}{a.at[:10] if a.at else so_far:<12}{what}", 0)

        if every.earned or not every.done:
            to_win = "a win in every game"
        else:
            left = [GAMES[k].name for k in every.left]
            to_win = "to win: " + names_in(left, RECORDS_W - 26 - len("to win: "))
        if week.earned:
            in_a_row = "a daily won seven days in a row"
        else:
            in_a_row = "the longest run of days with a daily won"
        lines += [
            ("Achievements", head),
            # not yet, as a win from before 1.1 counted no hints or undos
            achieved("Clean win", clean, "not yet", "a win with no hint and no undo"),
            achieved("Every game", every, f"{every.done} of {every.goal}", to_win),
            achieved("Seven dailies", week, f"{days.longest} of {week.goal}", in_a_row),
        ]
        return lines

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
        """The keys, as KEYMAP has them. Any key closes it, but where it's
        too long for the terminal, the keys that move the pick on the menu
        scroll it instead, as the wheel does. The mouse doesn't close it and
        a resize draws it again, so the pointer passing over it or a
        retiled window can't. The boss key hides it and comes back to it."""
        lines = help_lines()
        rows = Reader(len(lines))
        while True:
            self.draw_help(lines, rows)
            k = self.page_key()
            if self.boss_key(k) or (rows.scrolls() and rows.key(k)):
                continue
            if k == curses.KEY_MOUSE:
                try:
                    _, _mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                rows.mouse(bstate, my - 2)
            elif k not in (-1, curses.KEY_RESIZE):
                return

    def draw_help(self, lines: list[str], rows: Reader) -> None:
        """Draw the help, `lines` being what help_lines() gives."""
        self.begin_page()
        self.safe_add(1, 2, f"{APP_NAME} - controls", curses.A_BOLD)
        # the lines right under the title, then a gap and the footer; each
        # line's own indent is the one draw_list gives it
        rows.fit(self.stdscr.getmaxyx()[0] - 2 - 2)
        self.draw_list(rows, 2, 2, lambda i: lines[i][2:], marked=False)
        footer = "Press any key to continue."
        if rows.scrolls():
            footer = "Up/Down scroll - " + footer
        self.safe_add(2 + rows.room + 1, 4, footer)
        self.end_page()

    def copy_out(self, text: str, what: str) -> str:
        """Copy `text` for y, and say what came of it, naming the text as
        `what`. What's drawn goes out first, so that on a terminal the
        escape sequence that asks it to copy comes after it, not inside."""
        self.stdscr.refresh()
        return clipboard.copy(text, what)

    # ---- pause ---- #
    @hides_the_board
    def pause_screen(self):
        """Hide the board, with the clock standing still, until a key or a
        click. The pointer passing over, the wheel and a resize don't count,
        as on the help, and the boss key hides it and comes back to it."""
        CP, safe_add = self.CP, self.safe_add
        while True:
            self.begin_page()
            safe_add(2, 6, "Game paused", CP(MESSAGE) | curses.A_BOLD)
            safe_add(4, 6, f"Time played so far: {store.fmt_time(self.seconds())}")
            if self.clock.started:
                safe_add(5, 6, "The clock stands still until you go back.")
            else:
                safe_add(5, 6, "The clock starts at the first move.")
            safe_add(7, 6, "Press any key or click to go back to the game.", CP(CHROME))
            self.end_page()
            k = self.page_key()
            if self.boss_key(k):
                continue
            if k == curses.KEY_MOUSE:
                try:
                    bstate = curses.getmouse()[4]
                except curses.error:
                    continue
                if bstate & LEFT_CLICK:
                    return
            elif k not in (-1, curses.KEY_RESIZE):
                return

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
                    k = self.numpad.get(k, k)
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
                            self.keep_setting(camo_theme=theme)
                            gen = camo.stream(theme)
                            buf = []
                            break
                        return  # any other key exits camo mode
                    time.sleep(0.04)
                    slept += 0.04
        finally:
            stdscr.nodelay(False)

    def banner_lines(
        self, seconds: int, won: bool, stat: dict, note: str = "", on_deal: str = ""
    ) -> list[str]:
        """The rows of the end banner from row 4 down, "" for a blank one.
        The choices go under the last of them. A note from win_note goes
        after the best time, and on_deal, how the game stood on its deal,
        under it. The best time, the deal and the streak each have a row
        only when there's something to say, and the rows they leave are
        there empty at the end, so the choices don't move up."""
        game = self.game
        pcts = store.percent_text(stat)
        streak = history.streak_text(self.key) if won else ""
        deal = f"daily {game.daily}" if game.daily else game.deal_number
        rows = [
            f"Best time   : {store.fmt_time(stat['best'])}{note}" if stat["best"] else "",
            f"On this deal: {on_deal}" if on_deal else "",
            f"Streak      : {streak}" if streak else "",
        ]
        said = [row for row in rows if row]
        return [
            f"Game        : {game.gamedef.name}",
            f"Deal        : {deal}   share code {deals.code_of(game)}",
            f"Time        : {store.fmt_time(seconds)}",
            f"Score       : {game.score}",
            f"Moves       : {game.moves}",
            "",
            f"Wins/Total  : {stat['wins']}/{stat['total']}  ({pcts})",
            *said,
            *[""] * (len(rows) - len(said)),
        ]

    @hides_the_board
    def end_banner(self, seconds: int, won: bool, note: str = "", on_deal: str = "") -> str:
        """Show the end-of-game banner with choices. Returns one of:
        'undo' (take the last move back, when no moves are left), 'same'
        (replay this deal), 'new' (fresh deal), 'menu'. The note goes after
        the best time, and on_deal under it."""
        CP, safe_add = self.CP, self.safe_add
        game = self.game
        s = store.get_stat(self.key)
        if not self.recorded:
            # a loss is recorded on leaving the banner for a new deal or the
            # menu, so count it already, as the statistics will then
            s = {**s, "total": s["total"] + 1}
        lines = self.banner_lines(seconds, won, s, note, on_deal)
        top = 4 + len(lines) + 1  # the row of the first choice
        share = ""  # the line a daily leaves to paste to friends
        if game.daily:
            share = deals.share_line(game.gamedef.name, game.daily, won, seconds, game.moves)
        said = ""  # what came of y
        # each with the key that takes it
        choices = [
            ("same", "Replay this deal (s)"),
            ("new", "New deal (n)"),
            ("menu", "Back to menu (m)"),
        ]
        can_undo = not won and game.can_undo()
        if can_undo:
            choices.insert(0, ("undo", "Undo move (u)"))
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
            h, w = self.stdscr.getmaxyx()
            # only on a row the terminal has, as the banner fits without it,
            # and y copies the share code where it has none
            shown = share if footer + 2 < h else ""
            what = "the share line" if shown else "the share code"
            below = footer + (3 if shown else 2)  # the row for what y did
            if said and below >= h:
                # in the footer's place, as there's no row for it under
                safe_add(footer, 6, said, CP(MESSAGE))
            else:
                tip = f"Up/Down + Enter, or click to choose; y copies {what}."
                safe_add(footer, 6, tip, CP(CHROME))
                if said:
                    safe_add(below, 6, said, CP(MESSAGE))
            if shown:
                # plain, to copy, and nearer the edge if the margin would clip it
                x = 6 if self.page_dx + 6 + len(shown) <= w - 1 else 2
                safe_add(footer + 2, x, shown)
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
            elif k in (ord("y"), ord("Y")):
                said = self.copy_out(shown or deals.code_of(game), what)
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
