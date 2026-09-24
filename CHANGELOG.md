# Changelog

## Unreleased

- The help screen no longer says every game builds its foundations up by
  suit, which isn't true of them all.
- A text-mode game won in one move says `1 move`, not `1 moves`.
- Games played while not sharing statistics, for a game this version
  doesn't have, are kept for the version that recorded them instead of
  being dropped.
- `--debug-info` prints what a bug report needs: the versions, the
  terminal, curses and where Soliterm keeps its files. It only reads, and
  leaves every file as it was.
- Every deal has a number, shown on the board, at the end of a game and in
  text mode. `--deal N` plays deal N, and `n` then deals the next one.
- Share codes such as `klondike:d3:48213` name a deal with its options.
  The end of a game shows its code, and `--deal` takes one, as do the new
  `g` key during a game and Play a deal on the menu.
- FreeCell deals are numbered as in Microsoft FreeCell.
- `--draw` and `--suits` set Klondike's draw or Spider's suits for one run
  without saving them.
- Deals come from Soliterm's own shuffle, not Python's, so a number deals
  the same cards on every Python. This means the numbers from 1.0.0 deal
  different cards now. `--seed` still works as another name for `--deal`.
- In the full-screen game, `--seed 5` (or `--deal 5`) without `--game`
  goes straight into the game played last instead of the menu, and only
  that first game is deal 5, not every game picked from the menu.
- A game you've started is kept for next time when you leave it with `q`,
  `m` or Ctrl-C, or close the terminal on it, instead of counting as lost.
  Its menu row reads `Resume your game: 0:42, 31 moves`, and picking it or
  starting it with `--game` carries on where you left off, while a chosen
  deal or option starts afresh and leaves it waiting. Text mode keeps
  games too, when you're typing at a terminal.
- SIGHUP and SIGTERM leave the way Ctrl-C does, so the game is kept, and
  the exit status is 130. One ignored already, as `nohup` ignores SIGHUP,
  stays ignored.
- Every game played here goes in `history.jsonl`, one line each. The
  statistics gain Streak and Longest columns, the win banner and text mode
  name a run of two or more wins, and `--stats` lists the last ten games.
- `--reset-stats` clears the history as well, keeping a copy in
  `history.jsonl.bak`, and leaves saved games alone.
- `a` finishes the game once every card left can go up, safe or not, as
  one move, and the message line says when that is.
- `U` and `R` undo and redo every move at once; `u` and `r` still take
  one. `U` used to be the same as `u`. `U` keeps the clock and redo,
  where `N` deals the hand again as a new game.
- Text mode: `undo all` and `redo all`, and `a` finishes too.
- The finish sends the cards up one at a time, and a win bounces them
  off the board. Any key skips either, the boss key still hides
  everything at once, and `--no-animation` or `"animation": false` in
  config.json turns them off.
- The win banner says when a win is your first of that game or a new
  best time.
- Themes for the full-screen game: `classic` (the look it always had),
  `dark`, `light` and `contrast`. `t` moves on to the next one and
  remembers it, and `--theme NAME` picks one for a single run.
- A four-colour deck with green clubs and orange diamonds (blue diamonds
  on terminals without 256 colours). `4` turns it on and off, and it's
  remembered too. A terminal without the colour pairs for it says so, and
  the choice is kept for one that has them.
- The code skin colours its source's keywords, strings and numbers as an
  editor would, in the theme's colours.
- A terminal with too few colour pairs for all of these draws the ones it
  has no room for in colours it does have.
- Three new games: Spiderette, Triple Peaks and Scorpion. Each shares its
  statistics with AisleRiot's own record of it, so any games of them
  you've played in AisleRiot show up straight away. Each has its page in
  `docs/games`.
- Triple Peaks has AisleRiot's multiplier scoring as an option.
- `--reset-stats` clears the new games too, in AisleRiot's keyfile as well
  when sharing.
- Spider's status line says `1 deal`, not `1 deals`.
- A daily deal for every game, from `--daily` or Daily deal on the menu:
  the same cards for everyone that day, with the standard options. When
  it ends there's a line to share that names no cards. It works offline.
- A daily left unfinished is kept like any other game, and its menu row
  says it's a daily. That day's daily carries on with it, and `--stats`
  marks the games that were dailies.
- A kept game takes its newest 500 undo steps with it, and `U` on a
  longer one says it stopped at the oldest move saved, as does text
  mode's `undo all`.
- `*** YOU WIN! ***` shows in full on an 80-column status line in every
  game, code skin too, where a long status used to cut it off.
- Picking up a run names its card as the board draws it and says
  `2 cards`, not `2 card(s)`.
- In Golf, Triple Peaks and Scorpion, an `f` or a double-click that does
  nothing says why, as those games have no foundations. Text mode's `f`
  does too.
- `--reset-stats` only says the statistics are shared with GNOME
  AisleRiot when AisleRiot has a record of one of these games to clear,
  and then says `1 game`, not `1 game(s)`.
- A card dealt from the stock clears the line saying why the move before
  it did nothing.
- A game kept waiting while another copy of Soliterm finishes with the
  statistics says so, instead of stopping without a word. If Ctrl-C cuts
  leaving short while it waits, a note at exit says the game was neither
  saved nor counted.

## 1.0.0 - 2026-06-29

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
