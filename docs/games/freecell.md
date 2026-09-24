# FreeCell

A one-deck game with every card dealt face up, so nothing is hidden and
there's very little luck: nearly every deal can be won with enough care.
Four free cells give you room to move cards around, and making good use
of them is most of the game.

## The deal

- All 52 cards are dealt face up into eight columns: seven in each of
  the first four and six in each of the last four.
- Four free cells and four foundations sit along the top, all empty.
- Deals are numbered as in Microsoft FreeCell, so deal 617 here has the
  same cards as deal 617 there, and solutions for a numbered deal work.

## Goal

Move all 52 cards to the foundations, one suit to each, from Ace up to
King.

## Moves

- Build down the columns in alternating colours: a red 9 goes on a black
  10, and a black 9 on a red 10.
- A free cell holds a single card. You can put the top card of any
  column in an empty cell, and later move it on to a column or a
  foundation.
- An empty column takes any card, or any run you can move.
- Foundations build up by suit from the Ace, one card at a time, from a
  column or a free cell. Double-click a card, or press f, to send it up.
  Once a card is on a foundation it stays there.
- There's no stock, so no dealing and no redeals.

Strictly speaking cards move one at a time, but to save you the bother
you can move a run in alternating colours in one go, as long as you
could have done it card by card with the free cells and empty columns
you have. The most you can move at once is one more than the number of
empty free cells, doubled for every empty column:

- 4 empty free cells, no empty column: 5 cards
- 2 empty free cells, one empty column: 6 cards
- 4 empty free cells, one empty column: 10 cards
- no empty free cells, no empty column: 1 card

If the run is going into an empty column, that column doesn't count, so
with four empty free cells and one empty column you can move 5 cards
into it.

Autoplay, when you ask for it, only sends a card up once nothing still
in play could want to be built on it: a red 5 waits until both black 4s
are on the foundations. Aces and 2s always go.

Once every card left can go up, a sends them all up as one move.

## Scoring

One point for each card on the foundations, so a win scores 52. Cards
can't come back off the foundations, so short of an undo the score only
ever goes up. This matches AisleRiot.

## Options

FreeCell has no options.

## Tips

- Park cards in the free cells only for as long as you need to. Every
  card sitting in one shrinks the run you can move, and with all four
  full and no empty column you're down to one card at a time.
- An empty column is worth more than a free cell. With no empty column,
  each free cell adds one card to the run you can move, while an empty
  column doubles it. Before you drop a lone card into an empty column,
  check whether keeping it clear would help more.
- Find the Aces and 2s before you start and work out how to reach them.
  A low card buried deep in a column holds up its whole suit.
- You can see every card, so it pays to plan a few moves ahead before
  you commit. If a line doesn't work out, undo and try another.
