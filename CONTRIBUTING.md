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
python -m pip install pytest coverage ruff==0.16.6 vermin==1.8.0 build twine
python -m pip install mypy==2.3.1   # needs Python 3.10 or newer
```

mypy 2.3.1 won't install on Python 3.9, so on 3.9 skip that last line and
leave the type check to CI.

Those tools are the `dev` group in `pyproject.toml`, so with pip 25.1 or
newer `python -m pip install -e . --group dev` installs the lot, and with uv
`uv sync --group dev` does the whole setup in one step. Either way, mypy is
left out on 3.9.

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

The whole suite takes under a minute. pytest imports the package straight
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

vermin makes sure nothing newer than Python 3.9 has crept into `src/`,
with a gap: neither it nor mypy (which checks against 3.10) sees an
`X | Y` type that is evaluated when the code runs, such as a type alias
at module level or the argument to `cast()`. Only running the tests on
3.9, as CI does, catches those, so write them with `Optional` or `Union`.
In annotations `X | Y` is fine, as long as the file has
`from __future__ import annotations`.

In CI the formatter runs as `ruff format --check .`, which only reports
what it would change.

ruff, mypy and vermin are pinned to the same versions in the install lines
above, in the `dev` group and in CI, so a new release can't turn the checks
red on its own. When you move one of them up, change it in all three, and
for ruff in `.pre-commit-config.yaml` too.

If you use [pre-commit](https://pre-commit.com), `pip install pre-commit`
and then `pre-commit install` will run the whitespace fixers, the YAML and
TOML checks and ruff on every commit.

The commit that first formatted the whole tree is listed in
`.git-blame-ignore-revs`. GitHub skips it in its blame view; to have
`git blame` skip it as well, run this once in your clone:

```sh
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

With that set, `git blame` fails on a checkout from before the file
existed. If you look at old tags a lot, pass it for one run instead:
`git blame --ignore-revs-file .git-blame-ignore-revs FILE`.

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

[docs/adding-a-game.md](docs/adding-a-game.md) walks through adding one,
with a worked example. In short:

1. Write `src/soliterm/engine/games/<key>.py`, a subclass of `GameDef`
   that plays the game by AisleRiot's rules.
2. Add it to `GAMES` and `GAME_ORDER` in
   `src/soliterm/engine/games/__init__.py`, and import it in
   `src/soliterm/engine/__init__.py` and add it to `__all__` there.
3. If AisleRiot has the game, map the key to AisleRiot's section for it
   in `GAME_TO_SECTION` in `src/soliterm/aisleriot.py`, and add the pair
   to `NEW_SECTIONS` in `tests/test_aisleriot_sync.py`.
4. Add its number of cards to `EXPECTED_CARDS` in `tests/helpers.py`, and
   if it has no foundations, or ones that only take a whole suit, its key
   to the list in `test_finish_scores_like_the_moves_one_by_one`. Then
   `python -m pytest tests/test_conformance.py -k <key>` runs it through
   the rules every game keeps.
5. Once the deal is final, pin deals 1 and 2 in `DEALS` in
   `tests/test_conformance.py`.
6. Write `tests/test_<key>.py` for the rules that are the game's own.
7. Write `docs/games/<key>.md`, add a row to the tables in
   `docs/games/README.md` and `README.md`, give it an entry under GAMES in
   `man/soliterm.6` and a place in the Game list of
   `.github/ISSUE_TEMPLATE/bug_report.yml`, bring the number of games up
   to date wherever it's given, and add a line to the changelog.

## The key reference

`docs/keybindings.md` is written by `tools/keybindings.py`, from `KEYMAP`
in `src/soliterm/tui/keys.py` and the text-mode help. When you change a
key, run

```sh
python tools/keybindings.py
```

and commit the page along with the change. The tests fail until you do.
The keys of the other screens, such as the menu and the end banner, are
written out in the script itself, so change them there.

## Screenshots

The screenshots in the README come from `tools/screenshots.py`:

```sh
python tools/screenshots.py
```

It needs tmux 3.0 or newer, Pillow and the DejaVu Sans Mono font. Those
are only for this script and the game never uses them, so they aren't in
the dev group. If your change alters what's on screen, regenerate the
screenshots and commit them with it.

`--list` shows the scenes and `--scene NAME` redraws only the ones you
name. The scenes are a list near the top of the script: a deal and the
keys to press, so changing what a shot shows usually means editing a line
or two there. A new scene's picture goes in the README too: the tests
check that the README shows every picture the scenes draw. `--out DIR`
writes somewhere other than `docs/img/`, which is handy for checking a
change before you overwrite the real ones.

Two scenes play a whole game: the hero GIF plays Klondike to the finish,
and `win` plays Golf to the end banner. `tests/test_tui_play.py` presses
every scene's keys on a board the size of the scenes' terminal and checks
each still gets to its last shot, so a change to the hints or the layout
that throws them off fails the suite before it spoils a screenshot.

## Questions

Ask in [GitHub Discussions](https://github.com/bwenstar/soliterm/discussions).
Issues are for bugs and feature requests, and security problems go through
the process in [SECURITY.md](SECURITY.md).

By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md).
