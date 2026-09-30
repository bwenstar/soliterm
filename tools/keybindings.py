#!/usr/bin/env python3
"""Write docs/keybindings.md from the key tables in the code.

  python tools/keybindings.py          # rewrite docs/keybindings.md
  python tools/keybindings.py --check  # only say whether it's up to date

The board's keys and boss mode come from KEYMAP in src/soliterm/tui/keys.py,
the keys that work on a terminal too small for the board from
SMALL_SCREEN_ACTIONS in src/soliterm/tui/app.py, and the text-mode commands
from TEXT_HELP in src/soliterm/textmode.py. So a key added there shows up
here by running this again, and tests/test_keybindings_doc.py fails until
someone does.

The other screens read their keys one screen at a time in screens.py, with
nothing to generate them from, so they and the mouse are written out by
hand in OTHER_SCREENS and MOUSE below. When one of those screens changes,
change the text here and run the script.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import curses  # noqa: E402

from soliterm.textmode import TEXT_HELP  # noqa: E402
from soliterm.tui.app import SMALL_SCREEN_ACTIONS  # noqa: E402
from soliterm.tui.keys import KEYMAP, Binding  # noqa: E402

DOC = ROOT / "docs" / "keybindings.md"

# what the page calls the keys that aren't a character of their own
NAMES = {
    curses.KEY_UP: "Up",
    curses.KEY_DOWN: "Down",
    curses.KEY_LEFT: "Left",
    curses.KEY_RIGHT: "Right",
    curses.KEY_ENTER: "Enter",
    10: "Enter",
    13: "Enter",
    ord(" "): "Space",
    27: "Esc",
    ord("\t"): "Tab",
    curses.KEY_F2: "F2",
}
# events rather than keys: the mouse is described on its own, and a resize
# only draws the screen again
NOT_KEYS = (curses.KEY_MOUSE, curses.KEY_RESIZE)

INTRO = """\
# Keys

<!-- Written by tools/keybindings.py. Edit that, not this file, and run
     python tools/keybindings.py to bring this page up to date. -->

Everything in Soliterm is a key or two away, and most of it is a click
away too. On the board, `?` shows the same keys as the first table here.
This page also has the other screens, the mouse and text mode.
"""

OTHER_SCREENS = """\
## The other screens

The boss key (`b`, `B` or `F2`) works on every screen. The one exception
is the Play a deal box, where `b` could be part of what you're typing, so
only `F2` works there.

### The menu

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move up and down the list |
| `PgUp` / `PgDn` | move a page up or down |
| `Home` / `End` | go to the first game or to Quit |
| `Enter` | play the game, or open Daily deal, Play a deal or View statistics |
| `q`, `Q` | quit |

A game with a save waiting says so on its row, and picking it carries on
where you left off.

In a terminal too short for every game, the games scroll, and a line
above or below them says how many more there are that way. Daily deal,
Play a deal, View statistics and Quit stay where they are under them.

### Daily deals

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move up and down the games |
| `PgUp` / `PgDn` | move a page up or down |
| `Home` / `End` | go to the first or the last game |
| `Enter` | play that game's daily deal |
| `Esc`, `q`, `Q` | back to the menu |

The games scroll here too when the terminal is too short for them all.

### Play a deal

`g` opens this box during a game, and so does Play a deal on the menu.

| Keys | What they do |
| --- | --- |
| typing | a deal number or a share code, up to 64 characters |
| `Backspace` | take the last character off |
| `Ctrl-U` | clear the line |
| `Enter` | play it, or go back if nothing is typed |
| `Esc` | go back |

A number on its own plays that deal of the game in play, with the options
it has now. From the menu, it plays that deal of the game you played last.
A board's whole title line, pasted in, works as well.

### Options

`o` opens the options of the game in play, for the games that have any.

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move between the options |
| `Left`, `Right`, `Space` | change the one you're on |
| `Enter`, `q`, `Q` | keep the changes and deal again with them |
| `Esc` | leave everything as it was |

### Statistics

The game in play is picked out, or the first game when they're opened
from the menu, and the games scroll as they do on the menu.

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move up and down the games |
| `PgUp` / `PgDn` | move a page up or down |
| `Home` / `End` | go to the first or the last game |
| any other key | close the statistics |

The mouse doesn't close them, so the pointer passing over the window
can't.

### Help

Any key closes it. In a terminal too short for it all, it scrolls
instead with the keys that move up and down the statistics, and a line
above or below says how many more there are that way. Any other key
closes it then. The mouse doesn't, so the pointer passing over the
window can't.

### Leaving a game under way

When `g` or a change of options would end a game you've started, Soliterm
asks first, since the game would count as lost.

| Keys | What they do |
| --- | --- |
| `y`, `Y` | yes: count it as lost and go on |
| `n`, `N`, `Esc`, `q`, `Q`, `Enter` | no: keep playing |

Enter says no, so one Enter too many can't give a game away.

### The end of a game

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move between the choices |
| `Enter`, `Space` | take the choice you're on |
| `u`, `U` | undo the last move (when no moves are left, not after a win) |
| `s`, `S` | replay this deal |
| `n`, `N` | a new deal |
| `m`, `M`, `q`, `Q` | back to the menu |

A left click on a choice takes it.

### The finish and the win

When `a` sends the last cards up one at a time, or the cards bounce off
the board after a win, any key or a left click skips the rest. The boss
key skips it too and hides the screen straight away.
"""

MOUSE = """\
## The mouse

Soliterm listens to the left button and the wheel. The pointer moving
over the window does nothing, and the wheel does nothing on the board.

- Click a card to pick it up, along with every card below it, then click
  where it should go. Click the same pile again to put it back. In Golf
  and Triple Peaks, a click on a card that goes on the waste plays it
  there instead.
- Click the stock to deal.
- Or press on a card, drag and let go over another pile.
- Double-click a card to send it up to its foundation, or double-click the
  stock to deal. In Golf and Triple Peaks it plays the card to the waste,
  just the one, as a click does.
  Two clicks on the same pile within 0.4 seconds count as a double-click.
  Some games do more with a double-click, and each game's page in
  [docs/games](games/README.md) says what.
- On the menu, the daily deals and the end of a game, click a row to pick
  it. On the statistics, a click picks out a game's row.
- On the menu, the daily deals and the statistics, the wheel moves up and
  down the list, and it scrolls the help where the help is too long for
  the terminal. Where they scroll, a click on the line saying how many
  more there are moves a page that way.

A terminal has to pass mouse clicks on for any of this to work. Most do,
and in tmux it takes `set -g mouse on`.
"""


def key_name(code: int) -> str:
    """How the page writes one key."""
    return NAMES.get(code) or chr(code)


def keys_of(binding: Binding) -> list[str]:
    """The binding's keys as the page writes them, each once, in order."""
    names: list[str] = []
    for code in binding.actions:
        if code in NOT_KEYS:
            continue
        name = key_name(code)
        if name not in names:
            names.append(name)
    return names


def cell(text: str) -> str:
    """Text for a table cell: one line, with any | kept out of the table."""
    return " ".join(text.split()).replace("|", "\\|")


def key_table(bindings: list[Binding]) -> str:
    rows = ["| Keys | What they do |", "| --- | --- |"]
    for b in bindings:
        names = keys_of(b)
        # the mouse bindings have no keys, only a gesture
        keys = ", ".join(f"`{name}`" for name in names) if names else b.label.lower()
        rows.append(f"| {keys} | {cell(b.text)} |")
    return "\n".join(rows) + "\n"


def board_section() -> str:
    listed = [b for b in KEYMAP if b.label and b.mode == "play"]
    return (
        "## On the board\n\n"
        + key_table(listed)
        + "\n"
        + paragraph(
            "`k`, `j` and `l` move up, down and right, as they do in vi. vi's"
            " `h` for left is the hint here, so left has only its arrow key."
        )
        + "\n"
        + paragraph(
            "In Golf and Triple Peaks, which have no foundations,"
            f" {spoken(keys_for('select', 'foundation'))} play the card at the"
            " cursor onto the waste if it goes there."
        )
    )


def keys_for(*wanted: str) -> list[str]:
    """The keys on the board that run any of the actions `wanted`."""
    names: list[str] = []
    for b in KEYMAP:
        if b.mode != "play":
            continue
        for code, action in b.actions.items():
            name = f"`{key_name(code)}`"
            if action in wanted and code not in NOT_KEYS and name not in names:
                names.append(name)
    return names


def spoken(names: list[str], last: str = "and") -> str:
    """["a", "b", "c"] as "a, b and c"."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {last} {names[-1]}"


def paragraph(text: str) -> str:
    return textwrap.fill(" ".join(text.split()), 72) + "\n"


def boss_section() -> str:
    listed = [b for b in KEYMAP if b.label and b.mode == "boss"]
    boss = spoken(keys_for("boss"), "or")
    return (
        "### Boss mode\n\n"
        + paragraph(
            f"{boss} hides whatever is on screen behind something that looks like"
            " work, and the clock stops until you come back."
        )
        + "\n"
        + key_table(listed)
        + "\n"
        + paragraph("Moving the mouse or resizing the window doesn't bring the game back.")
    )


def small_section() -> str:
    works = spoken(keys_for(*SMALL_SCREEN_ACTIONS))
    resizers = spoken([keys_for(action)[0] for action in ("code_skin", "view")])
    return "### A terminal too small for the board\n\n" + paragraph(
        "Soliterm says how big the board needs the terminal to be, and until"
        f" it is, only {works} do anything, so no key can make a move you"
        f" can't see. {resizers} change the size the board needs, so they can"
        " bring it back. A menu or a dialog that doesn't fit takes only `q`"
        " and the boss key."
    )


def text_section() -> str:
    return (
        "## Text mode\n\n"
        "Text mode reads one command a line. `h` prints this list, and\n"
        "[text-mode.md](text-mode.md) has the rest.\n\n"
        "```text\n" + TEXT_HELP.strip("\n") + "\n```\n"
    )


def render() -> str:
    """The whole of docs/keybindings.md."""
    parts = [
        INTRO,
        board_section(),
        OTHER_SCREENS,
        boss_section(),
        small_section(),
        MOUSE,
        text_section(),
    ]
    return "\n".join(parts)


def is_current(path: Path | None = None) -> bool:
    """Whether the page at `path`, docs/keybindings.md by default, is as
    render() would write it now."""
    try:
        return (path or DOC).read_text(encoding="utf-8") == render()
    except FileNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the page is out of date, and write nothing"
    )
    args = parser.parse_args(argv)
    shown = DOC.relative_to(ROOT).as_posix()
    if args.check:
        if is_current():
            print(f"{shown} is up to date")
            return 0
        print(f"{shown} is out of date: run python tools/keybindings.py", file=sys.stderr)
        return 1
    DOC.parent.mkdir(parents=True, exist_ok=True)
    with open(DOC, "w", encoding="utf-8", newline="\n") as f:
        f.write(render())
    print(f"wrote {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
