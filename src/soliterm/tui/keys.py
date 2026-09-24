"""soliterm.tui.keys - what every key does on the play screen.

KEYMAP is the one table of key bindings. App looks each key up in it to find
the handler to run, and the help screen is written from it, so a key can't be
wired up in one place and forgotten in the other.
"""

from __future__ import annotations

import curses
from collections.abc import Iterable
from typing import NamedTuple


class Binding(NamedTuple):
    """One entry on the help screen and the keys behind it."""

    label: str                # the keys as the help screen names them
    text: str                 # what they do; each "\n" starts another help line
    actions: dict[int, str]   # key code -> action, run as App.do_<action>()
    compact: bool = False     # listed several to a line at the foot of the help
    mode: str = "play"        # the screen the keys work on: "play" or "boss"


def bind(keys: Iterable[str | int], action: str, label: str, text: str,
         **kw) -> Binding:
    """A Binding where every key in `keys` (characters or key codes) does
    the same action."""
    codes = [ord(k) if isinstance(k, str) else k for k in keys]
    return Binding(label, text, dict.fromkeys(codes, action), **kw)


KEYMAP: tuple[Binding, ...] = (
    # h is taken by the hint, so the vi-style keys stop at k, j and l
    Binding("Arrow keys, k j l",
            "move between the slots (k up, j down, l right)",
            {curses.KEY_UP: "up", ord("k"): "up",
             curses.KEY_DOWN: "down", ord("j"): "down",
             curses.KEY_LEFT: "left",
             curses.KEY_RIGHT: "right", ord("l"): "right"}),
    bind((curses.KEY_ENTER, 10, 13, " "), "select", "Enter / Space",
         "pick up the cursor's run; press again to drop"),
    Binding("+ / -", "lift one card more / fewer while holding a run",
            {ord("+"): "lift_more", ord("-"): "lift_fewer"}),
    bind((curses.KEY_MOUSE,), "mouse", "Mouse click",
         "click a card to pick it up, then a target to drop;\n"
         "click one mid-stack to lift it and all below it."),
    # a gesture the mouse handler tells apart itself, so no keys of its own
    Binding("Mouse double-click", "send a card to a foundation; deal on stock", {}),
    bind((27,), "cancel", "Esc", "cancel the current selection / clear hint"),
    bind("dD", "deal", "d", "deal from the stock (where applicable)"),
    bind("aA", "autoplay", "a", "autoplay safe cards to the foundations"),
    bind("fF", "foundation", "f", "send the selected/cursor card to a foundation"),
    bind("hH", "hint", "h", "show a hint (highlights a legal move)"),
    bind(("b", "B", curses.KEY_F2), "boss", "b / F2",
         "boss mode: hide any screen behind 'work'"),
    bind("\t", "next_disguise", "Tab (boss mode)",
         "cycle the disguise; any other key goes back", mode="boss"),
    bind("cC", "code_skin", "c", "code skin: keep playing inside a code file"),
    bind("vV", "color", "v", "toggle colour on / off (monochrome)"),
    bind("xX", "view", "x", "toggle view: full cards <-> compact cells"),
    bind("n", "new_deal", "n", "new deal", compact=True),
    bind("N", "restart", "N", "restart this deal", compact=True),
    bind("uU", "undo", "u", "undo", compact=True),
    bind("rR", "redo", "r", "redo", compact=True),
    bind("oO", "options", "o", "options", compact=True),
    bind("sS", "stats", "s", "statistics", compact=True),
    bind("?", "help", "?", "help", compact=True),
    bind("mM", "menu", "m", "menu", compact=True),
    bind("qQ", "quit", "q", "quit", compact=True),
    # a resized terminal only needs a fresh frame; nothing to list in the help
    bind((curses.KEY_RESIZE,), "redraw", "", ""),
)


def actions(mode: str = "play") -> dict[int, str]:
    """Key code -> action for the keys that work on the given screen."""
    table: dict[int, str] = {}
    for b in KEYMAP:
        if b.mode == mode:
            table.update(b.actions)
    return table


PLAY_ACTIONS = actions("play")
BOSS_ACTIONS = actions("boss")

HELP_KEY_W = 20     # the help's key column, gap before the text included
HELP_PACK_W = 60    # how wide a line of compact entries may get


def help_lines() -> list[str]:
    """The key list on the help screen, one entry per line and the compact
    ones packed together at the end."""
    lines: list[str] = []
    packed: list[str] = []
    for b in KEYMAP:
        if not b.label:
            continue
        if b.compact:
            packed.append(f"{b.label}  {b.text}")
            continue
        first, *more = b.text.split("\n")
        lines.append(f"  {b.label:<{HELP_KEY_W}}{first}")
        lines.extend(" " * (2 + HELP_KEY_W) + ln for ln in more)
    row = ""
    for item in packed:
        if row and len(row) + 3 + len(item) > HELP_PACK_W:
            lines.append("  " + row)
            row = item
        else:
            row = f"{row}   {item}" if row else item
    if row:
        lines.append("  " + row)
    return lines
