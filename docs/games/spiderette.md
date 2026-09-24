# Spiderette

Spiderette is Spider cut down to one deck and seven columns, dealt like
Klondike. It's quicker than Spider, and harder than it looks: with four
suits and so few columns, an empty column is rare and precious.

## The deal

- Seven columns make up the tableau. The first gets one card, the second
  two, and so on up to seven in the last, 28 cards in all. Only the top
  card of each column is face up.
- The other 24 cards go face down in the stock, top left: enough for
  three deals of seven and a last deal of three.
- Four foundations sit beside the stock and start empty.

The status line shows the cards left in the stock, how many deals that
makes, and how many suits are done.

## Goal

Build all four suits from King down to Ace. Each one moves off to a
foundation by itself as soon as it's finished, and the game is won when
all four have gone.

## Moves

- Build down by one rank, whatever the suit: any 6 can go on any 7.
- You can move the top card of a column, or a run of cards that goes
  down one rank at a time in a single suit. A mixed-suit run can be
  built but can't be moved in one piece.
- An empty column takes any card, or any run you're allowed to move.
- When you uncover a face-down card, it turns over by itself.
- Dealing puts one card face up on each of the seven columns. Press d,
  click the stock, or type d in text mode. You can't deal while any
  column is empty, so fill the gaps first. The last deal has only three
  cards, and they go on the first three columns.
- When the top 13 cards of a column make a full run from King down to
  Ace in one suit, they move to a foundation by themselves and the card
  underneath turns over. A finished suit never comes back.

As in Spider, if the stock still has cards in it but fewer than seven
are left in the columns, you can never fill every column, so you can
never deal again. Undo until there are enough to go round.

## Scoring

You get a point for every face-up card sitting directly on a face-up
card of the same suit one rank higher, and 12 for each finished suit.
The score is worked out afresh after every move, so a won game scores
48. This matches AisleRiot.

## Options

Spiderette has no options. AisleRiot always deals it with four suits,
and so does Soliterm.

## Tips

- An empty column is worth even more here than in Spider. Fill it only
  when the move you get from it pays you back.
- Before a deal, sort each column so the run on top is in one suit. The
  deal drops a card on it, and a mixed run gets buried.
- The last deal only reaches the first three columns, so plan for the
  other four to get nothing more from the stock.
- The seventh column hides six cards. Work on the right-hand columns
  early, as that's where most of the face-down cards are.
