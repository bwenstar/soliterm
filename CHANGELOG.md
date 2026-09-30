# Changelog

All notable changes to Soliterm are written down here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Soliterm follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Soliterm grew out of aisle-cli, a private project of mine that played the
same kind of games in a terminal under the command `aisle`. Its one
release, aisle-cli 1.0.0 of 2026-06-29, stays at the bottom as history, and
Soliterm 1.0.0 lists the changes since.

## [Unreleased]

This release is about the first few games and the reasons to come back
after them. There's a thirteenth game, Pyramid. A move the rules refuse
says why, `p` pauses and `y` copies a share code. Each game has a page of
records and three achievements, the daily list keeps a streak of days,
and the win banner says how you did on that deal before. All of that is
worked out from the history Soliterm has kept since 1.0, so the games
you've played here already count, and no file has changed its format.

### Added

- Pyramid, AisleRiot's Thirteen, for thirteen games in all. You take a
  pyramid of 28 cards apart in pairs whose ranks make 13, a King going on
  its own, with only the bottom row dealt face up and one pass through
  the stock. Put a card down on its partner to take both off, and `f` or
  a double-click takes off a King, or the top two cards of the waste when
  they make 13. It shares AisleRiot's record of Thirteen, so any games of
  it you've played there show up straight away, and its share codes,
  such as `pyramid:216`, deal the same cards from now on, as the other
  games' do. [docs/games/pyramid.md](docs/games/pyramid.md) has the
  rules, and when AisleRiot counts a game of it as won.
- Each game has a page of records. Enter on its row of the statistics
  opens it, as does a click on the row already picked, and Left and Right
  go through the other games. It has the games played and won, the
  fastest win and the one in the fewest moves, each with its deal and
  date, the best score for each set of options, which a lost game can
  hold too, and the win streak. They count only the games played here,
  so they can come from fewer games than the Wins and Total, and the
  page says so.
- Three achievements, on each game's records page: a clean win of that
  game, with no hint and no undo, a win in every game, and a daily won
  seven days in a row. Each gives the day it was earned or how far along
  you are. Like the records they come from `history.jsonl` each time, so
  they count the games played here and not AisleRiot's, and a win from
  before 1.1, which didn't count its hints and undos, can't be a clean
  one.
- The daily list says how each of today's dailies went: `won in 3:12,
  87 moves` for your best win of it, `played, not won yet`, or
  `saved at 0:42, 31 moves` for one waiting to be picked up. Over it is
  your daily streak, the days in a row with a daily won in any game, and
  the longest, and until one of today's is won, a reminder that it needs
  one to keep going. A daily won or lost can still be played again.
- The win banner says how a win stood against your best win of the same
  deal, on time and then on moves: `On this deal: a new best, was 2:40,
  61 moves`, or `your best is 1:58, 44 moves`. The first win of a deal
  says nothing more, and a game with no moves left gives your best win of
  its deal, if there is one. The deal is the game, its number and the
  options, so a daily is the same deal as the plain one of its number
  with the standard options, as they have the same cards.
  Text mode prints the same line under a win's share code.
- A move the rules refuse says why, in the full-screen game and in text
  mode, as in `illegal move: 8D doesn't go on 10D, which takes a black 9`.
  Each game gives its own rules' reasons, names the cards the way the
  board does, and gives nothing away about a face-down card.
- `p` pauses the full-screen game. A page over the board says how long
  you've played, and the clock stands still until any key or a left
  click takes you back. A game left from behind it, as when the terminal
  closes, keeps the time played up to the pause and none of the pause
  itself.
- In the full-screen game `y` copies the share code of the deal in play,
  and on the banner at the end of a game the share code, or a daily's
  share line, and the message names what went. On Windows it goes on the
  clipboard. Anywhere else Soliterm asks the terminal to copy it, with
  the escape sequence OSC 52, as it never runs another program to reach
  the clipboard. Not every terminal takes OSC 52 and none says whether it
  did, so the message only says it was sent. In tmux it needs
  `set -g set-clipboard on`, and under GNU screen it goes through screen
  to the terminal outside. [SECURITY.md](SECURITY.md) adds the clipboard
  to what Soliterm writes.
- Text mode says when a game has nothing left to do that could still win
  it, once, under the board: `No moves left - game over. Type u to undo
  or n for a new deal.` It doesn't count the game yet, so `u` can still
  go back and try another way, and after an undo it waits for your next
  move before it says so again. See
  [docs/text-mode.md](docs/text-mode.md).
- In text mode a daily that counts as lost, when you leave it with `q`,
  deal again with `n` or the input runs out, prints the line to share
  that a won one does, as in `Soliterm daily 2026-09-24, Klondike: stuck
  after 4:05, 57 moves`.
- [docs/img/hero.cast](docs/img/hero.cast) is a recording of a game of
  Klondike, made from what the game itself wrote to the terminal, and
  `asciinema play docs/img/hero.cast` plays it back.

### Changed

- When `TERM` names a terminal type this system has no terminfo entry
  for, as over ssh from a terminal newer than the far end, the
  full-screen game plays as `xterm-256color`, or `xterm`, and inside tmux
  or screen as `screen-256color` or `screen`, where it used to go to text
  mode. The first game's message line says so, stderr says it again once
  the screen is back, and so does `--debug-info`. Installing the
  terminal's own terminfo entry there gets you its full look. With none
  of those known either, it's text mode as before.
- In a terminal too short for them, the menu, the daily list and the
  statistics scroll their games, with a line above or below saying how
  many more there are that way, where they used to say the terminal was
  too small. PgUp, PgDn, Home and End move the pick on all three, the
  wheel moves it a row, and a click on a "more" line turns the page. The
  help and a game's records scroll the same way when they don't fit. See
  [docs/keybindings.md](docs/keybindings.md).
- The statistics always pick out a game's row now, the one in play as
  before or else the first, so there's one to scroll by and to open, and
  a click on a row picks it. Up and Down (or `k` and `j`), PgUp, PgDn,
  Home, End and Enter no longer close them, and any other key still
  does. Without colour the row picked is marked with `>`, as on the menu.
- Text mode says what has gone wrong with Soliterm's files as the game
  starts, such as one set aside as damaged, on stderr before its first
  board, where it used to wait until the game was over, and it doesn't
  say it again on the way out.
- `--reset-stats` says the records and achievements go with the history,
  when there's a history to clear, and that putting `history.jsonl.bak`
  back as `history.jsonl` brings them back.
- The test suite has grown to about 3,700 tests, from about 2,900, and
  still needs only pytest. Two of them start a Python of their own to
  look up `xterm-256color` and `screen-256color` in the system's
  terminfo, and each skips where that Python's curses has no entry for
  it.

### Fixed

- When AisleRiot was open, the warning saying so on the first game's
  message line hid the game's own note, such as `Resumed your game` or
  that its save couldn't be read. Now the line gives every note in turn,
  most pressing first, with anything that has gone wrong with the files
  so far, and each key that leaves the line as it was brings up the next.
- A message too long for the message line comes in pieces that each fit
  at 80 columns, code skin and all, and a key with nothing of its own to
  say brings up the next. The note that a saved game is being played
  somewhere else was cut off at the edge after `n`, `g`, `o` or a game
  picked from the menu, and so were the longest things Scorpion and
  Spider say when there's no hint or no deal.
- On Windows, Ctrl-Break at the `--reset-stats` prompt ends it at once,
  where it did nothing until Enter was pressed. It clears nothing, even
  when a yes comes in with it, and ends with 130 as it did.
- When curses finds no terminfo database at all, as with a Python built
  to look only in a folder of its own, the line on stderr says so, and
  that `TERMINFO_DIRS=/usr/share/terminfo:/lib/terminfo` points it at
  the system's. It used to say to set `TERM` to your terminal's type,
  `xterm-256color` for most, even when that was what it was already.
- A text-mode win in under half a second, as a script can make, prints
  its time as 0:01, the time the statistics and the history keep, where
  it printed 0:00. So does a daily's share line.
- On Windows without windows-curses, the note on how to add it says
  `py -m pip install windows-curses`, as the README does. It said
  `pip install windows-curses`, and a python.org install doesn't put
  `pip` on the PATH unless you ask it to.

## [1.1.0] - 2026-09-29

### Added

- [docs/compatibility.md](docs/compatibility.md) says what stays the same
  from one release to the next: the deals, share codes and the daily
  deal, the game keys and slot ids, the command line, what a script can
  read in text mode, and the files, with what an older version makes of
  a newer one's. It also says what isn't promised.
- On Linux, while statistics are shared, the first game says so when
  AisleRiot is open, on the bottom line or, in text mode, on stderr. A
  game finished here while it's open drops out of both when it quits. It
  looks through /proc for a `sol` of your own and runs nothing.
- Each game counts the hints you asked for and the moves you took back.
  The history's line for a game and its save carry them as `hints` and
  `undos`, for records to come, and nothing shows them yet. A game
  resumed from an older save leaves them out, as unknown, rather than
  counting from 0. 1.0.1 reads both as it did.
- The README shows how to play with uv (`uvx soliterm` or
  `uv tool install soliterm`), and how to check a downloaded
  `soliterm.pyz` against the release's `SHA256SUMS` and the attestation
  of where it was built.
- The README, the man page and the architecture notes say which Windows
  setups Soliterm has been tried on: conhost on Windows Server 2025, with
  Python 3.9 and 3.14. Windows Terminal and desktop Windows 10 and 11
  haven't been tried by hand yet.

### Changed

- The Klondike hint takes a card back down from a foundation when that
  lets another go on it and turns a face-down card over, and where
  nothing clearly helps it says to try one, as AisleRiot does, rather
  than to undo. Following the hint alone now wins 120 of the first 300
  deals drawing one, up from 106, and none of the other options wins
  fewer.
- On Windows the board draws the suits and the card edges, where a
  console always got letters and plus signs. A console font without the
  glyphs still needs `--ascii`.
- On Windows the dark, light and contrast themes use their own colours
  in Windows Terminal and in ConEmu with its ANSI on. The classic
  console only has 16 colours, which would draw the diamonds in the
  hearts' red, so there they look like `classic`, as on any 16-colour
  terminal.
- In Golf and Triple Peaks, `f` or a double-click on a card that doesn't
  go on the waste names the card, as text mode does. A face-down one is
  "that face-down card", so it isn't given away.

### Fixed

- A game picked up from its save is no longer lost for good when it ends
  some other way than `q`, `m` or Ctrl-C, such as a crash, a `kill -9`
  or, on Windows, the console closing. The save stays in the folder as
  `saves/<game>.in-play.json` while the game is played, locked so no
  other copy can take it up, and the next start offers it again as it
  was. An error in the full-screen game puts the game away first, as
  text mode does.
- On Windows, closing the console window or pressing Ctrl-Break keeps
  the game, or counts it, as Ctrl-C does. Both used to end Soliterm at
  once and lose it. After a close Windows still ends the process, with
  status 0xC000013A, and Ctrl-Break leaves with 130.
- On Windows two copies finishing at once no longer lose a result. The
  lock on the statistics was only there on Linux and macOS, and with two
  copies recording 25 wins each at the same moment, stats.json kept 5 to
  7 of the 50.
- On Windows bold no longer changes the colours. PDCurses draws it as
  the bright one, which turned the cursor and the selection grey, and in
  the tuned themes a card picked up dark grey and the banner's gold pale.
- Ctrl-Z stops the game clock, as it does in AisleRiot, so a game left
  stopped for an hour no longer comes back an hour slower. In the
  full-screen game up to a second of play can go with the stop.
- The tests pass under `LC_ALL=C` without UTF-8 mode, with SIGINT
  ignored from the start, as a build in the background has it, and from
  the unpacked sdist, which now carries the games' pages too. The ones
  that break off a wait for the statistics lock watch for the wait
  rather than sleep, so a slow machine doesn't fail them.
  CONTRIBUTING.md tells packagers what the suite needs.
- The man page and the text-mode notes said an unset or unknown `TERM`
  means text mode, which only holds off Windows.

## [1.0.1] - 2026-09-29

### Fixed

- On Linux, text mode keeps your game when the terminal closes on it, as
  the README said it did, and a byte that isn't UTF-8 in what you type is
  a bad command now instead of a crash. Both used to lose the game, and
  one you'd resumed lost its save for good.
- Text mode shows its colours in a Windows console, where it printed the
  escape codes as text, and boss mode clears the screen there. A console
  that can't show them gets none.
- On Windows, numpad Enter, numpad + and -, and the numpad arrows with
  NumLock off do what the main keys do, in the game and on the menu.
- The hint no longer says "Deal from the stock" forever in Canfield, or
  in Klondike drawing three or with unlimited redeals, where dealing only
  brings the same cards round again. It offers the move that sets one up
  instead, which on canfield:59 leads on to a win. In Klondike drawing
  one with its two redeals, the hint makes that move while it still has
  a redeal in hand, rather than spending the redeal first.
- Following a hint with the keys makes the move the hint names. Enter
  lifts the longest run, and dropping that where the hint said used to
  put all of it down, even when the hint moved fewer cards.
- Changing a setting in the full-screen game saves only that setting.
  It used to write back the whole config.json it read at the start, over
  any edit made by hand in the meantime and without the keys it didn't
  know.
- A config.json or stats.json saved with a byte order mark, as Notepad
  can save it, or in UTF-16, as PowerShell can, is read as it is. It used
  to be set aside as damaged, and everything in it started over.
- When stats.json can't be written, Soliterm says the game is missing
  from it, where it used to count the game on screen and then lose it
  without a word. `--reset-stats` then clears nothing, says why and
  exits 1.
- A best or worst time over 100 minutes counts as no time, as it does in
  AisleRiot, so the two show the same statistics, and a win that long is
  shared with no time.
- The win percentage rounds a half up, as AisleRiot does, so 1 win in 8
  is 13% in both.
- The code skin shows the game's status whole at 80 columns, where five
  games lost the end of it, and leaves out the deal number first when
  there isn't room.
- The "Terminal too small" notice gives the whole size it needs and the
  size it has, even in a narrow window.
- `--stats` skips a line of `history.jsonl` with control characters or
  broken text in it, rather than print them to the terminal or crash.
- Output to a reader that has gone, as with `| head`, ends with status
  141 for `--help` and `--version` as well, and when whatever reads
  stderr has gone, the status is no longer 120.
- The docs say that on Windows, closing the console window or pressing
  Ctrl-Break ends Soliterm at once and loses the game, where `q`, `m` and
  Ctrl-C keep it, and that text mode's end of input there is Ctrl-Z and
  then Enter.
- The docs say that a game finished here while AisleRiot is open drops
  out of the statistics of both when AisleRiot quits, since it writes its
  own copy of the keyfile back, and that the lock that stops two copies
  of Soliterm losing each other's results is only there on Linux and
  macOS.

## [1.0.0] - 2026-09-28

Soliterm's first public release. It grew out of aisle-cli, a private
project of mine, and these are the changes since aisle-cli 1.0.0, which is
at the bottom of CHANGELOG.md.

### Added

- Three new games: Spiderette, Triple Peaks and Scorpion, for twelve in
  all. Each shares its statistics with AisleRiot's own record of it, so
  any games of them you've played in AisleRiot show up straight away, and
  each has its page in `docs/games`. Triple Peaks has AisleRiot's
  multiplier scoring as an option.
- Every deal has a number, shown on the board, at the end of a game and in
  text mode. `--deal N` plays deal N, and `n` then deals the next one.
  FreeCell deals are numbered as in Microsoft FreeCell.
- Share codes such as `klondike:d3:48213` name a deal with its options.
  The end of a game shows its code, and `--deal` takes one, as do the `g`
  key during a game and Play a deal on the menu.
- A daily deal for every game, from `--daily` or Daily deal on the menu:
  the same cards for everyone that day, with the standard options. When
  it ends there's a line to share that names no cards. It works offline.
- `--draw` and `--suits` set Klondike's draw or Spider's suits for one run
  without saving them.
- A game you've started is kept for next time when you leave it with `q`,
  `m` or Ctrl-C, or close the terminal on it, instead of counting as lost.
  Its menu row reads `Resume your game: 0:42, 31 moves`, and picking it or
  starting it with `--game` carries on where you left off, while a chosen
  deal or option starts afresh and leaves it waiting. A daily is kept the
  same way, its menu row says so, and that day's daily carries on with it.
  Text mode keeps games too, when you're typing at a terminal. On the way
  out a line says which game was kept and how to pick it up again.
- Every game played here goes in `history.jsonl`, one line each. The
  statistics gain Streak and Longest columns, the win banner and text mode
  name a run of two or more wins, and `--stats` lists the last ten games
  and marks the dailies.
- `a` finishes the game once every card left can go up, safe or not, as
  one move, and the message line says when that is. It does in text mode
  too.
- `U` and `R` undo and redo every move at once, and text mode has
  `undo all` and `redo all`. `U` used to be the same as `u`. It keeps the
  clock and redo, where `N` deals the hand again as a new game.
- A kept game takes its newest 500 undo steps with it, and `U` on a
  longer one says it stopped at the oldest move saved, as does text
  mode's `undo all`.
- The finish sends the cards up one at a time, and a win bounces them off
  the board. Any key skips either, the boss key still hides everything at
  once, and `--no-animation` or `"animation": false` in config.json turns
  them off.
- The win banner says when a win is your first of that game or a new best
  time.
- Themes for the full-screen game: `classic` (the look it always had),
  `dark`, `light` and `contrast`. `t` moves on to the next one and
  remembers it, and `--theme NAME` picks one for a single run. A terminal
  with too few colour pairs for a theme draws the ones it has no room for
  in colours it does have. When `COLORFGBG` says the terminal's
  background is light, `classic` and `contrast` swap the colours that
  would vanish on it for ones that show.
- A four-colour deck with green clubs and orange diamonds (blue diamonds
  on terminals without 256 colours). `4` turns it on and off, and it's
  remembered too. A terminal without the colour pairs for it says so, and
  the choice is kept for one that has them.
- The code skin colours its source's keywords, strings and numbers as an
  editor would, in the theme's colours.
- `+` and `-` lift one card more or fewer while you hold a run, so the
  keyboard can split a run the way a click mid-stack does.
- `--debug-info` prints what a bug report needs: the versions, the
  terminal, curses and where Soliterm keeps its files. It only reads, and
  leaves every file as it was.
- `--version`, and `--no-sync` (or `SOLITERM_NO_AISLERIOT=1`) to leave
  AisleRiot's statistics alone for a run.
- Text mode puts a number on every slot, a hint is a command you can type
  as it stands, a command that does nothing says why, and `N` starts the
  deal over as it does in the full-screen game.
- Windows, through the windows-curses package, which pip installs there
  by itself.
- A man page, `soliterm(6)`.

### Changed

- The command is `soliterm` now, and settings and statistics live in
  `soliterm` folders under `~/.config` and `~/.local/share`. The first run
  copies aisle-cli's `config.json` and `stats.json` across, once, and
  leaves the old files where they are.
- Deals come from Soliterm's own shuffle, not Python's, so a number deals
  the same cards on every Python. This means the numbers from aisle-cli
  1.0.0 deal different cards now. `--seed` still works as another name for
  `--deal`, though `--help` no longer lists it, and numbers run from 0 to
  2147483647.
- In the full-screen game, `--deal 5` without `--game` goes straight into
  the game played last instead of the menu, and only that first game is
  deal 5, not every game picked from the menu.
- SIGHUP and SIGTERM leave the way Ctrl-C does, so the game is kept, and
  the exit status is 130. One ignored already, as `nohup` ignores SIGHUP,
  stays ignored.
- `--reset-stats` asks first (`--yes` skips the question) and keeps a
  backup of what it clears. It clears the history as well, and every game,
  in AisleRiot's keyfile too when sharing, but leaves saved games alone.
- Spider deals four suits by default, in AisleRiot's layout, and Golf
  starts with the waste empty, as AisleRiot's does.
- Autoplay only sends up cards that are safe to send up.
- A hint can be a move that sets up the next one, and in Spider one that
  fills an empty column so you can deal. When nothing gains, it names a
  plain move that goes somewhere instead of saying no move helps. It
  lights up the whole run it would move, not just the top card, in a
  colour of its own that shows on any background.
- `o` shows the options before it gives up the game in play. Esc, or
  leaving them as they were, keeps the game, a change mid-game asks
  first, and new options deal the next number, the way `n` does. Where
  Soliterm asks whether to give a game up, only `y` says yes, so an Enter
  too many can't.
- A game counts from its first move, even if you undo every move. One
  with no moves left offers Undo on its banner and counts as lost only when
  you leave it for a new deal or the menu.
- The end-of-game banner shows each choice with its key, as in
  `Replay this deal (s)`.
- In Golf and Triple Peaks, Enter or a click on a card that goes on the
  waste plays it, as a click does in AisleRiot. One that doesn't go is
  picked up as before.
- The clock ticks on the status line and stops while another screen hides
  the board, and the banner shows the same time the statistics keep.
- A board that's short of room closes up before it loses anything. A long
  column piles its face-down cards onto one row that counts them and
  keeps every face-up rank in view, the columns beside it squeeze alike,
  and a wide game closes up its fans and the gaps between its columns. A
  board, the menu or a dialog that still doesn't fit says what size it
  needs instead of drawing off the edge.
- Klondike drawing three fans out the last three cards of the waste, as
  AisleRiot does, and the stock's count sits on the stock itself.
- The code skin stays on for the menu, the dialogs, the banners and the
  too-small notice, which show as comments in the same file, and draws
  its source in the terminal's own colours instead of a card's black on
  white. Its board sits as high as the plain one, so it takes no rows
  from the cards.
- When curses can't drive the terminal, or can't load at all, Soliterm
  says why and plays in text mode.
- `--no-color` and `NO_COLOR` beat the colour saved with `v`, and `--ascii`
  works in the full-screen game as well as in text mode.

### Removed

- The `aisle` command and the aisle-cli package. `soliterm` replaces them.
- Python 3.8. Soliterm needs Python 3.9 or newer.

### Fixed

- The menu gives each game a line short enough to show whole at 80
  columns, where most were cut off mid-word, and `--list` uses the same
  line, so it fits in 80 columns too. `--help` sends you to `--list` for
  the game names instead of spelling them all out twice.
- The help screen no longer says every game builds its foundations up by
  suit, which isn't true of them all.
- A text-mode game won in one move says `1 move`, not `1 moves`, and
  Spider's status line says `1 deal`, not `1 deals`.
- Games played while not sharing statistics, for a game this version
  doesn't have, are kept for the version that recorded them instead of
  being dropped.
- AisleRiot's keyfile is read the way GLib reads it. Each statistic is
  written over the keyfile as it is at that moment, so one AisleRiot saved
  in the meantime isn't put back, and a keyfile that can't be read, or
  isn't valid UTF-8, is left as it is. A game missing from it is rebuilt
  from Soliterm's own record, games played while sharing was off are
  shared once it's back on, and Soliterm says so when it can't write the
  file.
- Settings and statistics are written whole, so a crash can't leave half a
  file, and a damaged one is kept aside instead of being written over. A
  hand-edited file is read a value at a time, so one bad value doesn't
  lose the rest, and a bad game option falls back to its default.
- A game kept waiting while another copy of Soliterm finishes with the
  statistics says so, instead of stopping without a word. If Ctrl-C,
  SIGTERM or SIGHUP cuts leaving short while it waits, a note at exit says
  the game was neither saved nor counted, and a deal you haven't touched
  leaves without waiting at all.
- Rules that had drifted from AisleRiot's: Klondike drawing one no longer
  redeals forever, FreeCell's foundation cards stay out of play, Aces
  can't slide between foundations for points, Eight Off and Forty Thieves
  move only as many cards at once as their free cells or empty columns
  allow, and a Spider game with too few cards left to deal ends. Canfield
  and Bakers Dozen let foundation cards come back down, Canfield counts
  its base card in the score, and Forty Thieves is scored as AisleRiot
  scores it, can send a whole run up in one move, and on a double-click
  puts a card that can't go up onto a column.
- Statistics are only shared when AisleRiot is there, as its keyfile or
  its `sol` program, and not just because there's a `gnome-games` folder,
  which other GNOME games keep too. Until AisleRiot has run once, the
  statistics screen says they'll be shared from then on.
- `--reset-stats` only says the statistics are shared with GNOME
  AisleRiot when AisleRiot has a record of one of these games to clear,
  and then says `1 game`, not `1 game(s)`.
- Double-clicking a foundation sends up every card that can go.
- In Golf, Triple Peaks and Scorpion, an `f` or a double-click that does
  nothing says why, as those games have no foundations. Text mode's `f`
  does too.
- The mouse: a slow click picks a card up instead of undoing itself, a
  double-click at a normal speed counts, and a click straight after a
  drag isn't taken for one. Moving the pointer doesn't move the cursor,
  and letting go of a click doesn't move the menu's. A click on the menu
  or a dialog doesn't turn up on the board afterwards, and the banner
  only takes a left click on a choice.
- The keys: Esc acts at once, and Alt with a key is no longer read as Esc
  and then the key. Help and statistics stay up until a key is pressed.
  The boss key works on every screen, not just the board, and brings you
  back to where you were. Boss mode stays up when the mouse moves or the
  window is resized, and game keys do nothing while the terminal is too
  small to show the board.
- Hints name cards as the board draws them and no longer tell you to deal
  when you can't, the Spider summary no longer claims that builds must
  follow suit, and the status line catches up after undo and redo.
- Picking up a run names its card as the board draws it and says
  `2 cards`, not `2 card(s)`.
- A card dealt from the stock clears the line saying why the move before
  it did nothing.
- `*** YOU WIN! ***` shows in full on an 80-column status line in every
  game, code skin too, where a long status used to cut it off.
- The full-screen game starts on terminals that can't hide the cursor and
  on colour terminals without default colours, draws plain cards when the
  locale can't show the suit symbols, and keeps a ten inside its card at
  the narrowest width and in the compact view.
- Text mode lines the cards up under their tags, times each deal on its
  own clock, counts a game left unfinished from a pipe as lost, uses
  letter suits when the output can't show the symbols, and leaves quietly
  on Ctrl-C or when piped into `head`. Its boss screen hides the board
  properly, with paths that fit the platform.
- Soliterm starts on Klondike when the game played last no longer exists.

## aisle-cli 1.0.0 - 2026-06-29

- Initial release. A dependency-free terminal Solitaire collection, a
  command-line replica of GNOME AisleRiot (`/usr/games/sol`), pure Python 3
  with no third-party packages.
- **Nine games**: Klondike, Spider (1/2/4 suit), FreeCell, Eight Off, Golf,
  Yukon, Bakers Dozen, Forty Thieves, Canfield.
- **Curses TUI** with keyboard **and** mouse: arrow-key cursor, click to
  pick up / drop, click mid-stack to split a run, double-click to a foundation
  (or to deal on the stock).
- **Real overlapping card art**: top card full-size, covered cards peek with
  their rank visible, with a one-key toggle (`x`) to the compact legacy view.
- **Progress-based hints** (`h`) that only ever suggest a move which advances
  the game, and are provably loop-free.
- **AisleRiot statistics sharing**: reads from and writes to the installed
  GNOME AisleRiot keyfile, so games played in either program are mirrored in
  both (wins / total / percentage / best & worst time).
- Live toggles, all persisted: colour on/off (`v`), code-skin play mode (`c`),
  and a boss key (`b` / F2) that hides the board behind fake build output.
- Restart-this-deal, undo/redo, autoplay, "no moves left" detection, and an
  end-of-game banner with same-deal / new-deal / menu choices.
- Pipe-friendly text mode (`--text`) and three distribution forms: a zero
  install single-file zipapp, a pip wheel + sdist, and a source archive.
- 17 test files covering the engine, all nine games' rules, scoring, undo/redo,
  hints, statistics persistence, and the rendering modes.

[Unreleased]: https://github.com/bwenstar/soliterm/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/bwenstar/soliterm/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/bwenstar/soliterm/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/bwenstar/soliterm/releases/tag/v1.0.0
