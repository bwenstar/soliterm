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
