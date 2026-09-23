# Contributing to Soliterm

Thanks for wanting to help. Bug reports, fixes, new games and corrections to
the docs are all welcome. If you're planning something bigger than a bug fix,
open an issue or start a discussion first so we can agree on the shape of it
before you spend an evening on it.

## Getting set up

You need Python 3.9 or newer and git.

```sh
git clone https://github.com/bwenstar/soliterm.git
cd soliterm
python -m venv .venv
. .venv/bin/activate              # on Windows: .venv\Scripts\activate
python -m pip install -e .
python -m pip install pytest coverage ruff mypy vermin build
```

Those tools are the `dev` group in `pyproject.toml`, so with pip 25.1 or
newer `python -m pip install -e . --group dev` installs the lot. If you use
uv, `uv sync --group dev` does the whole setup in one step.

The game reads and writes your real statistics, and GNOME AisleRiot's too if
you have it installed. When you try out a change by hand, give it a throwaway
home so a half-finished branch can't touch them:

```sh
tmp=$(mktemp -d)
HOME=$tmp XDG_CONFIG_HOME=$tmp/.config XDG_DATA_HOME=$tmp/.local/share soliterm
```

## Running the tests

```sh
python -m pytest
```

The whole suite takes a few seconds. pytest imports the package straight
from `src/`, so the tests work even without the editable install. To run
part of it, name a file or use `-k`:

```sh
python -m pytest tests/test_spider.py
python -m pytest -k undo
```

For a coverage report, `python -m coverage run -m pytest` and then
`python -m coverage report`.

## Lint and type checks

CI runs all of these, so it saves a round trip to run them before you push:

```sh
ruff check .
ruff format .
mypy src
vermin -t=3.9- --no-tips --violations --eval-annotations src
```

vermin makes sure nothing newer than Python 3.9 has crept into `src/`.

If you use [pre-commit](https://pre-commit.com), `pip install pre-commit`
and then `pre-commit install` will run the whitespace fixers, the YAML and
TOML checks and ruff on every commit.

## Building

```sh
python tools/build_pyz.py           # dist/soliterm.pyz
python tools/build_pyz.py --wheel   # plus a wheel and an sdist
```

The zipapp builds with the standard library alone. `--wheel` runs
`python -m build`, so it needs `build` installed. Either way `dist/` is
emptied first.

## House rules

**The runtime stays standard library only.** Soliterm has to run from a
single `.pyz` file with nothing else installed, so code under `src/soliterm`
may only import the standard library. The one exception is windows-curses
on Windows, because CPython doesn't ship curses there. Tools you only need
while developing are fine; add them to the `dev` group.

**Every bug fix comes with a test that fails without it.** Write the test
first, watch it fail, then fix the bug. That way we know the test really
covers the bug and it can't quietly come back.

**Tests never touch the real home directory.** `tests/conftest.py` has an
autouse fixture, `isolated_home`, that runs before every test. It points
`HOME`, `USERPROFILE`, `XDG_CONFIG_HOME` and `XDG_DATA_HOME` into the test's
own `tmp_path` and fakes `USER` and `LOGNAME`. The store and the AisleRiot
code look up their paths each time they're called, so every test starts
with an empty home: no config, no stats and no AisleRiot. To keep it that
way, don't work these paths out once at import time, and don't write to
fixed paths in tests. When a test needs AisleRiot to be installed, use the
`keyfile` fixture, which writes a fake keyfile into the test's home.
`tests/test_isolation.py` checks the fixture itself.

**Keep commits small and focused.** One change per commit, with a subject
line that says what it does. A refactor and the fix it makes room for go in
separate commits. That keeps review easy and makes `git bisect` useful.

## Adding a game

Each game is one module in `src/soliterm/engine/games/`.

1. Create `src/soliterm/engine/games/<key>.py` with a subclass of `GameDef`
   from `soliterm.engine.gamedef`. Set `key`, `name` and `blurb`, then fill
   in the callbacks the game needs: at least `deal`, `can_pickup`,
   `can_drop` and `is_won`, and usually `on_click`, `autoplay`, `status`
   and options as well. The existing games are the best reference;
   `golf.py` and `freecell.py` are short ones to start from.
2. Register it in `src/soliterm/engine/games/__init__.py` by adding the
   class to `GAMES` and its key to `GAME_ORDER`, which is the order of the
   menu and of `--list`.
3. If GNOME AisleRiot has the game, add an entry to `GAME_TO_SECTION` in
   `src/soliterm/aisleriot.py` that maps your key to AisleRiot's section
   name, so the statistics are shared. If AisleRiot doesn't have it, leave
   it out and the stats stay in Soliterm's own file.
4. Add the number of cards in a full deal to `EXPECTED_CARDS` in
   `tests/helpers.py`. After that, `tests/test_conformance.py` picks the
   game up by itself and runs it, with every combination of its options,
   through the rules every game has to follow: the deal has every card,
   a seed always deals the same hand, random play never loses a card,
   undo and redo replay exactly, every hint is a legal move, and so on.
   The other tests that loop over `GAME_ORDER` cover it too. Add a test
   file of your own for the rules that are particular to the game.
5. Add a row to the games table in `README.md`.

## Screenshots

The screenshots in the README come from `tools/screenshots.py`:

```sh
python tools/screenshots.py
```

It needs tmux and Pillow. Those are only for this script and the game
never uses them, so they aren't in the dev group. If your change alters
what's on screen, regenerate the screenshots and commit them with it.

## Questions

Ask in [GitHub Discussions](https://github.com/bwenstar/soliterm/discussions).
Issues are for bugs and feature requests, and security problems go through
the process in [SECURITY.md](SECURITY.md).

By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md).
