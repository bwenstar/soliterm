# What stays the same

People pass deals around, drive text mode from scripts and keep years of
statistics in Soliterm's files, so some things stay the same from one
release to the next. This page says which, and what happens to your
files if you go back to an older version. Unless it says otherwise, all
of it holds through every 1.x release.

## Deals

- **Deal numbers.** Deal N of a game is the same cards in every release,
  on every computer and every Python. Numbers run from 0 to 2147483647.
  An option that doesn't change the deck doesn't change the deal either,
  so Klondike deal 5 is the same cards drawing one or three. Only
  Spider's suits change the deck, and so only they change the deal.
  FreeCell's numbers are Microsoft FreeCell's.
- **Share codes.** A code is the game's key, the options that aren't the
  standard ones, and the number, as in `klondike:d3:48213`, read the way
  [`deals.py`](../src/soliterm/deals.py) reads it. Every code a release
  has printed keeps working in the ones after it. A new option can add
  letters to a code, and a code without them means the standard setting,
  as it did before.
- **The daily deal** is deal YYYYMMDD with the standard options, 20260924
  on 2026-09-24, so `klondike:20260924` is that day's daily for good.

The tests pin a hash of deals of every game, as 1.0.0 dealt them, so a
change that would deal different cards fails straight away.

## Names and numbers

- **Game keys**, such as `klondike` and `triplepeaks`: the names `--list`
  prints and `--game` takes. They're in the share codes and in every file
  below, and every game but FreeCell seeds its shuffle with its key,
  through `stream_of` in [`engine/rng.py`](../src/soliterm/engine/rng.py),
  so a key can never be renamed.
- **Slot ids**, the numbers in text mode's tags, which its commands take
  and saves store. A game keeps its slots, in the order it has them.
- **AisleRiot's section names**, `GAME_TO_SECTION` in
  [`aisleriot.py`](../src/soliterm/aisleriot.py), as `[eight_off.scm]`
  for Eight Off, so the statistics stay shared.

## The command line

Options can be added, but none is taken away or given another meaning.
That goes for `--seed` as well, aisle-cli's name for `--deal`, which
`--help` doesn't show but still works. The exit statuses in the man page
keep their meanings too.

## Text mode

[text-mode.md](text-mode.md) has all of it. A script can rely on:

- the commands `h` lists, what they do, and the other spellings they
  take: `print`, `deal`, `auto`, `click`, `dc`, `found`, `undo`, `redo`,
  `new`, `quit` and `exit`. A comma does for the space in a move, and
  upper and lower case are the same, bar `n` and `N`;
- the first line, which names the game and then `Deal 216`, or
  `Daily 2026-09-24` for a daily, as in
  `Soliterm - Golf - Deal 216 (text mode). Type h for help.`;
- the tags on the board, `stk#0`, `wst#1`, `fnd#2`, `cel#0`, `rsv#6` and
  a bare `#9` for a tableau column, and the cards under them: `[ 8D]`
  face up (with `--ascii`), `[###]` face down and `[   ]` for none;
- the status line that ends each board, `score=0 moves=0 |` and then the
  game's own words, with `*** YOU WIN! ***` on the end of a win;
- the end of a hint, `(type: 12 2)` or `(type: d)`, the command to type;
- `Share code: golf:216` on a win.

The rest is for people and can change: the wording of hints and other
messages, the game's words in the status line, and where the slots sit on
the board.

## The files

They're JSON, and each release reads what the ones before it wrote. A
later 1.x can add keys, but the ones here keep their meaning, so 1.0.1
can always read what a newer release writes.

| File | What's in it |
| --- | --- |
| `config.json` | `last_game`, `options` (each game's, by key), `symbols`, `sync_aisleriot` and `merged_into_aisleriot`, and once they've been set, `color`, `theme`, `four_color`, `code_skin`, `camo_theme`, `view`, `animation` and `migrated_from` |
| `stats.json` | a record for each game key, with `wins`, `total`, `best` and `worst` (in seconds, 0 for none), and `_meta`, with the marker for the one-time merge into AisleRiot's record and the games still to be shared |
| `history.jsonl` | a line for each game: `at`, `game`, `options`, `deal`, `result` (`won` or `lost`), `seconds`, `moves` and `score`, and `daily` for a daily |
| `saves/<game>.json` | `format`, `version`, `saved` and `seconds`, then `game`, `options`, `deal`, `daily`, `chosen`, `moves`, `score`, `position`, `undo` and `redo` |

1.0.0 and 1.0.1 write the same keys, and saves in format 1. They save
config.json differently, though: 1.0.0 writes every setting it has each
time it saves one, 1.0.1 only the one that changed, and a setting that
isn't in the file is its default.

## Going back to an older version

- **config.json.** From 1.0.1 on, saving a setting changes only that
  key, so the rest of the file stays as it is, keys from a newer version
  included. 1.0.0 writes its whole copy of the settings, as the
  full-screen game does whenever it starts a game, and that copy leaves
  out every key it doesn't know and puts the default back for a value it
  can't use, such as a `last_game` it doesn't have. It keeps `options`
  whole, other games' included, and any `theme` name.
- **stats.json.** Every version keeps the records of games it doesn't
  have as they are, and anything in `_meta` it doesn't know. The record of
  a game it counts is written with the four numbers alone.
- **history.jsonl** is only ever added to. A line from a newer version is
  a game as long as its `at`, `game`, `result`, `seconds` and `moves` are
  as above, and the fields it doesn't know are passed over. A game it
  doesn't have shows in `--stats` by its key. A line that isn't a game,
  with a `result` other than `won` or `lost`, say, is skipped and stays in
  the file.
- **Saves.** A save carries a format, 1 so far, and a version that saves
  something an older one would misread gives it a higher one. A save in
  a format above a version's own is left where it is, with a note saying
  so, and while it waits, a game of that kind left unfinished there
  counts as lost, since there's no room to keep it. A save in its own
  format with fields it doesn't know is picked up as usual, and those
  fields are gone once the game is saved again.

## What isn't promised

- **The screen**: the full-screen game's layout, its colours and themes,
  and the words it uses.
- **The keys.** One can move or do something else in any release, and
  the changelog says so when it does.
- **The hint's choice.** Which move a hint picks can change as the hints
  get better. It's always a legal one.
- **The Python API.** Soliterm is a game first, and its modules are
  provisional: any of them can change or go in any release. The command
  line and text mode are the parts to build on.
