# Scorpion

A one-deck game with no foundations. You sort the whole deck into four
columns, one suit each, from King down to Ace. Any face-up group can
move, in order or not, so the puzzle is untangling knots rather than
finding room.

## The deal

- Seven columns of seven cards make up the tableau. The bottom three
  cards of the first four columns are face down, 12 hidden cards in
  all, and every other card is face up.
- The last three cards go face down in the stock, top left.
- There are no foundations.

The status line shows the cards left in the stock and how many suits
are done.

## Goal

Get four columns each holding one whole suit in order, from the King at
the bottom to the Ace on top, with the other three columns empty. The
game is won the moment that's true.

## Moves

- Any face-up card can be picked up along with every card on top of it,
  whether or not they're in order. It goes on the next card up of its
  own suit: the 8 of hearts takes the 7 of hearts, and nothing else.
- Only a King, or a group with a King at the bottom, goes into an empty
  column.
- When you uncover a face-down card, it turns over by itself.
- The stock is dealt once, whenever you like: press d or click the
  stock, or type d in text mode. It puts one card face up on each of the
  first three columns, even an empty one.
- Nothing ever leaves the tableau. A suit is done where it lies.

If all that's left is sliding a column with a King at the bottom from
one empty column to another, the game is over, as that changes nothing.
Undo to try another line.

## Scoring

The score is worked out afresh from the board after every move, so an
undo takes it back exactly. This matches AisleRiot:

- 1 point for every face-up card sitting directly on the next card up
  of its own suit. A run of hearts from 9 down to 5 is worth 4.
- 4 points for each suit that's whole in a column of its own.
- 3 points for each of the 12 face-down cards once it's turned up.

A won game scores 100: 48 for the pairs, 16 for the four suits and 36
for the cards turned up.

## Options

Scorpion has no options.

## Tips

- Get at the face-down cards in the first four columns early. They're
  where games are lost.
- Moving a big mixed group onto its match is often right. The mess
  moves with it, and you can sort it out later.
- Keep the stock until it helps. Three new cards on the first three
  columns can bury what you were digging for.
- A King stuck in the middle of a column needs an empty column to go
  to. Plan the empty column before you need it.
