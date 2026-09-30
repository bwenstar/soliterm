# Pyramid

This is AisleRiot's Thirteen. A pyramid of 28 cards stands in seven
rows, and you take it apart in pairs whose ranks add up to 13, a King
going on its own. It's the Pyramid you may know with two differences:
the pyramid is dealt face down but for its bottom row, so each card is
a surprise when it turns up, and the stock goes through only once.

## The deal

- 28 cards make a pyramid of seven rows, one card at the peak and seven
  along the bottom. Each card is partly covered by the two below it.
- Only the bottom row is dealt face up.
- The other 24 cards go face down to the stock, top left. The waste
  beside it starts empty.

The status line shows how many cards are left in the stock.

## Goal

Take the pyramid apart. As AisleRiot counts it, the game is won once
the stock and the waste are empty and the left card of the second row
is gone. That card can only go once the 20 cards under it have, so all
that can be left then is a line of cards from the peak down the right
edge, with only the lowest of them free and nothing left to pair it
with. Clearing every card is a win too.

## Moves

- A card is free once both cards covering it are gone, and it turns
  face up then. The top card of the waste is free too.
- Two free cards whose ranks add up to 13 go off together: an Ace (1)
  with a Queen (12), a 2 with a Jack (11), a 3 with a 10, a 4 with a 9,
  a 5 with an 8, and a 6 with a 7. Pick one up and put it down on the
  other, by keyboard or mouse, or type both slots in text mode, as in
  `23 27`.
- A King counts 13 on its own and goes alone. Press f on it or
  double-click it, put it down on the pile of cards taken off, top
  right (Fnd on the board, `fnd#30` in text mode), or type `f` and its
  slot in text mode. AisleRiot takes a King off with one click; here a
  click picks it up, as it does any card.
- The top card of the waste pairs with a free card in the pyramid, or
  with the waste card under it. For that one, press f on the waste or
  double-click it, or put its top card down on the pile of cards taken
  off.
- Turn the next stock card onto the waste at any time: press d or click
  the stock, or type d in text mode. The stock is turned one card at a
  time and there is no redeal.

The board shows the top two cards of the waste, the ones that can pair.
The cards taken off go on a pile of their own, top right, so that undo
can bring them back. A pair is one move, to undo and redo and in the
move count.

There's nothing for `a` to send up as it plays, until the end: once the
stock is out, every card left is face up and the win needs only Kings
and pairs on the waste to go, it takes those off as one move.

## Scoring

Each card taken off scores 1, so clearing the lot scores 52. This
matches AisleRiot.

## How it differs from other Pyramids

Most Pyramid games deal the whole pyramid face up, so you can plan the
game from the first move, and many let you go through the stock two or
three times. Here the cards turn up only as the two on them go, and the
stock goes through once. AisleRiot also has no pile for the cards taken
off; Soliterm keeps one so undo has somewhere to take them back from.

## Options

Pyramid has no options.

## Tips

- Take a King off as soon as it's free. It pairs with nothing, so there
  is nothing to wait for, and one on the waste holds back the cards
  under it.
- Prefer the pair that turns up a card in the pyramid. The pyramid's
  cards are what the game is played with, and a waste card comes back
  anyway once the cards on it go.
- Before you turn the stock, look at the top two waste cards. They may
  make 13 on their own.
- Work on the left side. The game is won once the left card of the
  second row goes, so the cards down the right edge can wait.
- Most deals can't be won however they're played, so a lost game is
  often the deal's doing and not yours.
