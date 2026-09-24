"""Share codes: what they look like, and reading them back however they
were pasted. And the daily deal, which is the same for everyone."""

import itertools
import re
from datetime import date

import pytest

from soliterm import deals
from soliterm.deals import Code, Deal, code_of, parse, share_code
from soliterm.engine import GAME_ORDER, GAMES

from helpers import deal

KLONDIKE = {"draw": 1, "redeals": "standard"}


@pytest.mark.parametrize(
    "key, number, options, code",
    [
        ("klondike", 48213, {"draw": 3}, "klondike:d3:48213"),
        ("klondike", 48213, None, "klondike:48213"),
        ("klondike", 48213, {"draw": 1, "redeals": "standard"}, "klondike:48213"),
        ("klondike", 1, {"draw": 3, "redeals": "none"}, "klondike:d3rn:1"),
        ("klondike", 77, {"redeals": "unlimited"}, "klondike:ru:77"),
        ("spider", 7, {"suits": 2}, "spider:s2:7"),
        ("spider", 5, None, "spider:5"),
        ("freecell", 617, None, "freecell:617"),
        ("golf", 0, None, "golf:0"),
    ],
)
def test_share_code(key, number, options, code):
    assert share_code(key, number, options) == code


@pytest.mark.parametrize(
    "text, key, number, options",
    [
        ("klondike:d3:48213", "klondike", 48213, {"draw": 3, "redeals": "standard"}),
        ("Klondike D3RN 48213", "klondike", 48213, {"draw": 3, "redeals": "none"}),
        # the game's own defaults, not whatever the player has saved
        ("klondike:48213", "klondike", 48213, KLONDIKE),
        ("klondike:d1rs:48213", "klondike", 48213, KLONDIKE),
        ("Forty Thieves 5", "fortythieves", 5, {}),
        ("forty-thieves/5", "fortythieves", 5, {}),
        ("baker's dozen:5", "bakersdozen", 5, {}),
        ("eight-off/9", "eightoff", 9, {}),
        ("freecell #617", "freecell", 617, {}),
        ("FreeCell deal 617", "freecell", 617, {}),
        ("Klondike, deal 48213", "klondike", 48213, KLONDIKE),
        # the board's title line, pasted whole
        ("Soliterm  -  Klondike  -  Deal 48213", "klondike", 48213, KLONDIKE),
        # and text mode's, with its note after the number
        ("Soliterm - Golf - Deal 8 (text mode)", "golf", 8, {}),
        ("Soliterm - Golf - Deal 8 (text mode). Type h for help.", "golf", 8, {}),
        # a daily's, as the deal it is, with the standard options
        ("Soliterm  -  Klondike  -  Daily 2026-09-24", "klondike", 20260924, KLONDIKE),
        ("Soliterm - Golf - Daily 2026-09-24 (text mode)", "golf", 20260924, {}),
        ("klondike:d3:48213.", "klondike", 48213, {"draw": 3, "redeals": "standard"}),
        ("spider:s2:7", "spider", 7, {"suits": 2}),
        ("golf:0", "golf", 0, {}),
        ("klondike:2147483647", "klondike", 2147483647, KLONDIKE),
        # a bare number leaves the game open
        ("48213", None, 48213, None),
        ("+5", None, 5, None),
        ("007", None, 7, None),
        ("#617", None, 617, None),
        ("0", None, 0, None),
        (" 2147483647 ", None, 2147483647, None),
    ],
)
def test_parse(text, key, number, options):
    assert parse(text) == Code(key, number, options)


@pytest.mark.parametrize(
    "text, error",
    [
        ("", "a share code looks like klondike:d3:48213"),
        (":::", "a share code looks like klondike:d3:48213"),
        ("#", "a share code looks like klondike:d3:48213"),
        ("-5", "deal numbers run from 0 to 2147483647, not -5"),
        ("2147483648", "deal numbers run from 0 to 2147483647, not 2147483648"),
        ("99999999999", "deal numbers run from 0 to 2147483647, not 99999999999"),
        ("klondike:2147483648", "deal numbers run from 0 to 2147483647, not 2147483648"),
        ("klondike", "klondike needs a deal number too, as in klondike:48213"),
        ("klondike:d3", "klondike needs a deal number too, as in klondike:48213"),
        ("klondike (text mode)", "klondike needs a deal number too, as in klondike:48213"),
        # a number that's there, just not where it goes
        ("klondike:48213:d3", "the deal number goes last in a share code, as in klondike:d3:48213"),
        ("klondike:12x", "'12x' isn't a deal number"),
        ("chess:5", "no game called 'chess'"),
        ("5 klondike", "the game goes first in a share code, as in klondike:d3:48213"),
        ("12x", "'12x' isn't a deal number"),
        # a fullwidth 5, which str.isdigit takes for a digit
        ("\uff15", "'\uff15' isn't a deal number"),
        (
            "klondike:d2:5",
            "'d2' isn't a Klondike option in a share code (it takes d1, d3, rs, rn, ru)",
        ),
        ("klondike:d3d1:5", "the share code sets draw twice"),
        ("spider:s3:5", "'s3' isn't a Spider option in a share code (it takes s1, s2, s4)"),
        ("freecell:d3:5", "FreeCell has no options, so 'd3' can't be in its share code"),
    ],
)
def test_parse_refuses(text, error):
    with pytest.raises(ValueError, match=f"^{re.escape(error)}$"):
        parse(text)


def every_option_set():
    for key in GAME_ORDER:
        spec = GAMES[key].option_spec()
        names = [name for name, _, _ in spec]
        for values in itertools.product(*(vals for _, _, vals in spec)):
            opts = dict(zip(names, values))
            label = key + "".join(f"-{n}{v}" for n, v in opts.items())
            yield pytest.param(key, opts, id=label)


@pytest.mark.parametrize("key, opts", list(every_option_set()))
def test_share_codes_round_trip_for_every_game_and_option(key, opts):
    code = share_code(key, 48213, opts)
    assert parse(code) == Code(key, 48213, opts)
    # and it reads the same however it's written
    assert parse(code.upper().replace(":", " ")) == Code(key, 48213, opts)


def test_code_of_the_game_in_play():
    g = deal("spider", 7, suits=2)
    assert code_of(g) == "spider:s2:7"
    g.new_game()
    assert code_of(g) == "spider:s2:8"
    assert code_of(deal("canfield", 20260924)) == "canfield:20260924"


@pytest.mark.parametrize("key", GAME_ORDER)
def test_every_option_has_a_letter_and_values_of_its_own(key):
    # what a share code needs to tell the options and their values apart
    spec = GAMES[key].option_spec()
    assert len({name[0] for name, _, _ in spec}) == len(spec)
    for name, _, values in spec:
        assert len(set(values)) == len(values)
        kinds = {type(v) for v in values}
        assert kinds in ({int}, {str}), name
        if kinds == {str}:
            assert len({v[0] for v in values}) == len(values), name
        for value in values:
            token = name[0] + (str(value) if kinds == {int} else value[0])
            assert token.isalnum() and token.isascii(), token


# -- the daily deal -------------------------------------------------------------------

DAY = date(2026, 9, 24)


def test_the_daily_number_is_the_date():
    assert deals.daily_number(DAY) == 20260924
    assert deals.daily_number(date(2027, 1, 2)) == 20270102
    assert deals.daily("spider", DAY) == Deal("spider", 20260924, None, "2026-09-24")


def board(g):
    return [s.cards for s in g.slots]


@pytest.mark.parametrize("key", GAME_ORDER)
def test_a_daily_plays_the_standard_options(key):
    # the player's own options stay out of it, so everyone gets the same cards
    saved = {"draw": 3, "redeals": "none"} if key == "klondike" else {"suits": 4}
    g = deals.deal_game(deals.daily(key, DAY), saved)
    assert g.options == GAMES[key].default_options()
    assert board(g) == board(deal(key, 20260924))
    assert (g.deal_number, g.daily) == (20260924, "2026-09-24")
    assert code_of(g) == f"{key}:20260924"
    assert deals.deal_label(g) == "Daily 2026-09-24"
    # n goes on to a deal at random, not the next day's
    assert g.seed is None


def test_a_dailys_code_typed_in_is_not_a_daily():
    g = deals.deal_game(deals.deal_of(parse("klondike:20260924"), "klondike"), {})
    assert g.daily is None and g.seed == 20260924
    assert deals.deal_label(g) == "Deal 20260924"


@pytest.mark.parametrize(
    "won, seconds, moves, line",
    [
        (True, 192, 87, "Soliterm daily 2026-09-24, Klondike: won in 3:12, 87 moves"),
        (False, 543, 212, "Soliterm daily 2026-09-24, Klondike: stuck after 9:03, 212 moves"),
        (True, 40, 1, "Soliterm daily 2026-09-24, Klondike: won in 0:40, 1 move"),
    ],
)
def test_the_share_line(won, seconds, moves, line):
    assert deals.share_line("Klondike", "2026-09-24", won, seconds, moves) == line


def test_the_longest_share_line_is_71_characters():
    name = max((cls.name for cls in GAMES.values()), key=len)
    line = deals.share_line(name, "2026-09-24", False, 59 * 60 + 59, 1000)
    assert line.endswith(f", {name}: stuck after 59:59, 1000 moves")
    assert len(line) == 71


@pytest.mark.parametrize("key", GAME_ORDER)
def test_the_share_line_names_no_card(key):
    g = deals.deal_game(deals.daily(key, DAY), {})
    line = deals.share_line(g.gamedef.name, g.daily, True, 192, 87)
    cards = {c.label(symbols) for slot in g.slots for c in slot.cards for symbols in (True, False)}
    assert cards and not cards & set(re.split(r"[\s,:]+", line))
