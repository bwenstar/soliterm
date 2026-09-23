# Klondike

The solitaire most people know: one deck, seven columns and a stock to
work through. Luck plays a big part, so some deals can't be won however
well you play, and drawing three cards at a time is harder than drawing
one.

## The deal

- Seven columns make up the tableau. The first gets one card, the second
  two, and so on up to seven in the last, 28 cards in all. Only the top
  card of each column is face up.
- The other 24 cards go face down in the stock. The waste beside it and
  the four foundations start empty.

## Goal

Get all 52 cards onto the four foundations, one suit to each, built up
from Ace to King.

## Moves

- Build down the columns in alternating colours: a red 6 goes on a black
  7, and a black 6 on a red 7.
- You can lift any face-up card along with the cards covering it, as
  long as they all run down in alternating colours. There's no limit on
  how many.
- An empty column will only take a King, along with any run built on it.
- When you uncover a face-down card, it turns over by itself.
- Foundations build up by suit, starting with the Ace. Cards go up one
  at a time, from the waste or from the top of a column. Double-click a
  card, or press f, to send it to its foundation. Doing the same on a
  foundation sends up everything that will go, which is handy for
  finishing a game off quickly.
- The top card of a foundation can come back down onto a column where it
  fits, which is sometimes the only way to free a card. It can't move
  across to another foundation.
- Dealing from the stock turns one card, or three, onto the waste,
  depending on the Cards to draw option (fewer if that's all the stock
  has left). Only the top card of the waste can be played.
- When the stock is empty, dealing again turns the whole waste back over
  into the stock, in the same order. That's a redeal. How many you get
  depends on the Redeals option, and when there's a limit the status
  line shows how many are left.

Autoplay, when you ask for it, only sends a card up once nothing still
in play could want to be built on it. A red 5 waits until both black 4s
are on the foundations, for example. Aces and 2s always go.

## Scoring

You get a point for each card you put on a foundation and lose one when
a card comes back down, so your score is simply the number of cards on
the foundations. A win scores 52. Redeals and turning cards over neither
earn nor cost anything. This is the same scoring AisleRiot uses.

## Options

Open the options screen with o during a game. Using it ends the game in
progress (which counts as a loss if you'd made a move) and starts a new
deal with your settings, which are remembered for next time.

- **Cards to draw**: 1 or 3, default 1. How many cards each deal turns
  from the stock onto the waste.
- **Redeals**: standard, none or unlimited, default standard. How many
  times the waste can go back into the stock.
  - standard is AisleRiot's rule: two redeals when drawing one card, so
    three trips through the stock, and no limit when drawing three.
  - none means no redeals at all, so one trip through the stock whichever
    draw you choose. AisleRiot's no-redeal game draws one card, so
    drawing three with no redeals is a Soliterm extra.
  - unlimited lets you turn the waste back as often as you like. When
    drawing three this plays just like standard, since both leave the
    redeals unlimited.

## Tips

- Go after the face-down cards. Given a choice, make the move that turns
  a card over, and favour the columns with the most cards still hidden.
- Pick your King with care when a column comes free. If a red Queen is
  stuck with nowhere to go, a black King gives it a home.
- Don't rush every card to the foundations. A black 4 sent up early is
  one less place for a red 3 to go. If you do need it back, the top card
  of a foundation can come down again for the price of a point.
- Drawing three, what you can reach depends on what you've already taken
  off the waste. If a whole pass turns up nothing useful, playing just
  one card from the waste shifts every group of three after it, so the
  next pass shows you different cards.
