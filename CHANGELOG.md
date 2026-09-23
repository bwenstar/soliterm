# Changelog

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
