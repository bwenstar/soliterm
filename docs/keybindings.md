# Keys

<!-- Written by tools/keybindings.py. Edit that, not this file, and run
     python tools/keybindings.py to bring this page up to date. -->

Everything in Soliterm is a key or two away, and most of it is a click
away too. On the board, `?` shows the same keys as the first table here.
This page also has the other screens, the mouse and text mode.

## On the board

| Keys | What they do |
| --- | --- |
| `Up`, `k`, `Down`, `j`, `Left`, `Right`, `l` | move between the slots (k up, j down, l right) |
| `Enter`, `Space` | pick up the cursor's run; press again to drop |
| `+`, `-` | lift one card more / fewer while holding a run |
| mouse click | pick up a card and those on it, then click a slot |
| mouse double-click | send a card to a foundation; deal on stock |
| `Esc` | cancel the current selection / clear hint |
| `d`, `D` | deal from the stock (where applicable) |
| `a`, `A` | autoplay safe cards, or finish once all can go up |
| `f`, `F` | send the selected/cursor card to a foundation |
| `h`, `H` | show a hint (highlights a legal move) |
| `b`, `B`, `F2` | boss mode: hide any screen behind 'work' |
| `c`, `C` | code skin: keep playing inside a code file |
| `v`, `V`, `t`, `T`, `4` | toggle colour / next theme / four-colour deck |
| `x`, `X` | toggle view: full cards <-> compact cells |
| `u`, `U`, `r`, `R` | undo / redo a move; U and R go all the way |
| `n` | new deal |
| `N` | restart this deal |
| `g`, `G` | pick deal |
| `y`, `Y` | copy share code |
| `p`, `P` | pause |
| `o`, `O` | options |
| `s`, `S` | statistics |
| `?` | help |
| `m`, `M` | menu |
| `q`, `Q` | quit |

`k`, `j` and `l` move up, down and right, as they do in vi. vi's `h` for
left is the hint here, so left has only its arrow key.

In Golf and Triple Peaks, which have no foundations, `Enter`, `Space`,
`f` and `F` play the card at the cursor onto the waste if it goes there.

## The other screens

The boss key (`b`, `B` or `F2`) works on every screen. The one exception
is the Play a deal box, where `b` could be part of what you're typing, so
only `F2` works there.

### The menu

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move up and down the list |
| `PgUp` / `PgDn` | move a page up or down |
| `Home` / `End` | go to the first game or to Quit |
| `Enter` | play the game, or open Daily deal, Play a deal or View statistics |
| `q`, `Q` | quit |

A game with a save waiting says so on its row, and picking it carries on
where you left off.

In a terminal too short for every game, the games scroll, and a line
above or below them says how many more there are that way. Daily deal,
Play a deal, View statistics and Quit stay where they are under them.

### Daily deals

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move up and down the games |
| `PgUp` / `PgDn` | move a page up or down |
| `Home` / `End` | go to the first or the last game |
| `Enter` | play that game's daily deal |
| `Esc`, `q`, `Q` | back to the menu |

The games scroll here too when the terminal is too short for them all.

### Play a deal

`g` opens this box during a game, and so does Play a deal on the menu.

| Keys | What they do |
| --- | --- |
| typing | a deal number or a share code, up to 64 characters |
| `Backspace` | take the last character off |
| `Ctrl-U` | clear the line |
| `Enter` | play it, or go back if nothing is typed |
| `Esc` | go back |

A number on its own plays that deal of the game in play, with the options
it has now. From the menu, it plays that deal of the game you played last.
A board's whole title line, pasted in, works as well.

### Options

`o` opens the options of the game in play, for the games that have any.

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move between the options |
| `Left`, `Right`, `Space` | change the one you're on |
| `Enter`, `q`, `Q` | keep the changes and deal again with them |
| `Esc` | leave everything as it was |

### Statistics

The game in play is picked out, or the first game when they're opened
from the menu, and the games scroll as they do on the menu.

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move up and down the games |
| `PgUp` / `PgDn` | move a page up or down |
| `Home` / `End` | go to the first or the last game |
| any other key | close the statistics |

The mouse doesn't close them, so the pointer passing over the window
can't.

### Help

Any key closes it. In a terminal too short for it all, it scrolls
instead with the keys that move up and down the statistics, and a line
above or below says how many more there are that way. Any other key
closes it then. The mouse doesn't, so the pointer passing over the
window can't.

### The pause

`p` hides the board and stops the clock, and says how long the game has
been played. Any key or a left click goes back to the game. The pointer
passing over the window, the wheel and a resize don't. A game left from
here, as when the terminal is closed, keeps the time played up to the
pause.

### Copying

`y` copies the share code of the deal in play, and at the end of a daily
the share line. On Windows it goes on the clipboard. Anywhere else
Soliterm asks the terminal to copy it, with the escape sequence OSC 52,
and the message says only that it asked, as not every terminal takes it.
In tmux it takes `set -g set-clipboard on`. Under GNU screen it goes
through screen to the terminal outside.

### Leaving a game under way

When `g` or a change of options would end a game you've started, Soliterm
asks first, since the game would count as lost.

| Keys | What they do |
| --- | --- |
| `y`, `Y` | yes: count it as lost and go on |
| `n`, `N`, `Esc`, `q`, `Q`, `Enter` | no: keep playing |

Enter says no, so one Enter too many can't give a game away.

### The end of a game

| Keys | What they do |
| --- | --- |
| `Up`, `k` / `Down`, `j` | move between the choices |
| `Enter`, `Space` | take the choice you're on |
| `u`, `U` | undo the last move (when no moves are left, not after a win) |
| `s`, `S` | replay this deal |
| `n`, `N` | a new deal |
| `m`, `M`, `q`, `Q` | back to the menu |
| `y`, `Y` | copy the share code, or on a daily the share line |

A left click on a choice takes it.

### The finish and the win

When `a` sends the last cards up one at a time, or the cards bounce off
the board after a win, any key or a left click skips the rest. The boss
key skips it too and hides the screen straight away.

### Boss mode

`b`, `B` or `F2` hides whatever is on screen behind something that looks
like work, and the clock stops until you come back.

| Keys | What they do |
| --- | --- |
| `Tab` | cycle the disguise; any other key goes back |

Moving the mouse or resizing the window doesn't bring the game back.

### A terminal too small for the board

Soliterm says how big the board needs the terminal to be, and until it
is, only `b`, `B`, `F2`, `c`, `C`, `x`, `X`, `q` and `Q` do anything, so
no key can make a move you can't see. `c` and `x` change the size the
board needs, so they can bring it back. A menu or a dialog that doesn't
fit takes only `q` and the boss key.

## The mouse

Soliterm listens to the left button and the wheel. The pointer moving
over the window does nothing, and the wheel does nothing on the board.

- Click a card to pick it up, along with every card below it, then click
  where it should go. Click the same pile again to put it back. In Golf
  and Triple Peaks, a click on a card that goes on the waste plays it
  there instead.
- Click the stock to deal.
- Or press on a card, drag and let go over another pile.
- Double-click a card to send it up to its foundation, or double-click the
  stock to deal. In Golf and Triple Peaks it plays the card to the waste,
  just the one, as a click does.
  Two clicks on the same pile within 0.4 seconds count as a double-click.
  Some games do more with a double-click, and each game's page in
  [docs/games](games/README.md) says what.
- On the menu, the daily deals and the end of a game, click a row to pick
  it. On the statistics, a click picks out a game's row.
- On the menu, the daily deals and the statistics, the wheel moves up and
  down the list, and it scrolls the help where the help is too long for
  the terminal. Where they scroll, a click on the line saying how many
  more there are moves a page that way.

A terminal has to pass mouse clicks on for any of this to work. Most do,
and in tmux it takes `set -g mouse on`.

## Text mode

Text mode reads one command a line. `h` prints this list, and
[text-mode.md](text-mode.md) has the rest.

```text
Text-mode commands. A slot is named by the number in its tag on the board,
so stk#0 is 0, fnd#4 is 4 and #9 is 9:
  p / .            reprint the board
  d                deal from the stock
  a                autoplay safe cards, or finish once all can go up
  <src> <dst>      move the longest run from slot src that dst takes, e.g.  9 12
  <src> <dst> <n>  move exactly n cards
  c <slot>         click a slot (deal / play, game-specific)
  cc <slot>        double-click a slot (send to foundation)
  f <slot>         send the slot's top card to its foundation
  hint / ?         suggest a legal move (shows the slot ids to use)
  b / boss         boss mode: print fake 'work' output to hide the game
  u  undo   r  redo   n  new deal
  undo all         take back every move, back to the deal
  redo all         redo every move taken back
  N / restart      start this deal over
  h / help         this help
  q                quit
```
