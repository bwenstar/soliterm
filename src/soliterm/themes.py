"""soliterm.themes - the colours the full-screen game draws in.

The colour pairs are numbered here, by what they draw, away from curses, so
the command line can know about them without importing curses.
"""

from __future__ import annotations

# the colour pairs, by what they draw
FACE_RED = 1  # a heart or a diamond: red on the white card face
FACE_BLACK = 2  # a spade or a club: black on the white card face
SELECTED = 3  # the run picked up
CHROME = 4  # titles, labels, empty slots, the code skin's line numbers
CURSOR = 5  # the cursor, the selected menu row, the code skin's tab
MESSAGE = 6  # the message line and headings
BACK = 7  # a face-down card
RED_SELECTED = 8  # a red card in the run picked up
HINT = 9  # a hinted card
