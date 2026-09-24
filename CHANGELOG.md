# Changelog

All notable changes to Soliterm are written down here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Soliterm follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Soliterm grew out of aisle-cli, a private project of mine that played the
same kind of games in a terminal under the command `aisle`. Its one
release, aisle-cli 1.0.0 of 2026-06-29, stays at the bottom as history, and
Unreleased lists everything that has changed since.

## [Unreleased]

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
  Text mode keeps games too, when you're typing at a terminal.
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
  in colours it does have.
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
  fills an empty column so you can deal.
- A game counts from its first move, even if you undo every move. One
  with no moves left offers Undo on its banner and counts as lost only when
  you leave it for a new deal or the menu.
- The clock ticks on the status line and stops while another screen hides
  the board, and the banner shows the same time the statistics keep.
- When curses can't drive the terminal, or can't load at all, Soliterm
  says why and plays in text mode.
- `--no-color` and `NO_COLOR` beat the colour saved with `v`, and `--ascii`
  works in the full-screen game as well as in text mode.

### Fixed

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
  statistics says so, instead of stopping without a word. If Ctrl-C cuts
  leaving short while it waits, a note at exit says the game was neither
  saved nor counted.
- Rules that had drifted from AisleRiot's: Klondike drawing one no longer
  redeals forever, FreeCell's foundation cards stay out of play, Aces
  can't slide between foundations for points, Eight Off and Forty Thieves
  move only as many cards at once as their free cells or empty columns
  allow, and a Spider game with too few cards left to deal ends. Canfield
  and Bakers Dozen let foundation cards come back down, Canfield counts
  its base card in the score, and Forty Thieves is scored as AisleRiot
  scores it and can send a whole run up in one move.
- Statistics are only shared when AisleRiot is there, as its keyfile or
  its `sol` program, and not just because there's a `gnome-games` folder,
  which other GNOME games keep too.
- `--reset-stats` only says the statistics are shared with GNOME
  AisleRiot when AisleRiot has a record of one of these games to clear,
  and then says `1 game`, not `1 game(s)`.
- Double-clicking a foundation sends up every card that can go.
- In Golf, Triple Peaks and Scorpion, an `f` or a double-click that does
  nothing says why, as those games have no foundations. Text mode's `f`
  does too.
- The mouse: a slow click picks a card up instead of undoing itself, a
  double-click at a normal speed counts, moving the pointer doesn't move
  the cursor, a click on the menu doesn't click the new board as well, and
  the banner only takes a left click on a choice.
- The keys: Esc acts at once, and Alt with a key is no longer read as Esc
  and then the key. Help and statistics stay up until a key is pressed,
  boss mode stays up when the mouse moves or the window is resized, and
  game keys do nothing while the terminal is too small to show the board.
- Hints name cards as the board draws them and no longer tell you to deal
  when you can't, the Spider summary no longer claims that builds must
  follow suit, and the status line catches up after undo and redo.
- Picking up a run names its card as the board draws it and says
  `2 cards`, not `2 card(s)`.
- A card dealt from the stock clears the line saying why the move before
  it did nothing.
- `*** YOU WIN! ***` shows in full on an 80-column status line in every
  game, code skin too, where a long status used to cut it off.
- The full-screen game starts on terminals that can't hide the cursor, and
  draws plain cards when the locale can't show the suit symbols.
- Text mode lines the cards up under their tags, times each deal on its
  own clock, counts a game left unfinished from a pipe as lost, uses
  letter suits when the output can't show the symbols, and leaves quietly
  on Ctrl-C or when piped into `head`. Its boss screen hides the board
  properly, with paths that fit the platform.
- Soliterm starts on Klondike when the game played last no longer exists.

### Removed

- The `aisle` command and the aisle-cli package. `soliterm` replaces them.
- Python 3.8. Soliterm needs Python 3.9 or newer.

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

[Unreleased]: https://github.com/bwenstar/soliterm/compare/ddab8952d7abbac919a35409eb7096e55a07f016...HEAD
