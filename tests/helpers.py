"""Helpers shared by the test modules (import them with `from helpers import`)."""

import curses
import glob
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from soliterm import engine, saves, store

# Cards in a full deal of each game.
EXPECTED_CARDS = {
    "klondike": 52,
    "spider": 104,
    "spiderette": 52,
    "freecell": 52,
    "eightoff": 52,
    "golf": 52,
    "triplepeaks": 52,
    "yukon": 52,
    "scorpion": 52,
    "bakersdozen": 52,
    "fortythieves": 104,
    "canfield": 52,
}

# The codes windows-curses (PDCurses) gives the numpad keys it has codes of
# its own for: Enter, + - / and *, and the arrows with NumLock off.
PDCURSES_NUMPAD = {
    "PADENTER": 459,
    "PADPLUS": 465,
    "PADMINUS": 464,
    "PADSLASH": 458,
    "PADSTAR": 463,
    "KEY_A2": 450,
    "KEY_C2": 456,
    "KEY_B1": 452,
    "KEY_B3": 454,
}


def child_env():
    """The environment for a child process: this one (with the isolated
    HOME from conftest), pointed at the checkout's src/."""
    src = str(Path(__file__).resolve().parents[1] / "src")
    return dict(
        os.environ, PYTHONPATH=os.pathsep.join(p for p in (src, os.environ.get("PYTHONPATH")) if p)
    )


# Text mode as it runs at a terminal, keeping a game left under way and
# resuming the one saved, on Klondike
TEXT_COPY = """
import sys
from soliterm import engine, textmode
g = engine.new_solitaire("klondike", seed=1)
sys.exit(textmode.run_text(g, False, "klondike", keep=True, resume=True))
"""


class OtherCopy:
    """Another copy of the game playing Klondike in text mode, in a process
    of its own with this one's HOME. Use it in a with block, which kills it
    if it's still there at the end."""

    def __init__(self):
        self.p = subprocess.Popen(
            [sys.executable, "-u", "-c", TEXT_COPY],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=dict(child_env(), SOLITERM_NO_AISLERIOT="1"),
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait(60)
        self.p.stdin.close()
        self.p.stdout.close()

    def says(self, text):
        """Read what it prints up to a line with `text` in it. One that
        never comes, as when it waits for a command instead, fails the test
        in 30 seconds rather than hanging the suite."""
        seen = ""
        timer = threading.Timer(30, self.p.kill)
        timer.start()
        try:
            for line in iter(self.p.stdout.readline, ""):
                seen += line
                if text in line:
                    return
        finally:
            timer.cancel()
        raise AssertionError(f"it didn't say {text!r}:\n{seen}")

    def types(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def quits(self):
        """Type q, and give its exit status once it has gone."""
        self.types("q")
        return self.p.wait(60)

    def kill(self):
        """Stop it there and then, as a crash or a closed window does."""
        self.p.kill()
        self.p.wait(60)


def crashed(key="klondike"):
    """This copy going with the game it took up for `key` still in play, as
    a crash or a closed window leaves it: nothing tidied, and the lock let
    go of, as the system does."""
    store._let_go(saves._playing.pop(key))


def saved(key="klondike"):
    """The save waiting for `key`, as it is in its file."""
    with open(saves.save_path(key), encoding="utf-8") as fh:
        return json.load(fh)


def from_before_the_counts(key="klondike"):
    """Take the hints and undos out of the save waiting for `key`, as a save
    made before they were kept."""
    save = saved(key)
    del save["hints"], save["undos"]
    with open(saves.save_path(key), "w", encoding="utf-8") as fh:
        json.dump(save, fh)


def nothing_in_play():
    """Whether every game taken up from a save is out of play: this copy
    holds no game's lock, and no in-play save is left in the folder."""
    return saves._playing == {} and not glob.glob(os.path.join(saves.saves_dir(), "*.in-play.*"))


def deal(key, seed=1, **options):
    """A seeded game; options go in as keywords, e.g. deal("spider", suits=2)."""
    return engine.new_solitaire(key, seed=seed, options=options or None)


def signal_once_written(monkeypatch, path, signum):
    """Send signum to this process the moment `path` has been written, as a
    kill landing just then would, before whoever wrote it hears back."""
    real = store._write_json

    def write(to, obj):
        done = real(to, obj)
        if to == path:
            os.kill(os.getpid(), signum)
        return done

    monkeypatch.setattr(store, "_write_json", write)


def stats_json_in_use(monkeypatch):
    """Have every save of stats.json fail, as on Windows while another
    program has the file open: the new one can't be put in its place."""
    real = os.replace

    def replace(src, dst):
        if os.fspath(dst) == store.stats_path():
            raise PermissionError(13, "Permission denied")
        real(src, dst)

    monkeypatch.setattr(os, "replace", replace)


def until(done, timeout=30):
    """Wait for done() to come true, and say whether it did in `timeout`
    seconds, which is more than the slowest machine needs: the deadline is
    there so a test gone wrong fails rather than hangs."""
    deadline = time.monotonic() + timeout
    while not done():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.001)
    return True


def signal_as_it_waits(main, signum, other):
    """A thread, still to be started, that sends signum to the thread
    `main` once it waits for the stats lock another copy of the game holds
    (on the open lock file `other`), and has that copy let go once the
    signal has broken the wait off.

    It watches store.waiting_for_lock() rather than sleeping for a set
    time, so however slow the machine, the signal goes once the wait has
    begun, and the lock stays taken until the wait is over: only the
    signal can end it. Its `seen` says whether the wait came, and then its
    end, before the lock was let go. A wait that never comes gets no
    signal, which would land wherever the test had got to by then.
    """

    def run():
        thread.seen.append(until(store.waiting_for_lock))
        if thread.seen[0]:
            signal.pthread_kill(main, signum)
            thread.seen.append(until(lambda: not store.waiting_for_lock()))
        store.fcntl.flock(other.fileno(), store.fcntl.LOCK_UN)

    thread = threading.Thread(target=run)
    thread.seen = []
    return thread


def card_count(g):
    return sum(len(s.cards) for s in g.slots)


def card_multiset(g):
    """Every card on the board as a Counter of (rank, suit)."""
    return Counter((c.rank, c.suit) for s in g.slots for c in s.cards)


def clear_board(g):
    """Empty every slot, for building a contrived position by hand."""
    for s in g.slots:
        s.cards = []


def random_op(g, rng):
    """Make one random player action on g.

    Mostly moves (sane and silly pickup sizes alike), plus deals, autoplay,
    clicks, undo and redo, so random play pokes every code path.
    """
    ns = len(g.slots)
    r = rng.random()
    if r < 0.16 and g.can_deal():
        g.deal()
    elif r < 0.28:
        g.autoplay()
    elif r < 0.38:
        g.undo()
    elif r < 0.45:
        g.redo()
    elif r < 0.54:
        g.double_click(rng.randrange(ns))
    elif r < 0.61:
        g.click(rng.randrange(ns))
    else:
        g.attempt_move(rng.randrange(ns), rng.randrange(ns), rng.choice([None, 1, 2, 3, 5, 13]))


class Steps(engine.GameDef):
    """A test game that places its cards by hand, one over two as Triple
    Peaks' peaks are: a stock, then a face-down card at (0, 1) on two
    face-up ones at (1, 0) and (1, 2)."""

    key = "steps"
    name = "Steps"
    SPOTS = ((0, 1), (1, 0), (1, 2))

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        self.stock = g.add_slot("stock")
        g.carriage_return()
        self.steps = [g.add_slot("tableau") for _ in self.SPOTS]
        for i, t in enumerate(self.steps):
            g.deal_from_deck(t, 1, face_up=i > 0)
        while g.deck:
            g.deal_from_deck(self.stock, 1, face_up=False)

    def spot(self, g, sid):
        i = sid - self.steps[0]
        return self.SPOTS[i] if 0 <= i < len(self.SPOTS) else None


def steps():
    """A dealt game of Steps, which never goes into engine.GAMES."""
    g = engine.Solitaire(Steps(), seed=1)
    g.new_game(1)
    return g


def board_state(g):
    """The cards on the board, slot by slot, ignoring score and counters."""
    return tuple(tuple(s.cards) for s in g.slots)


def stalled_klondike(blocked=False):
    """Klondike, every card face up, that safe autoplay leaves with one card
    up: 5H and 5D wait on the black fours, and 4C is under 5H. Sent up in
    any order that will go, every card still gets home. Blocked, 5C sits
    on the 4C it needs, so they can't."""
    g = deal("klondike", 1)
    fids, t = g.ids_of("foundation"), g.ids_of("tableau")
    clear_board(g)
    for f, suit, top in zip(fids, "SHDC", [4, 4, 4, 3]):
        g.slots[f].cards = [engine.Card(r, suit, True) for r in range(1, top + 1)]
    lowest = {"S": 5, "H": 5 if blocked else 6, "D": 5, "C": 6 if blocked else 5}
    for col, suit in zip(t[1:], "SHDC"):
        g.slots[col].cards = [engine.Card(r, suit, True) for r in range(13, lowest[suit] - 1, -1)]
    g.slots[t[0]].cards = [engine.Card(4, "C", True), engine.Card(5, "C" if blocked else "H", True)]
    return g


def legal_walk(g, rng, steps, allow=None):
    """Random play that mostly makes legal moves; yields after every step.

    allow(g, (src, dst, n)) can veto moves the caller wants to stay away from.
    """
    for _ in range(steps):
        r = rng.random()
        if r < 0.10 and g.can_deal():
            g.deal()
        elif r < 0.16:
            g.undo()
        elif r < 0.20:
            g.redo()
        elif r < 0.26:
            g.autoplay()
        else:
            moves = [m for m in g.legal_moves() if allow is None or allow(g, m)]
            if moves:
                g.attempt_move(*rng.choice(moves))
            elif g.can_deal():
                g.deal()
        yield


class FakeScr:
    """Just enough of a curses window for BoardUI.

    Keeps a character grid so a test can read the screen back as text.
    """

    encoding = "utf-8"  # what curses took from the locale

    def __init__(self, h=40, w=140):
        self.h, self.w = h, w
        self.erase()

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        self.grid = [[" "] * self.w for _ in range(self.h)]

    def refresh(self):
        pass

    def keypad(self, flag):
        pass

    def timeout(self, ms):
        pass

    def addnstr(self, y, x, text, n, attr=0):
        try:
            text.encode(self.encoding)
        except UnicodeEncodeError:
            # as curses does: the whole string is refused, not just the glyph
            raise curses.error("addnwstr() returned ERR") from None
        if not 0 <= y < self.h:
            return
        for i, ch in enumerate(text[:n]):
            if 0 <= x + i < self.w:
                self.grid[y][x + i] = ch

    def getch(self):
        return -1

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)
