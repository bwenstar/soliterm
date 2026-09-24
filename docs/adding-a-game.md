# Adding a game

Every game in Soliterm is one small Python module: a class that answers
the engine's questions about its rules. Can these cards be picked up? Can
they land there? What does a double-click do? Is the game won? This page
adds a game from the first line to a passing suite, using Fortress as the
example. Fortress is one of AisleRiot's games that Soliterm doesn't have,
and it's short enough to show whole.

[architecture.md](architecture.md) has the bigger picture, and
[CONTRIBUTING.md](../CONTRIBUTING.md) says how to set up a checkout and
run the tests.

## The rules

Soliterm plays each game the way AisleRiot does, scoring and all, so a
player who knows a game from one knows it from the other, and the
statistics the two share mean the same thing. AisleRiot's manual has a
page on every game, and on Linux it's installed along with AisleRiot, as
`/usr/share/help/C/aisleriot/fortress.xml` for this one. Its rules for
Fortress:

- One deck. Four foundations, built up in suit from Ace to King. Cards on
  the foundations are out of play.
- Ten columns, all face up: five cards to each and one more to two of
  them.
- Only the top card of a column moves, onto a card of its suit one rank
  higher or lower. An empty column takes any card.
- A point for every card on the foundations, so a win scores 52.

## A key and a name

The key is how everything else knows the game: `--game fortress`, share
codes such as `fortress:48213`, its save in `saves/fortress.json`, and its
settings and statistics. It picks the game's own stream of shuffles too,
so once the game is out, changing the key would change every deal. The
other keys are the name in lower case with the spaces taken out, as in
`bakersdozen`.

The name is what the menu, the board and the statistics show, and the
blurb is the one line about the game under the board's title, on the
menu and in `--list`. The menu and `--stats` leave 16 characters for the
name and `--list` leaves 14 for the key, so staying inside those keeps
the rows lined up. An 80-column menu shows about the first 54 characters
of the blurb.

## The module

Save this as `src/soliterm/engine/games/fortress.py`:

```python
"""Fortress: ten open columns built up or down in suit, one card at a time."""

from __future__ import annotations

from ..cards import ACE
from ..gamedef import GameDef


class Fortress(GameDef):
    key = "fortress"
    name = "Fortress"
    blurb = "Ten open columns, built up or down in suit."

    def deal(self, g):
        g.reset_slots()
        g.make_deck()
        g.shuffle()
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in range(10)]
        # five cards to each column, and the last two to the first two
        col = 0
        while g.deck:
            g.deal_from_deck(self.tableau[col % 10], 1, face_up=True)
            col += 1
        g.update_status()

    def tableau_adjacent(self, upper, lower):
        return upper.suit == lower.suit and abs(upper.rank - lower.rank) == 1

    def can_pickup(self, g, sid, n):
        # one card at a time, and never back off a foundation
        return n == 1 and g.kind(sid) == "tableau"

    def can_drop(self, g, src, cards, dst):
        card, top = cards[0], g.top(dst)
        if g.kind(dst) == "foundation":
            return card.rank == ACE if top is None else self.same_suit_up(top, card)
        if g.kind(dst) == "tableau":
            return top is None or self.tableau_adjacent(top, card)
        return False

    def send_up(self, g, sid):
        """Move the top card of sid to its foundation, if it can go."""
        card = g.top(sid)
        fid = None if card is None else self.foundation_for(g, card)
        if fid is None:
            return False
        g.slots[fid].cards.append(g.slots[sid].cards.pop())
        g.score += 1
        return True

    def on_double_click(self, g, sid):
        return g.kind(sid) == "tableau" and self.send_up(g, sid)

    def after_move(self, g, src, cards, dst):
        if g.kind(dst) == "foundation":
            g.score += 1

    def autoplay(self, g):
        # Anything that can go up is safe to send: the one card still in
        # play that could build on it, the next one up of its suit, can
        # follow it to the foundation instead.
        sent = 0
        while any(self.send_up(g, t) for t in self.tableau):
            sent += 1
        return sent

    def is_won(self, g):
        return all(len(g.cards(f)) == 13 for f in self.foundations)

    def status(self, g):
        done = sum(len(g.cards(f)) for f in self.foundations)
        return f"Foundations: {done}/52"
```

That's the whole game. The rest of this section takes it a part at a
time, and [gamedef.py](../src/soliterm/engine/gamedef.py) has every
callback with its default.

### Dealing

`deal(g)` lays out the board and deals the cards on `g`, the `Solitaire`
the game is being played on. The engine calls it for every new deal and
every restart, with the shuffle already seeded from the deal number, so
all `deal` has to do is ask for a deck, shuffle it and set the cards out:

- `g.reset_slots()` clears the board.
- `g.make_deck()` puts a deck in `g.deck`, and `g.shuffle()` shuffles it.
  `g.make_deck(2)` gives two decks, for a game like Forty Thieves.
- `g.add_slot(kind, expand)` adds a slot and returns its number. The
  kinds are `stock`, `waste`, `foundation`, `tableau`, `freecell` and
  `reserve`. `expand` is how its cards spread: `"down"` for a column,
  `"right"` for a fan like Golf's waste, or `"none"`, the default, for a
  pile that shows its top card.
- `g.carriage_return()` starts the next row of slots.
- `g.deal_from_deck(sid, n, face_up)` deals `n` cards off the end of
  `g.deck` onto slot `sid`.
- `g.update_status()` fills in the status line from `status`, below.

Slots are numbered in the order they're added, so here the foundations
are 0 to 3 and the columns 4 to 13. Text mode prints those numbers and
saves record them, so settle the order before the game goes out.

Keep the slot numbers on `self`, as `self.tableau` is here, and nothing
else. Undo, redo and saves keep the slots, the options, the score, the
moves, the redeals and Canfield's base rank, and that's all, so
anything more on `self` would be wrong after an undo.

### Moving cards

- `can_pickup(g, sid, n)`: can the top `n` cards of slot `sid` be picked
  up? Fortress lets one card at a time leave a column, and none leave a
  foundation.
- `can_drop(g, src, cards, dst)`: can `cards`, picked up from slot `src`,
  land on slot `dst`?
- `tableau_adjacent(upper, lower)`: does `lower` build on `upper` in a
  column? The hint uses it to see how much building there is on the
  board, and autoplay to see which cards are still wanted. The default is
  down in alternating colours, as in Klondike, so a game that builds any
  other way has to say so. Fortress's `can_drop` uses it as well, to keep
  the rule in one place.

The engine asks these two questions about every move, from a key, a drag,
text mode, the hint or the finish, and moves the cards only when both
answers are yes. Then it calls `after_move(g, src, cards, dst)`, where
Fortress scores a point for a card that went up, and `post_move(g)`,
which brings the status line up to date. A game that does more after a
move, as Spider does when a run is complete, overrides `post_move` and
calls `g.update_status()` itself.

The score never goes below 0, so a game that takes a point back when a
card comes down off a foundation can just subtract one.

### Clicks

`on_click(g, sid)` and `on_double_click(g, sid)` are for what a click
does beyond picking cards up. A single click on the stock usually deals,
and a double-click usually sends a card up. `f` in the full-screen game
and in text mode is a double-click too. Fortress has no stock, so it only
needs the double-click.

Return True when something changed. The engine saves the position for
undo before it calls them and drops that again on False, so one that
returns False must leave everything as it was. A click moves the cards
itself, so `after_move` isn't called and the click scores for itself,
which is why `send_up` adds the point.

### Autoplay, the finish and the hint

`autoplay(g)` sends up what's safe to send up and says how many cards
went. Most games ask `safe_to_autoplay(g, card)`, which holds a card back
while anything still in play could want to build on it, going by
`tableau_adjacent`. That's what keeps a red 5 down in Klondike while a
black 4 is out. Fortress doesn't need it: the only card that could build
on one that can go up is the next one up of its suit, and that can follow
it to the foundation instead. So Fortress sends up everything that will
go.

The finish, when `a` sends every card left up as one move, needs nothing
from the game. The engine offers it once every card is face up, the
stock is empty and every card left can go up, and plays it with
`can_pickup`, `can_drop` and `after_move`.

The hint needs nothing either. The engine tries each legal move on a copy
of the board and suggests the one that raises `progress(g)` the most.
The default counts cards on the foundations, face-down cards turned up,
cards taken out of the waste, free cells and reserve, and cards built
into runs. A game with no foundations, such as Golf, gives its own
`progress`, and `fallback_move`, `is_dead_end` and `no_hint_reason` are
there for a game whose hint needs more help.

### Winning, dealing and the status line

- `is_won(g)` says when the game is won.
- `can_deal(g)` says whether the stock can deal now, and
  `deal_blocked_reason(g)` why not. The defaults cover a plain stock, and
  with no stock, as here, they say there's nothing to deal.
- `status(g)` is the game's part of the status line.

### Options

Fortress has none. A game with options declares them in two class
methods, as Klondike does:

```python
class Klondike(GameDef):
    @classmethod
    def default_options(cls):
        return {"draw": 1, "redeals": "standard"}

    @classmethod
    def option_spec(cls):
        return [
            ("draw", "Cards to draw", [1, 3]),
            ("redeals", "Redeals", ["standard", "none", "unlimited"]),
        ]
```

The game reads them from `g.options`. They show in the Options box that
`o` opens, they're saved for each game in `config.json`, and a value
there that isn't one of the allowed ones falls back to the default. A
share code writes each option that isn't the default as a letter and a
value, as in `klondike:d3:48213`, so each option's name has to start
with a different letter, its values have to be all numbers or all
strings, and strings have to start with different letters.
`tests/test_deals.py` checks that.

An option that changes the cards, as Spider's suits do, changes what each
deal number deals. That's fine, but it has to be deliberate.

### Laying out by hand

Most games are rows of slots side by side. `fan_limit` sets how many
cards a slot that spreads to the right shows, and `spot` places slots by
hand, as Triple Peaks does to overlap its peaks.

## Register it

Two files make the game part of Soliterm. In
`src/soliterm/engine/games/__init__.py`, import the class, add it to
`GAMES`, and put its key in `GAME_ORDER` where it should come on the menu
and in `--list`:

```python
from .fortress import Fortress

GAMES: dict[str, type[GameDef]] = {
    cls.key: cls
    for cls in [
        ...
        BakersDozen,
        Fortress,
        FortyThieves,
        Canfield,
    ]
}

GAME_ORDER = [
    ...
    "bakersdozen",
    "fortress",
    "fortythieves",
    "canfield",
]
```

In `src/soliterm/engine/__init__.py`, import it too and add `"Fortress"`
to `__all__`, as the other games are.

Now it plays. Give it a throwaway home, so your own statistics stay out
of it:

```sh
tmp=$(mktemp -d)
HOME=$tmp XDG_CONFIG_HOME=$tmp/.config XDG_DATA_HOME=$tmp/.local/share soliterm --game fortress
```

With `--text --deal fortress:1 --ascii` on the end instead of `--game
fortress`, text mode prints the board with its slot numbers, which come
in handy while you work on the rules:

```text
Soliterm - Fortress - Deal 1 (text mode). Type h for help.

=== Fortress ===
fnd#0 fnd#1 fnd#2 fnd#3
[   ] [   ] [   ] [   ]

   #4    #5    #6    #7    #8    #9   #10   #11   #12   #13
[ 7C] [ AC] [ 2D] [ 6C] [ 5D] [ 5S] [ QD] [ 9C] [ QH] [ 5C]
[ 6S] [ 3S] [ QC] [ QS] [ KC] [ 8H] [ 6H] [ 7S] [ KS] [ JD]
[ KD] [10D] [ 2C] [ 9H] [ 9S] [ JC] [ 3H] [ AH] [ 3D] [10H]
[10C] [ AS] [ 6D] [ KH] [ 8S] [ 4S] [ 4C] [ 5H] [ 2H] [ 7D]
[ JH] [ JS] [ 2S] [ 4D] [ 4H] [10S] [ AD] [ 3C] [ 9D] [ 7H]
[ 8C] [ 8D]

score=0 moves=0 | Foundations: 0/52
```

## Share its statistics with AisleRiot

If AisleRiot has the game, add it to `GAME_TO_SECTION` in
[aisleriot.py](../src/soliterm/aisleriot.py):

```python
    "fortress": "fortress.scm",
```

That's the section AisleRiot keeps the game's statistics under in its
keyfile, `~/.config/gnome-games/aisleriot`. It's the name of the game's
Scheme file with any hyphens turned into underscores, so `eight-off.scm`
keeps its statistics under `[eight_off.scm]`. With the entry there,
Soliterm and AisleRiot share one record of the game, and a win in either
shows in both. If you have AisleRiot, play a game of it there and look
for the section in the keyfile to be sure of the name.

Add the pair to `NEW_SECTIONS` in `tests/test_aisleriot_sync.py` as well,
which lists the games added since 1.0.0.

A game AisleRiot doesn't have stays out of `GAME_TO_SECTION`, and its
statistics stay in Soliterm's own `stats.json`.

## Run the conformance suite

Add the number of cards in a full deal to `EXPECTED_CARDS` in
`tests/helpers.py`:

```python
    "fortress": 52,
```

and run

```sh
python -m pytest tests/test_conformance.py -k fortress
```

[test_conformance.py](../tests/test_conformance.py) takes every game in
`GAME_ORDER`, with every mix of its options, through the rules they all
keep:

- the deal has the right number of cards, none missing or doubled;
- a deal number always deals the same hand, and the next number a
  different one;
- random play, sensible and silly, never crashes, loses a card or takes
  the score below 0;
- a position written out and read back plays on the same;
- undo goes all the way back to the deal, and redo replays every step
  exactly;
- every hint is a legal move, and asking for one changes nothing;
- the finish scores the same as sending the cards up one at a time.

A game with no foundations can't be finished that way, so add its key to
the list in `test_finish_scores_like_the_moves_one_by_one`, with Golf,
Triple Peaks and Scorpion.

When one fails, the test's name says which game and options, as in
`[fortress]` or `[klondike-draw3-redealsnone]`. The rest of the suite goes
over `GAME_ORDER` as well, so `python -m pytest` also checks the new
game's share codes, daily deal, hints, `--list` and `--stats`.

## Pin the deals

Once the deal is final, pin it, so nothing can change it by accident.
`DEALS` in `tests/test_conformance.py` holds a short hash of deals 1 and
2 of each game. From the top of the checkout:

```sh
PYTHONPATH=src:tests python -c "from helpers import deal; from test_conformance import deal_digest; print(tuple(deal_digest(deal('fortress', n)) for n in (1, 2)))"
```

On Windows, `set PYTHONPATH=src;tests` first. It prints

```text
('3cfe7281f0d700ca', 'ce6d60442a91d165')
```

and that's the row to add:

```python
    "fortress": ("3cfe7281f0d700ca", "ce6d60442a91d165"),
```

Nothing checks a game without a row. Once players have codes for a game,
a change that fails this test would deal them different cards, so after a
release a failure here is a bug to fix, not a row to update.

## Test its own rules

The conformance suite knows what every game has to do, not what makes
this one Fortress. Give the game a test file of its own,
`tests/test_fortress.py`, that sets small positions up by hand and checks
each rule. `clear_board` from `tests/helpers.py` empties the board, so a
test can put down exactly the cards it wants:

```python
"""Fortress: ten open columns built up or down in suit, one card at a time."""

import pytest

from soliterm.engine import Card

from helpers import clear_board, deal

FOUNDATIONS, COLUMNS = [0, 1, 2, 3], list(range(4, 14))
A, B, C, D, E = COLUMNS[:5]


def up(rank, suit):
    return Card(rank, suit, True)


@pytest.fixture
def table():
    """Fortress with every card taken off, to set a position up by hand."""
    g = deal("fortress", 1)
    clear_board(g)
    return g


def test_the_deal_is_ten_open_columns():
    g = deal("fortress", 1)
    assert g.ids_of("foundation") == FOUNDATIONS
    assert g.ids_of("tableau") == COLUMNS
    assert [len(g.cards(t)) for t in COLUMNS] == [6, 6] + [5] * 8
    assert all(c.face_up for t in COLUMNS for c in g.cards(t))
    assert g.status == "Foundations: 0/52"


def test_columns_build_up_or_down_in_suit(table):
    g = table
    g.slots[A].cards = [up(7, "H")]
    g.slots[B].cards = [up(8, "H")]
    g.slots[C].cards = [up(6, "H")]
    g.slots[D].cards = [up(8, "S")]
    g.slots[E].cards = [up(5, "H")]
    assert not g.attempt_move(D, A)  # another suit
    assert g.attempt_move(B, A)  # 8H up on 7H
    assert not g.attempt_move(C, A)  # 6H isn't next to 8H
    assert g.attempt_move(E, C)  # 5H down on 6H
```

The rest of the file checks one card at a time and the empty columns, the
foundations keeping their cards, the score, autoplay and the win, the
same way.

## Write it up

- `docs/games/fortress.md`, in the sections the other pages have: a
  paragraph on what the game is like, then The deal, Goal, Moves,
  Scoring, Options and Tips. Say where it differs from games a player may
  know already, and give the scoring AisleRiot uses.
- A row in the table in [docs/games/README.md](games/README.md), in menu
  order.
- A row in the games table in [README.md](../README.md).
- Its name in the Game list of the bug report form,
  [.github/ISSUE_TEMPLATE/bug_report.yml](../.github/ISSUE_TEMPLATE/bug_report.yml).
  `tests/test_game_lists.py` checks that list and the table in
  `docs/games/README.md`.
- An entry under GAMES in the man page,
  [man/soliterm.6](../man/soliterm.6), in menu order.
  `tests/test_man_page.py` checks every game is there. See how it reads
  with `man -l man/soliterm.6`.
- The number of games, where the README and the man page give it.
- A line under Unreleased in [CHANGELOG.md](../CHANGELOG.md).

## Before you send it

Play a few games through, in the full-screen game and in text mode, and
at 80 by 24 as well as at the size you usually play. Then run the lint
commands and the whole suite as [CONTRIBUTING.md](../CONTRIBUTING.md)
describes. Its checklist has every step on this page in one place.
