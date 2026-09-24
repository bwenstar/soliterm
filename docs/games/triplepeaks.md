# Triple Peaks

Also known as Tri Peaks. Three overlapping peaks of cards stand on a row
of ten, and you clear them onto a single waste pile one rank up or
down. It plays like Golf, but the ranks wrap and the score rewards long
runs, so the question is less "can I clear it" than "how well".

## The deal

- Three peaks of 1, 2 and 3 rows, 18 cards in all, are dealt face down.
  They rest on a face-up row of ten that joins them, 28 cards in all.
  Each card overlaps the one or two cards above it.
- One card is turned face up onto the waste, for free.
- The other 23 cards go face down to the stock, top left.

The status line shows how many cards are left in the stock and how long
the current run is.

## Goal

Clear all 28 cards off the peaks onto the waste. The game is won as soon
as the last one goes, even with cards still in the stock.

## Moves

- A card is free once neither of the two cards overlapping it is left,
  and it turns face up then. Where two peaks meet, one card in the
  bottom row overlaps a card in each.
- A free card goes on the waste if it is one rank above or below the
  waste's top card, in any suit. The ranks wrap round: an Ace goes on a
  King or a 2, and a King goes on an Ace or a Queen. A run can change
  direction as often as you like.
- You can turn the next stock card onto the waste at any time: press d
  or click the stock, or type d in text mode. The stock is turned one
  card at a time and there is no redeal.
- Click a free card that goes on the waste, or press Enter or f on it,
  to play it.
- Nothing moves between the peaks, and nothing comes back off the waste.

## Scoring

Each card you play scores the number of cards played since the stock
was last turned, so a run of five scores 1 + 2 + 3 + 4 + 5 = 15.

- Turning a stock card costs 5 points, and the score never goes below
  0.
- Clearing the top card of a peak scores 15, for each of the three.
- Clearing the whole board scores another 15.

The best possible game plays all 28 cards in one run for 406, plus 45
for the peaks and 15 for the clear, which makes 466.

With multiplier scoring, each card of a run is worth twice the one
before it: 1, 2, 4, 8 and 16, so a run of five scores 31. The bonuses
are 25 each, and turning a stock card costs nothing.

The cards turned face down on the waste are the ones from runs that are
over. The face-up cards on top of them are the current run. This all
matches AisleRiot.

## Options

Open the options screen with o during a game. Using it ends the game in
progress (which counts as a loss if you'd made a move) and starts a new
deal with your settings, which are remembered for next time.

- **Scoring**: standard or multiplier, default standard, as described
  above. It doesn't change the cards: a deal number deals the same hand
  either way.

A share code sets the scoring too, as in `soliterm --deal
triplepeaks:sm:5` for deal 5 with multiplier scoring. AisleRiot's
Progressive Rounds option, which deals a fresh board after a clear and
carries the score on, isn't offered.

## Tips

- Count the chain before you play. The first card of a run is the cheap
  one, and every card you add is worth more than the last.
- Prefer the play that frees a card. A bottom-row card whose neighbour
  is already gone uncovers the card above it.
- With multiplier scoring, one long run beats several short ones by a
  lot. Hold back an easy play if it would break a longer chain.
- The peaks' top cards are worth 15 each (25 with multiplier scoring),
  so a game that clears two peaks and then gets stuck still scores well.
