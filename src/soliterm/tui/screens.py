"""soliterm.tui.screens - the screens other than the board.

The menu, the daily deals, the statistics, the options, the pick-deal
box, the yes-or-no question, the help, boss mode and the end banner, and
what they share to put a page up and read its keys. They are methods of
Screens, which App takes in, so that each reaches the config, the colours
and the game in play just as the play screen does.
"""

from __future__ import annotations

import curses
import functools
import textwrap
import time
from typing import TYPE_CHECKING, Any, Callable

from .. import APP_NAME, camo, deals, history, saves, store
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


def skip_mouse_event() -> None:
    """Take a mouse event the screen has no use for off ncurses' queue,
    where the next getmouse, on another screen, would find it."""
    try:
        curses.getmouse()
    except curses.error:
        pass


def hides_the_board(screen):
    """Stop the game clock while the screen a method shows is up."""

    @functools.wraps(screen)
    def show(self, *args, **kwargs):
        with self.clock.paused():
            return screen(self, *args, **kwargs)

    return show


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
            if store.sharing_waits():
                shared = "(will be shared with GNOME AisleRiot once sol has run)"
            else:
                shared = "(shared with GNOME AisleRiot - sol)"
            safe_add(3, 4, shared, CP(MESSAGE) if self.has_color else 0)
        y = 4
        header = (
            f"  {'Game':<16}{'Wins':>6}{'Total':>7}{'Win%':>7}{'Best':>8}{'Worst':>8}"
            f"{'Streak':>8}{'Longest':>8}"
        )
        safe_add(y, 4, header, CP(MESSAGE) | curses.A_BOLD)
        y += 1
        for key in GAME_ORDER:
            s = store.get_stat(key)
            pcts = store.percent_text(s)
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

    def banner_lines(self, seconds: int, won: bool, stat: dict, note: str = "") -> list[str]:
        """The rows of the end banner from row 4 down, "" for a blank one.
        The choices go under the last of them. The rows of the best time and
        the streak are there even when empty, so the choices don't move up.
        A note from win_note goes after the best time."""
        game = self.game
        pcts = store.percent_text(stat)
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
            safe_add(footer, 6, "Up/Down + Enter, or click to choose.", CP(CHROME))
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
