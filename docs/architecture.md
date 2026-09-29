# How Soliterm fits together

This is a map of the code for anyone who wants to change it. It's short
on purpose: each section says where to look, and the docstrings in the
files say the rest. Everything under `src/soliterm` is standard library
Python, 3.9 or newer, and the only package it ever needs is
windows-curses, on Windows. None of it is an API to build on: the modules
are provisional and can change in any release.
[compatibility.md](compatibility.md) says what does stay the same.

## The layout

The engine knows the rules and nothing about screens. The two front ends,
the full-screen game and text mode, drive it, and a handful of small
modules around them keep the files.

| Where | What it does |
| --- | --- |
| [`engine/`](../src/soliterm/engine/) | the cards, the slots and the game state |
| [`engine/core.py`](../src/soliterm/engine/core.py) | `Solitaire`, the state every front end drives: slots, score, moves, undo and redo, hints, autoplay and the finish |
| [`engine/gamedef.py`](../src/soliterm/engine/gamedef.py) | `GameDef`, the base class each game fills in, and the rule helpers games share |
| [`engine/cards.py`](../src/soliterm/engine/cards.py) | `Card`, `make_deck` and the suit and rank constants |
| [`engine/rng.py`](../src/soliterm/engine/rng.py) | the shuffles: PCG32, Fisher-Yates and Microsoft FreeCell's deals |
| [`engine/games/`](../src/soliterm/engine/games/) | one module per game, and in `__init__.py` the registry, `GAMES` and `GAME_ORDER` |
| [`tui/app.py`](../src/soliterm/tui/app.py) | the full-screen game: the menu, the dialogs, the play loop and the end banner |
| [`tui/board.py`](../src/soliterm/tui/board.py) | draws a board with curses and keeps the map that clicks go through |
| [`tui/keys.py`](../src/soliterm/tui/keys.py) | `KEYMAP`, the one table of what each key does |
| [`tui/cascade.py`](../src/soliterm/tui/cascade.py) | the sums behind the cards bouncing off the board after a win |
| [`textmode.py`](../src/soliterm/textmode.py) | text mode: the plain board and the command loop |
| [`cli.py`](../src/soliterm/cli.py) | the command line, and the choice between the two front ends |
| [`deals.py`](../src/soliterm/deals.py) | deal numbers, share codes and the daily deal |
| [`store.py`](../src/soliterm/store.py) | `config.json` and `stats.json`, and sharing statistics with AisleRiot |
| [`aisleriot.py`](../src/soliterm/aisleriot.py) | reads and writes AisleRiot's keyfile, a line at a time |
| [`saves.py`](../src/soliterm/saves.py) | the games kept for next time, one of each kind |
| [`history.py`](../src/soliterm/history.py) | `history.jsonl`, a line for every game, for streaks and `--stats` |
| [`migrate.py`](../src/soliterm/migrate.py) | copies aisle-cli's settings and statistics across on the first run |
| [`debuginfo.py`](../src/soliterm/debuginfo.py) | what `--debug-info` prints, without writing anything |
| [`themes.py`](../src/soliterm/themes.py) | the colour themes, as tables of colour pairs, away from curses |
| [`camo.py`](../src/soliterm/camo.py) | the boss screen's fake work and the code skin's source |

Outside the package, [`tools/`](../tools/) has the scripts that build the
zipapp, write [keybindings.md](keybindings.md) and take the screenshots,
and [`tests/`](../tests/) has the suite.

## The engine

A game is a list of slots, each with a kind (stock, waste, foundation,
tableau, free cell or reserve), the way its cards fan out, and its cards.
`Solitaire` holds them along with the score, the moves and the undo and
redo stacks, and asks the game's `GameDef` whenever a rule comes up: can
these cards be picked up, can they land there, what does a click on this
slot do, is the game won. It's AisleRiot's design, where each game is a
Scheme file answering the same questions, written again in Python. No
AisleRiot code is copied.

Slots are numbered in the order the game adds them, and those numbers are
what text mode prints, what saves store and what the tests name, so a
game keeps its order once it's out.

Every move goes through one of five doors in
[`core.py`](../src/soliterm/engine/core.py): `attempt_move` for cards
from one slot to another, `click` and `double_click` for what a game
does on a click, `autoplay` for sending up the cards that are safe to
send, and `finish` for sending up every card left. Each one checks with
the game, writes the position onto the undo stack, makes the move, bumps
the move count by one and calls the game's `post_move`, where Spider
sends a finished run up.

Only `attempt_move` and `finish` move the cards themselves, so only those
two call the game's `after_move` for the cards that moved, which is where
most games score. The finish counts as one move, but it sends the cards
up one at a time and calls `after_move` and `post_move` for each.
`click`, `double_click` and `autoplay` leave the moving to the game's
`on_click`, `on_double_click` and `autoplay`, which do their own
scoring, so anything a game has to do after every move belongs in
`post_move`.

Undo and redo swap whole positions, written out by `serialize()`, so no
game has to know how to take a move back.

## From a key to the screen

In the full-screen game, `App.play` in
[`tui/app.py`](../src/soliterm/tui/app.py) goes round one loop: bring the
status line up to date, draw the board, check for a win or a game with no
moves left, and read a key.

1. `read_key` waits up to a second for a key, so the clock on the status
   line keeps ticking when none comes. It also tells Esc apart from Alt
   and a key, which a terminal sends as Esc and then the key.
2. `handle_key` looks the key up in `PLAY_ACTIONS`, which
   [`tui/keys.py`](../src/soliterm/tui/keys.py) builds from `KEYMAP`, and
   calls the method named after the action: Enter is `select`, so it runs
   `do_select`. While the board doesn't fit the terminal, only a few
   actions get through, the ones in `SMALL_SCREEN_ACTIONS`.
3. `do_select` deals when the cursor is on the stock, and otherwise plays
   the card there if the game's `on_click` does, as Golf and Triple Peaks
   put a card on the waste, or else picks up the longest run the game
   allows there. With cards already in hand,
   it calls `drop_on`, which asks the engine for
   `attempt_move`. When the whole run can't land, it tries the shorter
   runs off the top, so a drop puts down as many cards as will go. One
   that follows the last hint, from its pile to its place with the run
   Enter lifted, puts down the cards the hint names first.
4. Back in `handle_key`, the first move starts the clock, and when every
   card left can go up, the message line offers the finish.
5. The next time round, `App.draw` hands the game, the cursor, what's in
   hand and the hint to `BoardUI.draw` in
   [`tui/board.py`](../src/soliterm/tui/board.py), which draws the board
   again from scratch.

A click comes in as `KEY_MOUSE` and takes the same road from `do_mouse`.
While drawing, the board writes down which slot and card sit at each cell
of the screen, and `hit_test` looks the click up there, so the mouse
always agrees with what's drawn. Because the keys and the drawing are
kept apart like this, the tests drive whole games on a fake window with
no terminal at all.

Text mode is the same idea on one line at a time: `apply_text_command` in
[`textmode.py`](../src/soliterm/textmode.py) turns a command into an
engine call, and `render_text` prints the board again.

## How deals are numbered

A deal number picks the shuffle, and the same number deals the same hand
of a game on every computer and every Python. Python's own `random`
doesn't promise that, so the engine brings its own in
[`engine/rng.py`](../src/soliterm/engine/rng.py): PCG32, seeded with the
deal number, drives a Fisher-Yates shuffle. Each game has a stream of its
own, a hash of its key, so deal 5 of Klondike and deal 5 of Yukon aren't
the same cards. FreeCell uses Microsoft FreeCell's generator instead, so
its deal numbers are the ones FreeCell players already know.

Numbers run from 0 to 2147483647. A random deal is one of the first
million, so it stays short enough to read out. After a numbered deal, `n`
goes on to the next number. An option that doesn't change the deck
doesn't change the shuffle either, so Klondike deal 5 has the same cards
drawing one or three. Spider's suits do change the deck, and so the deal.

[`deals.py`](../src/soliterm/deals.py) builds on that. A share code is
the game's key, any options that aren't the defaults, one letter and a
value each, and the number, as in `klondike:d3:48213`. The daily deal is
the date as a number, 20260924 on 2026-09-24, with the standard options,
so everyone playing that day gets the same cards with no network.

The tests keep every number honest. `DEALS` in
[`tests/test_conformance.py`](../tests/test_conformance.py) holds a hash
of deals 1 and 2 of each game, and `DEALS_IN_1_0_0` one of more deals,
from 0 to 2147483647, as 1.0.0 dealt them, so a change that would deal
different cards, and break every share code for that game, fails
straight away.

## Statistics and AisleRiot

Soliterm keeps the statistics AisleRiot keeps, per game: wins, games
played, and the best and worst winning times. When AisleRiot is there, it
shares them through AisleRiot's own keyfile,
`~/.config/gnome-games/aisleriot`, so a game won in either shows up in
both. [`aisleriot.py`](../src/soliterm/aisleriot.py) maps each game to
AisleRiot's section for it in `GAME_TO_SECTION`, as `eightoff` to
`[eight_off.scm]`, and only ever changes that section's `Statistic=`
line. Every other line, and anything it can't make sense of, is written
back byte for byte.

[`store.py`](../src/soliterm/store.py) decides what goes where:

- While sharing, the keyfile is the record, and `stats.json` follows it.
  A result is added to what the keyfile holds at that moment, not to what
  Soliterm read when it started.
- The first time sharing starts, the games Soliterm had counted on its own
  are added to AisleRiot's once, and a marker in `stats.json` makes sure
  that never happens twice. The marker is saved before the keyfile is
  touched, since missing a few games beats counting them twice.
- Games played while sharing is off, with `--no-sync` or
  `SOLITERM_NO_AISLERIOT=1` or while the keyfile can't be written, are
  listed in `stats.json` and go into the keyfile with the next game that
  can be shared.
- AisleRiot reads a best or worst time over 6000 seconds (100 minutes) as
  no time, and so does Soliterm when it reads the keyfile. A win that long
  goes into the keyfile with no time, since as the worst time it would push
  out one AisleRiot can show. Only `stats.json`, for games not shared, keeps
  the real time.

The keyfile is read again right before it's written, because AisleRiot
may have saved it in between: `update_stat` works the change out from the
file as it is then, and if the file changes again while the new one is
being written, it starts over. So a result AisleRiot saved a moment ago
is never put back to an older number. That only closes the gap between
Soliterm's read and its write. AisleRiot reads the keyfile once when it
starts and, if its copy has changed by the time it exits, writes the whole
of it back, so a game finished here while AisleRiot is open is gone from
the keyfile once AisleRiot closes. The statistics Soliterm shows come
from the keyfile, so they lose it at once, and `stats.json` keeps it only
until the next game of that kind is shared, when `_share` sets its record
from what the keyfile then says. `history.jsonl` still lists the game, so
it still counts towards the streaks.

Soliterm can't stop that, but on Linux it can see it coming. While
sharing, the first game to start asks `aisleriot_open_note` in
`store.py`, and `running` in `aisleriot.py` looks through `/proc`
(`PROC_ROOT`) for a process called `sol` that is the player's own. If
there is one, the front end says AisleRiot is open, on the message line
or on stderr, once a run. It reads the names of the player's own
processes and nothing of anyone else's, and it runs and signals nothing.

Every file is written whole: to a temporary file in the same folder that
then replaces the old one in one step, so a crash or a full disk leaves
the old file as it was. A file that isn't valid JSON is moved aside to
`<name>.corrupt-<time>` rather than written over, one that can't be read
at all is left alone, and a lock beside `stats.json` keeps two copies of
the game finishing at once from losing one result. While another copy
has the lock, the game says it's waiting, on the bottom line or on
stderr, instead of stopping without a word. The lock is `flock` on
`stats.lock` on Linux and macOS. On Windows, which has no `flock`, it's
`msvcrt.locking` on the file's first byte, asked for again every 50 ms
while another copy has it, since the way Windows waits for one gives up
after ten seconds.

## Saves and signals

A game you leave with `q`, `m` or Ctrl-C, or by closing the terminal, is
kept in `saves/<game>.json` under the data folder, one per game, by
[`saves.py`](../src/soliterm/saves.py). A save holds the position, up to
500 undo and redo steps each way and the time so far. When it's taken up
again, `resume_solitaire` in
[`engine/games/__init__.py`](../src/soliterm/engine/games/__init__.py)
deals the same hand afresh and checks every saved position against it,
same slots and same cards, so a damaged or hand-edited save is set aside
instead of played. Once the full-screen game has put the terminal back,
`main` in [`tui/app.py`](../src/soliterm/tui/app.py) names the games this
run left in the folder, from `saves.kept()`.

A save that's taken up stays in the folder until the game is done with.
`take` renames it to `saves/<game>.in-play.json`, a name 1.0 never
reads, so it neither offers the game nor sets it aside, and locks
`saves/<game>.lock` the way `stats.lock` is locked, for as long as the
game is in play. The in-play file goes only once the game is kept again,
with the new save written first, or counted, or dealt again from the
start with `N` or Replay, which counts nothing; that happens inside
`store.signals_held`, and then the lock is let go. So a game that goes
any other way, by a crash, a `kill -9` or a closed console window, is
still there: the next start that can take the lock finds the in-play
file and offers it again, as it was when it was taken up. Where no lock
can be had at all, as on a file system without them, the save comes out
of the folder as it did in 1.0, and a crash loses it. One whose lock
another copy holds is in play there, and is left alone, not offered, not
set aside and not touched, and while it is, that copy has the game's one
slot, so a game of that kind left here counts as lost. A save beside an
in-play file was kept after the game was taken up, by 1.0 say, so it's
the newer one and the in-play file goes. The in-play file goes just
before the game is counted, so a crash between the two loses that game
from the statistics rather than counting it twice.

Leaving always goes the same way, whatever the reason:

- `_leave_on_signals` in [`cli.py`](../src/soliterm/cli.py) turns SIGHUP
  and SIGTERM into the `KeyboardInterrupt` Ctrl-C raises, so the terminal
  closing or a `kill` leaves by the same road as `q`. After the first,
  another does nothing, so the second SIGHUP a closing terminal often
  sends can't cut that short, unless it comes while the game waits for
  the stats lock: then it breaks off the wait, as a second Ctrl-C does.
  A signal that was already ignored, as under `nohup`, stays ignored.
  After a hangup, output goes to `/dev/null`, since the terminal has
  gone.
- The play loop catches it and calls `put_away`, which keeps the game, or
  counts it as won or lost when it can't be kept. A deal never started
  has nothing to keep, so it leaves at once, without the stats lock. Any
  other error out of the loop, a bug say, puts the game away the same
  way before it goes on, and an error doing that doesn't hide it.
- Saving a game or counting it, and marking it done, happen inside
  `store.signals_held`, which holds those signals back until the block
  is over. Without it, a signal landing between the two would have the
  game saved or counted a second time on the way out. Taking a save up
  and putting the game in play happen inside it too, so no signal lands
  while the save is in play but there's no game yet to keep again. It
  takes the stats lock first, while signals still land, so Ctrl-C or a
  signal can break off a wait for another copy of the game.

Text mode does the same in `run_text`, except that it only keeps games
for someone typing at a terminal. A script's game is counted, as it
always has been. Any other error out of its loop puts the game away too
before it goes on, since on Linux a closing terminal's read fails with
EIO before the SIGHUP comes, and a second call to `put_away` does
nothing.

Ctrl-Z stops the game without leaving it, and the clock leaves out the
time it was stopped, as AisleRiot's does. In the full-screen game ncurses
handles SIGTSTP, putting the terminal back before it stops, so all
Soliterm sees is the SIGCONT once it goes on. `carry_on` then takes off
the time since `read_key` last woke, which can take up to a second of
play with it. Text mode has no curses in the way, so `run_text` handles
SIGTSTP itself: it stops the usual way inside the handler and leaves out
the time until it's back.

Windows sends no SIGHUP or SIGTERM to turn into anything. Closing the
console window or pressing Ctrl-Break ends the process there and then
(status 0xC000013A), so the game in play is neither kept nor counted,
though one taken up from a save is offered again the next time, as it
was when it was taken up. Ctrl-C still raises `KeyboardInterrupt` and
leaves as `q` does.

## Tests

The suite never reads or writes your own files: the autouse fixture in
[`tests/conftest.py`](../tests/conftest.py) points `HOME`,
`USERPROFILE`, `XDG_CONFIG_HOME` and `XDG_DATA_HOME` at each test's own
temporary folder, and tells the store that AisleRiot isn't installed or
running, so nothing reaches a real keyfile even on a machine that has one.
A test that wants AisleRiot writes a fake keyfile with the `keyfile`
fixture.
[`tests/test_isolation.py`](../tests/test_isolation.py) checks the
fixture itself.

Some tests are worth knowing about before you change the engine:

- [`tests/test_conformance.py`](../tests/test_conformance.py) runs every
  game, with every mix of its options, through the rules every game must
  keep: the deal has every card, random play never loses one, undo and
  redo replay exactly, every hint is a legal move, and the deals stay
  pinned.
- [`tests/test_tui_app.py`](../tests/test_tui_app.py) and
  [`tests/test_tui_play.py`](../tests/test_tui_play.py) drive the
  full-screen game on a fake window.
- [`tests/test_keybindings_doc.py`](../tests/test_keybindings_doc.py)
  fails when [keybindings.md](keybindings.md) no longer matches `KEYMAP`.

[adding-a-game.md](adding-a-game.md) walks through a new game from the
first line to a passing suite.
