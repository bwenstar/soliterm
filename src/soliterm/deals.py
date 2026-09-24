"""soliterm.deals - deal numbers and share codes.

A share code names a deal so someone else can play it: the game, any
options that differ from the defaults, and the deal number, as in
klondike:d3:48213 (Klondike drawing three, deal 48213). Each option is
its first letter and its value, or the first letter of its value.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from . import APP_NAME, engine
from .engine import GAMES, MAX_DEAL, Solitaire

EXAMPLE = "klondike:d3:48213"
_SEPARATORS = re.compile(r"[\s:\-_./#',]+")
_DIGITS = re.compile(r"[0-9]+")  # ASCII only, unlike str.isdigit
_BARE = re.compile(r"#?[+-]?[0-9]+")
_NOTE = re.compile(r"(?<=[0-9])\s*\([^0-9]*$")  # "Deal 8 (text mode)", after the number


class Code(NamedTuple):
    """What a share code says. key and options are None for a bare number,
    which leaves the game (and so its options) to whoever plays it."""

    key: str | None
    number: int
    options: dict | None


class Deal(NamedTuple):
    """A game to start: `key`, deal `number` (None for a random one), with
    `options` over the saved ones (None for just the saved ones)."""

    key: str
    number: int | None = None
    options: dict | None = None


def _number(text: str) -> int:
    digits = text.lstrip("+-")
    # -1 stands for anything that isn't a number, and 11 digits or more is
    # out of range whatever they are
    n = int(text) if _DIGITS.fullmatch(digits) and len(digits) <= 10 else -1
    if not 0 <= n <= MAX_DEAL:
        raise ValueError(f"deal numbers run from 0 to {MAX_DEAL}, not {text}")
    return n


def _token(name: str, value: object) -> str:
    return name[0] + (str(value) if type(value) is int else str(value)[0])


def share_code(key: str, number: int, options: dict | None = None) -> str:
    """The share code of deal `number` of `key` with `options`."""
    cls = GAMES[key]
    opts, default = cls.sanitize_options(options), cls.default_options()
    tokens = "".join(
        _token(name, opts[name]) for name, _, _ in cls.option_spec() if opts[name] != default[name]
    )
    return ":".join(part for part in (key, tokens, str(number)) if part)


def code_of(g: Solitaire) -> str:
    """The share code of the deal in play."""
    return share_code(g.gamedef.key, g.deal_number, g.options)


def deal_label(g: Solitaire) -> str:
    """What the title and the text header call the deal in play."""
    return f"Deal {g.deal_number}"


def _options(key: str, text: str) -> dict:
    cls = GAMES[key]
    spec = cls.option_spec()
    if not spec:
        raise ValueError(f"{cls.name} has no options, so '{text}' can't be in its share code")
    by_letter = {name[0]: (name, allowed) for name, _, allowed in spec}
    opts = dict(cls.default_options())
    seen = set()
    i = 0
    while i < len(text):
        name, allowed = by_letter.get(text[i], (None, None))
        value, end = None, i + 1
        if name is not None and allowed is not None:
            if type(allowed[0]) is int:
                m = _DIGITS.match(text, i + 1)
                if m:
                    value = next((a for a in allowed if str(a) == m.group()), None)
                    end = m.end()
            else:
                value = next((a for a in allowed if a[0] == text[i + 1 : i + 2]), None)
                end = i + 2
        if value is None:
            takes = ", ".join(_token(n, a) for n, _, vals in spec for a in vals)
            raise ValueError(
                f"'{text[i:]}' isn't a {cls.name} option in a share code (it takes {takes})"
            )
        if name in seen:
            raise ValueError(f"the share code sets {name} twice")
        seen.add(name)
        opts[name] = value
        i = end
    return opts


def parse(text: str) -> Code:
    """Read a deal number or a share code. Raises ValueError saying what's
    wrong with it."""
    text = _NOTE.sub("", text.strip().lower())
    if _BARE.fullmatch(text):
        return Code(None, _number(text.lstrip("#")), None)
    parts = [p for p in _SEPARATORS.split(text) if p]
    if parts and parts[0] == APP_NAME.lower():
        del parts[0]  # the board's title line, pasted whole
    if not parts:
        raise ValueError(f"a share code looks like {EXAMPLE}")
    for used in range(len(parts), 0, -1):
        key = "".join(parts[:used])
        if key in GAMES:
            break
    else:
        first = parts[0]
        if _DIGITS.fullmatch(first):
            raise ValueError(f"the game goes first in a share code, as in {EXAMPLE}")
        if first[0].isdigit():
            raise ValueError(f"'{first}' isn't a deal number")
        raise ValueError(f"no game called '{first}'")
    rest = parts[used:]
    if len(rest) >= 2 and rest[-2] == "deal":
        del rest[-2]  # "Klondike, deal 48213"
    if not rest or not _DIGITS.fullmatch(rest[-1]):
        if any(_DIGITS.fullmatch(p) for p in rest):
            raise ValueError(f"the deal number goes last in a share code, as in {EXAMPLE}")
        if rest and rest[-1][0].isdigit():
            raise ValueError(f"'{rest[-1]}' isn't a deal number")
        raise ValueError(f"{key} needs a deal number too, as in {key}:48213")
    fields = "".join(rest[:-1])
    options = _options(key, fields) if fields else GAMES[key].default_options()
    return Code(key, _number(rest[-1]), options)


def deal_of(code: Code, key: str) -> Deal:
    """The Deal a code asks for, with `key` as the game for a bare number."""
    return Deal(code.key or key, code.number, code.options)


def deal_game(deal: Deal, saved: dict) -> Solitaire:
    """Deal what `deal` asks for. Options it leaves out come from `saved`,
    the player's own."""
    opts = {**GAMES[deal.key].default_options(), **saved, **(deal.options or {})}
    # looked up here, not imported, so a test can hand in its own game
    return engine.new_solitaire(deal.key, seed=deal.number, options=opts)
