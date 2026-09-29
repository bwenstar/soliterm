"""soliterm.tui.app - the curses session and the play loop.

App holds what the screens share: the config and the colour flags, and for
the game in play the board, the cursor, the selection, the hint, the clock
and the message line. Every screen is a method: the play screen here, and
the menu, the dialogs and the end banner in Screens (screens.py), which App
takes in. The play screen handles each key or click in a small method of
its own, so a test can drive a game on a fake window without a terminal.

Statistics use AisleRiot's Wins/Total/Percentage/Best/Worst model.
"""

from __future__ import annotations

import curses
import os
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Callable

from .. import deals, history, saves, store, themes
from ..deals import Deal
from ..engine import GAMES, Solitaire
from .board import BoardUI, can_draw_unicode, color_attr
from .cascade import FRAME_MS, MAX_S, Cascade
from .keys import PLAY_ACTIONS, numpad_keys
from .screens import LEFT_CLICK, WHEEL_DOWN, WHEEL_UP, Screens

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

# What still works while "Terminal too small" hides the board: nothing that
# could make a move the player can't see. The mouse finds no cards to hit.
# The code skin and the view change the size the board needs, so the toggle
# that hid it can bring it back.
SMALL_SCREEN_ACTIONS = ("quit", "redraw", "boss", "mouse", "code_skin", "view")

# The mouse events the game asks for: the left button, and the wheel, which
# scrolls the lists of games. Asking for REPORT_MOUSE_POSITION as well would
# have the terminal report every move of the pointer, button or not.
LEFT_BUTTON = (
    curses.BUTTON1_PRESSED
    | curses.BUTTON1_RELEASED
    | curses.BUTTON1_CLICKED
    | curses.BUTTON1_DOUBLE_CLICKED
)
MOUSE_MASK = LEFT_BUTTON | WHEEL_UP | WHEEL_DOWN
# PDCurses, which windows-curses is, only says which way the wheel went
# when the mask has its MOUSE_WHEEL_SCROLL too, a bit the curses module
# doesn't name. ncurses has BUTTON_CTRL there, so only Windows asks for it.
PDC_WHEEL = 0x2000000
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

    def leave_out(self, stopped: float) -> None:
        """Leave out of a running clock the time from `stopped` to now, as
        when Ctrl-Z stopped the game all that time. A clock that isn't
        running, or stands still behind another screen, has nothing to
        leave out, and one that set off since loses only what it has run."""
        if self.since is not None:
            now = clock()
            self.since += now - max(stopped, self.since)

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


def basic_colours() -> tuple[int, ...]:
    """curses' numbers for the basic 8, in the order of themes.BASIC.

    ncurses has them in that order too, but PDCurses, the curses on
    Windows, goes by their blue, green and red bits, so its red is 4.
    """
    return (
        curses.COLOR_BLACK,
        curses.COLOR_RED,
        curses.COLOR_GREEN,
        curses.COLOR_YELLOW,
        curses.COLOR_BLUE,
        curses.COLOR_MAGENTA,
        curses.COLOR_CYAN,
        curses.COLOR_WHITE,
    )


def colour_count() -> int:
    """The number of colours to pick the theme's colours by.

    PDCurses, the curses on Windows, says 768 whatever the console. It
    writes xterm's colour codes only in Windows Terminal and in ConEmu with
    its ANSI on, which it tells by WT_SESSION and ConEmuANSI as it starts.
    There colours 16 to 255 are xterm's, the ones the tuned colours are
    for, so it counts as 256. The classic console gets the nearest of its
    own 16 for each, which would draw the four-colour deck's orange
    diamonds in the hearts' red, so there it counts as 16. Every other
    curses says what it has.
    """
    colours = getattr(curses, "COLORS", 8)
    if sys.platform == "win32" and colours > 256:
        # Windows has the names in capitals whatever case they were set in
        xterm = os.environ.get("WT_SESSION") is not None or os.environ.get("CONEMUANSI") == "ON"
        return 256 if xterm else 16
    return colours


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


@contextmanager
def on_continue(then: Callable[[], object]) -> Iterator[None]:
    """Call `then` each time the process goes on after being stopped, as
    by Ctrl-Z and fg, while the with block runs. Where there is no
    SIGCONT (Windows) it does nothing.

    Ctrl-Z itself is left to ncurses, whose handler puts the terminal back,
    stops the process and draws the screen again once it goes on. One of
    Python's own would take its place, with no way to hand on to it.
    """
    cont = getattr(signal, "SIGCONT", None)
    if cont is None:
        yield
        return
    old = signal.signal(cont, lambda signum, frame: then())
    try:
        yield
    finally:
        signal.signal(cont, signal.SIG_DFL if old is None else old)


class App(Screens):
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
        note: str = "",
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
        # the numpad keys to read as the main ones (windows-curses only)
        self.numpad = numpad_keys(curses)
        # the saved games the menu offers, as saves.waiting() gives them
        self.waiting: dict[str, dict] = {}
        # clock() when read_key last had a key or ran out of time waiting,
        # the last sign of life before a stop (see carry_on)
        self.alive = clock()
        # per-game state, reset by start_game()
        self.clock = GameClock()
        self.selected: int | None = None
        self.selected_n = 1
        self.selected_exact = False  # True when the player split by clicking a card
        self.pressed: int | None = None  # the slot the left button went down on
        self.last_click: tuple[int, float] | None = None  # (slot, clock())
        # (y, x, clock()) of the last click that played a card
        self.played: tuple[int, int, float] | None = None
        self.cursor = 0
        self.hint: tuple[int, int, str] | None = None
        self.hint_n = 1  # how many cards the hint would move
        # the move the last hint named and the board it was named on, kept
        # for drop_on past the keys that clear the hint (see hinted_drop)
        self.hinted: tuple[tuple[int, int, int], str] | None = None
        self.message = ""
        # a line from the command line for the first game to start with,
        # as on the terminal type it plays as
        self.note = note
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
            curses.mousemask(MOUSE_MASK | (PDC_WHEEL if sys.platform == "win32" else 0))
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
            colour_count(),
            self.light,
            self.default_colours,
            self.four_color,
            basic_colours(),
        ):
            if n < room:
                curses.init_pair(n, fg, bg)

    def CP(self, n):
        return color_attr(n) if self.has_color else 0

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

    def carry_on(self) -> None:
        """Take the time the game was stopped, by Ctrl-Z say, off its clock,
        as AisleRiot's clock doesn't run then either.

        Only the going on is seen (SIGCONT), so the stop is taken to run
        from the last time read_key woke. That is never much more than a
        second before it, as read_key wakes each second, so up to a second
        of play can go with it.
        """
        self.clock.leave_out(self.alive)

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

    # ---- play one game ---- #
    def play(self, key: str, deal: Deal | None = None) -> bool:
        """Play a game of `key` until the player leaves it: `deal` if given,
        or a random deal with the saved options.

        Returns True if they quit the program, False to go back to the menu.
        """
        try:
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
            except Exception:
                # a bug, say: the game is kept or counted as it is for q, and
                # the error goes on, not one that doing so ran into. Inside
                # the handler below, so a signal meanwhile puts it away again.
                if hasattr(self, "game"):
                    with suppress(Exception):
                        self.leave()
                raise
        except KeyboardInterrupt:
            # Ctrl-C, wherever in the game it comes, leaves the way q does
            if not hasattr(self, "game"):  # there is none before the first deal
                raise
            try:
                self.leave()
            finally:
                # another Ctrl-C, say as it waited for another copy's lock
                if not self.recorded and (self.game.is_won() or self.under_way()):
                    store.cut_short(self.game.gamedef.name)
            raise

    def leave(self) -> None:
        """Put the game away as the program goes, but on the end banner
        there is nothing left to come back to, so it's counted."""
        if self.ending:
            self.give_up()
        else:
            self.put_away()

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

        A numpad key that windows-curses gives a code of its own comes back
        as the main key it stands for, so numpad Enter is Enter.
        """
        if self.pending_key is not None:
            k, self.pending_key = self.pending_key, None
            return k
        self.stdscr.timeout(wait_ms)
        try:
            k = self.stdscr.getch()
        finally:
            self.stdscr.timeout(-1)  # the other screens wait for a key
        self.alive = clock()
        k = self.numpad.get(k, k)
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
        # From the take on, the save is in play until put_away keeps the
        # game again, so a signal waits until there's one set up to keep
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
        # before the first game gets going, over anything else it would say
        note, self.note = self.note, ""
        self.message = store.aisleriot_open_note() or note or self.message

    def put_in_play(self, deal: Deal, resumed: tuple[Solitaire, int] | None) -> None:
        """Put the resumed game in play, or else a new deal of `deal`, with
        the play screen set up for it."""
        if resumed is None:
            self.game = self.new_game(deal)
        else:
            self.game = resumed[0]
            self.game.symbols = self.symbols
        self.keep_setting(last_game=self.key)
        self.ui = self.new_board()
        self.clock.reset()
        if resumed is not None:
            self.clock.resume(resumed[1])
        self.selected = None
        self.selected_n = 1
        self.selected_exact = False
        self.pressed = None
        self.last_click = None
        self.played = None
        self.cursor = self.first_cursor()
        self.hint = None
        self.hinted = None
        self.message = START_MESSAGE
        self.recorded = False
        self.dead_end_undone = False
        self.skip_cascade = False

    def unkept_note(self) -> str:
        """What a new deal says while a game of its kind is saved, or taken
        up in another window, as then leaving this one can't keep it too;
        "" when there's room for it.

        The slot is looked at again, for a game another window has saved
        since the menu, and the menu's list of saves is brought up to date.
        """
        name = GAMES[self.key].name
        saved = saves.waiting(self.key).get(self.key)
        if saved is not None:
            self.waiting[self.key] = saved
            return f"a saved {name} game is waiting, so this one won't be kept"
        self.waiting.pop(self.key, None)
        if saves.elsewhere(self.key):
            return f"a saved {name} game is being played somewhere else, so this one won't be kept"
        return ""

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
        # following the hint makes the move it names, not the longest run
        n = self.hinted_drop(sid)
        ok = n > 0 and game.attempt_move(self.selected, sid, n)
        if not ok:
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
        # why the run held won't go, not a shorter one tried after it
        self.message = (
            "" if ok else f"illegal move: {game.why_not(self.selected, sid, self.selected_n)}"
        )
        self.selected = None
        self.selected_exact = False
        self.hint = None
        self.hinted = None

    def hinted_drop(self, dst: int) -> int:
        """How many cards the last hint moves, if dropping the selection on
        dst follows it, else 0. It does if the hint was for this board and
        named a move from the selected pile to dst, and the player took
        what Enter lifts rather than choosing how many with + or - or a
        click on a card. Enter lifts the longest run, where the hint may
        move fewer cards to the same place.
        """
        if self.hinted is None or self.selected_exact:
            return 0
        (src, to, n), board = self.hinted
        if (src, to) != (self.selected, dst) or board != self.game.serialize():
            return 0
        return n

    def to_foundation(self, sid: int):
        if self.game.double_click(sid):
            self.message = ""
        else:
            top = self.game.top(sid)
            # the card as the board names it, unless that would give it away
            card = top.label(self.symbols) if top and top.face_up else "that face-down card"
            reason = self.game.no_foundation_reason(sid, card)
            self.message = reason or "no foundation move for that card"
        self.selected = None
        self.hint = None

    def click_stock(self, sid: int):
        # a deal clears what was said about the move before, as a move does
        ok = self.game.click(sid)
        self.message = "" if ok else self.game.deal_blocked_reason()

    def play_here(self, sid: int) -> bool:
        """Play the top card of sid, as a click does in AisleRiot, where the
        game has such a play: Golf and Triple Peaks put a card that goes on
        the waste there. True if it did."""
        if not self.game.click(sid):
            return False
        self.message = ""
        return True

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
            saves.let_go(self.key)  # a game taken up from a save, done with
            stat = history.record(self.game, won, seconds)
            self.recorded = True
        return stat

    def reset_for(self, new_game_fn: Callable[[], object]):
        """Run a (re)deal and reset the per-game UI state."""
        # a game taken up from a save and not counted, as dealing it again
        # from the start doesn't count it, goes with it
        saves.let_go(self.key)
        new_game_fn()
        self.clock.reset()
        self.recorded = False
        self.dead_end_undone = False
        self.skip_cascade = False
        self.selected = None
        self.selected_exact = False
        self.pressed = None
        self.last_click = None
        self.played = None
        self.hint = None
        self.hinted = None
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

    def keep_setting(self, **changes: object) -> None:
        """Make `changes` the new defaults, for this run and in config.json,
        where the rest of the file stays as it is on disk (a hand edit made
        since the game started, say) rather than as it was at the start."""
        self.cfg.update(changes)
        store.update_config(**changes)

    def do_code_skin(self):
        # code skin: keep playing with the board wrapped in source
        ui = self.ui
        ui.code_skin = not ui.code_skin
        self.keep_setting(code_skin=ui.code_skin)
        self.message = "code skin on" if ui.code_skin else "code skin off"

    def do_color(self):
        # toggle colour on/off live (persisted as the new default)
        if not self.color_capable:
            self.message = "this terminal has no colour support"
        else:
            self.has_color = not self.has_color
            self.ui.has_color = self.has_color
            self.keep_setting(color=self.has_color)
            self.message = "colour on" if self.has_color else "colour off (monochrome)"

    def do_theme(self):
        # the next theme, on screen at once (cells change with their pairs)
        # and kept as the new default
        if not self.color_capable:
            self.message = "this terminal has no colour support"
            return
        self.theme = themes.next_theme(self.theme)
        self.init_pairs()
        self.keep_setting(theme=self.theme.name)
        self.message = f"{self.theme.name} theme{self.colour_note()}"

    def do_four_color(self):
        # green clubs and orange diamonds on and off, kept as the new default
        if not self.color_capable:
            self.message = "this terminal has no colour support"
            return
        self.four_color = not self.four_color
        self.init_pairs()
        self.keep_setting(four_color=self.four_color)
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
        self.keep_setting(view=new_view)
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
        self.hinted = None
        if self.hint is None:
            # the game says why, and whether an undo could still help
            self.message = self.game.no_hint_reason()
        else:
            hsrc, hdst, desc = self.hint
            self.hint_n = self.hinted_run(hsrc, hdst)
            self.hinted = ((hsrc, hdst, self.hint_n), self.game.serialize())
            # move the cursor to the suggested source for convenience
            self.cursor = hsrc
            self.message = f"Hint: {desc}"

    def hinted_run(self, src: int, dst: int) -> int:
        """How many cards the hint from src to dst would move: as many as
        hint_move() says when the hint is that move, else the most dst takes."""
        mv = self.game.hint_move()
        if mv is not None and mv[:2] == (src, dst):
            return mv[2]
        takes = [n for (s, d, n) in self.game.legal_moves() if (s, d) == (src, dst)]
        return max(takes, default=1)

    def do_select(self):
        self.hint = None
        if self.selected is None:
            if self.game.kind(self.cursor) == "stock":
                self.click_stock(self.cursor)
            elif not self.play_here(self.cursor):
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
        store.update_config(options={self.key: dict(newopts)})
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
        if not bstate & LEFT_BUTTON:
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
        now = clock()
        played, self.played = self.played, None
        if played and played[:2] == (y, x) and now - played[2] <= DOUBLE_CLICK_S:
            # the second click of a double-click on a card the first one
            # played, which has nothing left to do
            return
        if target is None:
            return
        tsid, tidx = target
        self.cursor = tsid
        self.hint = None
        dbl = bstate & curses.BUTTON1_DOUBLE_CLICKED
        clicked = bstate & LEFT_CLICK
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
                elif self.play_here(tsid):
                    self.played = (y, x, now)
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


def run(stdscr, start: str | Deal | None = None, **options):
    """Run a session on stdscr. The settings go on to App by name, so a new
    one only has to be added there."""
    app = App(stdscr, start, **options)
    # a wait for another copy of the game is told of on the screen
    with store.lock_wait_note(app.say_waiting), on_continue(app.carry_on):
        return app.run()


def main(start: str | Deal | None = None, **options) -> int:
    # After an Esc, ncurses waits ESCDELAY ms (a whole second by default) to
    # see whether a key sequence follows, so the Esc key felt dead. It reads
    # the variable when curses starts; a value the player set is kept.
    os.environ.setdefault("ESCDELAY", "25")
    try:
        return curses.wrapper(run, start, **options)
    except curses.error as exc:
        print(f"curses error: {exc}", file=sys.stderr)
        return 1
    finally:
        # once the screen is back, where a game left for next time went
        kept = [GAMES[key].name for key in saves.kept()]
        if kept:
            try:
                print(f"soliterm: {_saved_line(kept)}", file=sys.stderr)
            except OSError:
                # whatever read stderr has gone (EPIPE, or EINVAL on
                # Windows). The line stays in stderr's buffer, where
                # Python's flush at exit would fail on it again, so stderr
                # goes to devnull instead.
                with suppress(OSError):
                    os.dup2(os.open(os.devnull, os.O_WRONLY), 2)


def _saved_line(names: list[str]) -> str:
    """What leaving says of the games it saved, named in `names`."""
    if len(names) == 1:
        return f"saved your {names[0]} game; run soliterm to pick it up"
    games = ", ".join(names[:-1]) + " and " + names[-1]
    return f"saved your {games} games; run soliterm to pick them up"
