# AisleRiot CLI

A dependency-free, terminal Solitaire collection, a command-line replica of
GNOME **AisleRiot** (the `/usr/games/sol` game). Pure Python 3, no third-party
packages. Plays nine games with a curses TUI (keyboard **and** mouse) or a
pipe-friendly text mode, and **shares its statistics with the installed GNOME
AisleRiot** so games played in either program are mirrored in both.

Needs only **Python 3.9+** (with the standard-library `curses`, which ships
with Python on Linux and macOS). No `pip install` of anything else required.

## Install / run

Pick whichever suits you:

**A. Zero install, single file.** Grab `soliterm.pyz` and run it:

```sh
python3 soliterm.pyz              # menu → pick a game (curses TUI)
./soliterm.pyz --game freecell    # or run it directly (it's executable)
```

**B. Install with pip** (gives you a `soliterm` command on your PATH):

```sh
pip install .                      # from a checkout
soliterm                           # then just run "soliterm"
```

**C. From source** (no install):

```sh
PYTHONPATH=src python3 -m soliterm
```

Common flags (all three forms): `--game NAME`, `--seed N`, `--list`,
`--stats`, `--text` (force text mode), `--ascii`, `--color` / `--no-color`.

## Build the distributables

```sh
python3 tools/build_pyz.py           # dist/soliterm.pyz, the single-file zipapp
python3 tools/build_pyz.py --wheel   # plus a wheel and an sdist in dist/
```

The zipapp builds with the standard library alone. `--wheel` runs
`python -m build`, so it needs `pip install build` first.

## Games

| Key | Game | Notes |
|-----|------|-------|
| `klondike` | Klondike | the classic; draw 1 or 3 (option) |
| `spider` | Spider | 4 suits, or 2 or 1 (option) |
| `freecell` | FreeCell | four free cells, supermoves |
| `eightoff` | Eight Off | eight cells, build by suit |
| `golf` | Golf | clear the tableau onto the waste |
| `yukon` | Yukon | move any face-up group |
| `bakersdozen` | Bakers Dozen | no stock, thirteen columns |
| `fortythieves` | Forty Thieves | two decks, ten columns |
| `canfield` | Canfield | reserve + deal-three, wrapping |

## Controls (TUI)

| Keys | Action |
|------|--------|
| Arrow keys | move the cursor between piles |
| Enter / Space | pick up the cursor's run; press again to drop |
| Mouse click | pick up a card/run; click a target to drop |
| click mid-stack | split a pile and lift from that card down |
| double-click | send a card to a foundation (or deal, on the stock) |
| `d` | deal from the stock |
| `a` | autoplay safe cards to the foundations |
| `f` | send the selected/cursor card to a foundation |
| `h` | hint: highlight a legal move |
| `n` / `N` | new deal / restart **this** deal |
| `u` / `r` | undo / redo |
| `o` | game options · `s` statistics · `v` toggle colour |
| `c` | code skin (keep playing inside a fake source file) |
| `b` / F2 | boss mode (hide the game behind fake "work" output) |
| `m` / `q` | back to menu / quit · `?` help |

## Text mode

`--text` (or any non-TTY / piped stdin) runs a scriptable REPL. It is also
what you get, with a line on stderr saying why, when curses can't run: no
`curses` module (on Windows, `pip install windows-curses` adds one) or a
`TERM` that is unset, `dumb` or unknown here. Slots are addressed by the
`#N` tags shown on the board:

```
d                deal           a       autoplay
<src> <dst>      move a run     u / r   undo / redo
<src> <dst> <n>  move n cards   hint    suggest a move
f <slot>         to foundation  n       new deal     q  quit
```

## Statistics & AisleRiot sharing

Statistics use AisleRiot's own model: **Wins / Total / Percentage / Best &
Worst winning time**, per game. When the installed GNOME AisleRiot is present,
this game reads from and writes to its config keyfile
(`~/.config/gnome-games/aisleriot`), so a game finished here shows up in
AisleRiot's Statistics dialog and vice versa. Disable by setting
`"sync_aisleriot": false` in `~/.config/soliterm/config.json`, or for a
single run with `--no-sync` (or `SOLITERM_NO_AISLERIOT=1` in the
environment): the keyfile is then neither read nor written, and the games
you play wait in the local stats until sharing is on again.

`--stats` prints the table; `--reset-stats` clears it, and that includes
AisleRiot's own record of these nine games (its other games are left
untouched). It asks you to type `yes` first, or takes `--yes` when there is
no terminal to ask on, and keeps a copy of what it clears in
`aisleriot.soliterm-bak` next to the keyfile and `stats.json.bak` next to
the local stats.

## Options

```
--game NAME     start a specific game        --seed N    reproducible deal
--text          force text mode              --ascii     letter suits S/H/D/C
--color         force colour in text mode    --no-color  disable colour
--list          list games and exit          --stats     print statistics
--reset-stats   clear statistics             --yes       don't ask first
--no-sync       leave AisleRiot's stats alone this run
```

Colour, code-skin, and other preferences persist in
`~/.config/soliterm/config.json`. Respects `NO_COLOR`. Statistics are in
`~/.local/share/soliterm/stats.json`. If you played the game under its old
name, the first run copies `config.json` and `stats.json` over from the
`aisle-cli` folders and leaves the old ones where they are.

## Tests

```sh
python3 -m pytest
```

The tests in `tests/` need pytest (the game itself doesn't). They cover the
engine, all nine games' rules, scoring, undo / redo, the hint, statistics
persistence, AisleRiot sharing, and the camouflage / code-skin / colour
features. They run against temporary config directories and never touch your
real AisleRiot data.
