# Changelog

All notable changes to Soliterm are written down here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Soliterm follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Soliterm grew out of aisle-cli, a private project of mine that played the
same kind of games in a terminal under the command `aisle`. Its one
release, aisle-cli 1.0.0 of 2026-06-29, stays at the bottom as history, and
Soliterm 1.0.0 lists the changes since.

## [Unreleased]

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

[Unreleased]: https://github.com/bwenstar/soliterm/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/bwenstar/soliterm/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/bwenstar/soliterm/releases/tag/v1.0.0
