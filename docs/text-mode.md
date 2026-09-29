# Text mode

Text mode plays every game as plain lines of text. It prints the board,
reads one command, prints the board again, and so on until the game is
over or the input runs out. There's no cursor movement and no curses in
it, so it works in a pipe, in a script, in a terminal curses can't drive,
and in a test.

For the full-screen game's keys, see [keybindings.md](keybindings.md).

## When it starts

Soliterm plays in text mode when:

- you ask for it with `--text`;
- its input or its output isn't a terminal, because commands are piped
  in or the board is going to a file or another program;
- curses can't be loaded, as on a Windows Python without the
  windows-curses package;
- off Windows, `TERM` isn't set, is `dumb`, names a terminal type this
  system has no terminfo entry for, or names one that can't move the
  cursor.

In the last two cases it says why on stderr before it starts, for
example:

```text
soliterm: TERM=dumb can't move the cursor, so playing in text mode; set TERM to your terminal's type (xterm-256color suits most) for the full-screen game
```

The game to play comes from the same options as the full-screen game:
`--game`, `--deal`, `--daily`, `--draw` and `--suits`. A share code
names its game, `--draw` means Klondike and `--suits` Spider. Otherwise
it's the game you last picked in the full-screen game, which is Klondike
until you've played there.

## The board

This is Klondike, deal 1, with `--ascii`:

```text
$ soliterm --text --deal klondike:1 --ascii
Soliterm - Klondike - Deal 1 (text mode). Type h for help.

=== Klondike ===
stk#0 wst#1 fnd#2 fnd#3 fnd#4 fnd#5
[###] [   ] [   ] [   ] [   ] [   ]
 (24)

   #6    #7    #8    #9   #10   #11   #12
[ 2C] [###] [###] [###] [###] [###] [###]
      [ 8D] [###] [###] [###] [###] [###]
            [10D] [###] [###] [###] [###]
                  [ AH] [###] [###] [###]
                        [ 9D] [###] [###]
                              [ 8S] [###]
                                    [ AD]

score=0 moves=0 | Stock: 24  Waste: 0  Redeals left: 2
```

The first line names the game and the deal. The board comes in rows, as
the full-screen game lays them out, and each slot has a tag above it:
what kind of slot it is and its number. Commands name a slot by that
number alone.

| Tag | Slot |
| --- | --- |
| `stk#0` | the stock, with the number of cards left in it underneath |
| `wst#1` | the waste |
| `fnd#2` | a foundation |
| `cel#0` | a free cell (FreeCell and Eight Off) |
| `rsv#6` | a reserve (Canfield) |
| `#9` | a tableau column, which needs no name as it's the usual case |

Each card is five characters wide:

- `[ 8D]` is a card face up: its rank, then its suit.
- `[###]` is a card face down.
- `[   ]` is an empty slot.

A tableau column lists its cards from the bottom of the pile to the top,
so the last card in a column is the one you can play. A pile that
doesn't spread, such as a foundation, shows only its top card. In Golf,
Triple Peaks, Canfield and Forty Thieves the waste fans out to the right
and shows its last four cards, the rightmost on top. Triple Peaks draws
its peaks where they sit, each card under its tag, and leaves out a slot
once it's empty.

The line at the bottom has the score, the number of moves and whatever
the game counts, such as the cards left in the stock or the free cells
still open. When you win it ends with `*** YOU WIN! ***`.

The suits are the symbols ♠ ♥ ♦ ♣, or the letters S H D C with
`--ascii`, and Soliterm uses the letters on its own when the output can't
show the symbols. At a terminal the cards are in colour, a white face
with red or black on it and a blue back, unless you give `--no-color` or
set `NO_COLOR`. `--color` turns the colour on even when the output isn't
a terminal.

## Commands

Type one command a line and press Enter. Upper and lower case are the
same, except for `n` and `N`. `h` lists them all:

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

After each command, Soliterm prints the board again. When a command
didn't do anything, a line above the board says why.

### Moving cards

`12 2` moves cards from slot 12 to slot 2. With no count, it moves the
longest run that slot 2 will take, the way dropping a run does in the
full-screen game. On the board above, that sends the Ace of Diamonds up
to its foundation:

```text
12 2
```

`11 10 1` moves exactly one card. A comma works in place of the space, so
`12,2` is the same move. A move the rules don't allow prints
`illegal move`, and a slot that isn't on the board says which ones are:

```text
99 2
no slot 99 (slots are 0-12)
```

### Dealing, clicking and sending up

- `d` deals from the stock, the way clicking it does. In Klondike it
  turns the waste back over once the stock is empty, while redeals are
  left. When there's nothing to deal, it says why.
- `c 0` clicks slot 0, and does whatever a click on that slot does in
  this game. `cc 9` double-clicks slot 9, which usually sends its top
  card up to a foundation. In Golf and Triple Peaks it plays the card to
  the waste instead. When a click does nothing it says so, as in
  `clicking fnd#5 does nothing`.
- `f 12` sends the top card of slot 12 up to its foundation, or says
  `no foundation move from #12`. Golf and Triple Peaks have no
  foundations, so there it plays the card to the waste as `cc` does, or
  says why not, as in `5♥ doesn't go on the waste`. Scorpion has none
  either, and says so.
- `a` sends up every card that's safe to send up, and says how many:
  `autoplayed 2`. Once every card left can go up, safe or not, it
  finishes the game instead. Either way it's one move, so one `u` takes
  it back.

### Hints

`hint` or `?` suggests a move, and gives the command to type for it:

```text
?
Hint: Move AD to its foundation  (#12 -> fnd#2, type: 12 2)
```

When the best thing to do is deal, it says `(type: d)`. When there's
nothing left to do, it says why.

### Undo, restart and a new deal

- `u` takes back the last move and `r` makes it again. `undo all` goes
  all the way back to the deal, and `redo all` forward again. A kept game
  takes its newest 500 undo steps with it, so in a longer one you've
  resumed, `undo all` stops short of the deal and says
  `back to the oldest move saved`.
- `N` or `restart` deals the same cards again as a fresh game. As in
  AisleRiot, starting a deal over doesn't count as a loss.
- `n` or `new` deals a new game. After a numbered deal it's the next
  number, so deal 1 goes on to deal 2, and otherwise it's a random one. A
  game you've made a move in counts as lost.

### Everything else

- `p`, `.` or `print` prints the board again.
- `b` or `boss` prints a screenful of something that looks like work,
  such as a build log, and at a terminal clears the screen and its
  scrollback first. The kind of work is the one boss mode was last left
  on in the full-screen game. Type `p` to see the board again.
- `q`, `quit` or `exit` leaves. So does the end of the input, which is
  Ctrl-D at a terminal, or Ctrl-Z and then Enter in a Windows console.
- Anything else prints `bad command: 'foo' (try h)`.

## Deal numbers and share codes

The first line says which deal it is: `Deal 1`, or
`Daily 2026-09-24` for the daily deal. `--deal` plays a deal again, and
takes either a number or a share code:

```text
soliterm --text --game golf --deal 216
soliterm --text --deal golf:216
soliterm --text --deal klondike:d3:48213
```

A share code carries the game and its options with it, so
`klondike:d3:48213` is Klondike drawing three whatever you usually play.
A bare number plays with your own options for that game. When you win,
text mode prints the deal's share code so you can pass it on:

```text
Congratulations - you won!
Score 35 in 2:11 (48 moves).
Share code: golf:216
```

A win of the daily deal also gets the line to share that the full-screen
game prints, the one that names no cards.

## Keeping a game for later

When you're typing at a terminal, text mode keeps a game you've started
the way the full-screen game does. Leave it with `q`, Ctrl-D or Ctrl-C and
it's saved instead of counting as lost:

```text
q
Saved your Golf game (0:02, 1 move).
Run soliterm --text --game golf to pick it up.
bye
```

Starting that game again with the command it names, without a deal number
or options, carries on where you left off:

```text
Soliterm - Golf - Deal 286262 (text mode). Type h for help.
Resumed your Golf game (0:02, 1 move). Type n for a new deal.
```

The saved game is the same one the full-screen game would resume, and the
other way round. Asking for a particular deal or options starts afresh
and leaves the save waiting, and text mode says so as it starts, and
again after each `n`:
`a saved Golf game is waiting, so this one won't be kept`. While that
saved game is being played in another window, it says this instead:
`a saved Golf game is being played somewhere else, so this one won't be kept`.

When the commands come from a pipe or a file, nothing is kept. A game
left unfinished when the input runs out counts as lost, as long as it had
a move made in it, and one nobody touched doesn't count at all.

On Windows, closing the console window keeps the game too, and so does
Ctrl-Break. Ended some other way, as `taskkill /f` does, Soliterm can't
keep or count the game, though if you'd picked it up from a save, that
save is offered again next time, as it was when you picked it up.

## Exit status

| Status | When |
| --- | --- |
| 0 | the game was won, or you left with `q`, or the input ran out |
| 2 | the command line was wrong, such as `--deal` with a code that isn't one |
| 130 | Ctrl-C, or the terminal closing (SIGHUP), or SIGTERM, or Ctrl-Break on Windows |
| 141 | whatever was reading the output stopped, as `head` does |

A game leaving on 130 is saved or counted just as it is for `q`.
On Windows, closing the console window still ends Soliterm with status
0xC000013A, but only once the game has been kept or counted.

## Scripting

Every game played in text mode counts in your statistics, and in
AisleRiot's when they're shared, whether a person or a script is typing.
On Linux, if AisleRiot is open while they're shared, a line on stderr
says so before the first board, since AisleRiot can write over the games
finished here as it quits. The output itself is the same either way.
For experiments, `--no-sync` leaves AisleRiot's alone, and pointing
`XDG_CONFIG_HOME` and `XDG_DATA_HOME` at a scratch directory keeps
Soliterm's own files out of it as well.

This plays Golf deal 216 through to a win. `printf '%s\n'` writes each of
its arguments on a line of its own, and the comma saves quoting a space:

```sh
printf '%s\n' d d 2,1 2,1 8,1 2,1 5,1 2,1 4,1 7,1 3,1 3,1 4,1 d 7,1 8,1 \
    7,1 d d 5,1 5,1 3,1 d 8,1 d d 6,1 3,1 6,1 5,1 8,1 7,1 4,1 d 6,1 5,1 \
    d 3,1 7,1 8,1 d 4,1 4,1 6,1 d 2,1 d 6,1 |
  soliterm --text --deal golf:216 --ascii | tail -n 12
```

With `XDG_CONFIG_HOME` and `XDG_DATA_HOME` pointing at a new, empty
directory, it prints exactly this. Run it again and it ends with a line
about your win streak as well, since the first win counted.

```text
=== Golf ===
stk#0                   wst#1
[###] [ 8H] [ 7C] [ QD] [ KD]
  (4)

   #2    #3    #4    #5    #6    #7    #8
[   ] [   ] [   ] [   ] [   ] [   ] [   ]

score=35 moves=48 | Stock: 4 left  *** YOU WIN! ***
Congratulations - you won!
Score 35 in 0:00 (48 moves).
Share code: golf:216
```

A script can look for `*** YOU WIN! ***`, or read the last status line,
to see how it went. The commands in `h` are kept as they are for
exactly this, so a script written today keeps working.
