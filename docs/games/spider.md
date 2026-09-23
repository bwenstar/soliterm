# Spider

A two-deck game over ten columns, where you sort the cards into full
runs from King down to Ace. With one suit it's a gentle way to learn;
with four, the default, it's hard work, and while skill counts for a lot
the stock can still turn against you late on.

## The deal

Spider always plays with 104 cards. Which cards depends on the Suits
option: with four suits it's two ordinary decks, with two it's four sets
each of spades and hearts, and with one it's eight sets of spades.

- Ten columns make up the tableau. Columns 1, 4, 7 and 10 get six cards
  each and the other six get five, 54 in all. Only the top card of each
  column is face up.
- The other 50 cards go face down in the stock, enough for five deals of
  ten.
- Eight foundations start empty and take the runs as you finish them.

## Goal

Build eight complete runs, each going from King down to Ace in a single
suit. Each one moves off to a foundation as soon as it's finished, and
the game is won when all eight have gone.

## Moves

- Build down by one rank, whatever the suit: any 6 can go on any 7.
- You can move the top card of a column, or a run of cards that goes
  down one rank at a time in a single suit. A mixed-suit run can be
  built but can't be moved in one piece: if a 5 and 6 of spades sit on a
  7 of hearts, only the 5 and 6 can come away together.
- An empty column takes any card, or any run you're allowed to move.
- When you uncover a face-down card, it turns over by itself.
- Dealing from the stock puts one card face up on each of the ten
  columns. You can't deal while any column is empty, so fill the gaps
  first. There's no redeal: once the fifth deal is out, the stock is
  gone. The status line shows how many deals are left.
- When the top 13 cards of a column make a full run from King down to
  Ace in one suit, they move to a foundation by themselves and the card
  underneath turns over. You can't put cards on the foundations
  yourself, and a finished run never comes back.

One trap to know about: if the stock still has deals in it but fewer
than ten cards are left in the columns, you can never fill every column,
so you can never deal again and the game can't be won. Undo until there
are enough cards to go round.

## Scoring

The score is worked out afresh after every move:

- 12 points for each finished run on the foundations.
- 1 point for every face-up card sitting directly on a face-up card of
  the same suit one rank higher. A run of five hearts from 9 down to 5
  is worth 4.

So splitting up a same-suit run costs you points. The most you can score
is 96. This is the same as AisleRiot's Spider scoring.

## Options

Open the options screen with o during a game. Using it ends the game in
progress (which counts as a loss if you'd made a move) and starts a new
deal with your settings, which are remembered for next time.

- **Suits**: 1, 2 or 4, default 4. How many suits the 104 cards are
  spread over. With one suit every card is a spade, so every run you
  build can move as one. Two suits uses spades and hearts, and four is
  two full decks. The more suits, the harder the game.

## Tips

- When a card could go on either of two others, put it on the one of
  its own suit. Same-suit runs move in one piece later and score points,
  while mixed ones mostly get in the way.
- An empty column is the most useful thing on the board. Use it to hold
  a run while you rearrange the others, or to swap cards between columns
  to sort out mixed suits. You'll have to fill it before the next deal,
  so get the most out of it first.
- Tidy up before you deal. Turn over what you can and join runs where
  they fit, because the deal drops a card on every column and can bury a
  run just as it was coming together.
- A King can only ever move into an empty column. Moving one there
  uncovers whatever was under it but ties that column up for a long
  while, so only do it when the cards you free are worth it.
