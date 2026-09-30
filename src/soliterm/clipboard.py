"""soliterm.clipboard - copies a share code or a daily's share line, for y.

On Windows the text goes on the clipboard through the Win32 API, called
with ctypes. Anywhere else the clipboard is out of reach without running
another program, which Soliterm never does, so it asks the terminal to
copy the text instead, with the escape sequence OSC 52. A terminal that
doesn't take OSC 52 should pass over it, as terminals do the strings of
its kind they don't know, and none answers to say whether it took it, so
what copy() says is only what it knows.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from collections.abc import Mapping
from typing import Any, Callable

# the Win32 values the clipboard calls take
GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13
ERROR_ACCESS_DENIED = 5  # OpenClipboard's error while another program has it open
# Another program can have the clipboard open for a moment, as a clipboard
# manager does each time it changes, so it's tried a few times over a
# fifth of a second before giving up.
OPEN_TRIES = 10
OPEN_WAIT = 0.02

TERMINAL = 1  # the file descriptor curses draws on, standard output


def copy(text: str, what: str) -> str:
    """Copy `text`, and say what came of it, naming the text as `what`
    (the share code itself, say, or "the share line"). What curses has
    drawn has to have gone out first, as a refresh leaves it."""
    if sys.platform == "win32":
        return copy_on_windows(text, what)
    return copy_by_terminal(text, what)


# ---- anywhere but Windows ---- #


def osc52(text: str, env: Mapping[str, str] = os.environ) -> bytes:
    """The bytes that ask the terminal to put `text` on the clipboard: OSC
    52 for the clipboard (c), with the text in base64 of its UTF-8.

    It ends in BEL rather than ST (ESC and a backslash). Every terminal
    that takes OSC 52 takes BEL, as xterm's first form, and only BEL can
    go inside the DCS string GNU screen passes on to the terminal outside
    it, where the ESC of an ST would end the DCS instead. Under screen,
    which keeps an OSC 52 to itself, it goes in one.

    tmux takes it as it comes, with set-clipboard on, into a paste buffer
    and on to the terminal outside. Wrapped in tmux's own passthrough it
    would need allow-passthrough, off by default, and would miss the paste
    buffer.

    With TMUX and STY both set, one runs inside the other, and nothing
    says which, so it goes in the DCS string as under screen alone. Screen
    inside tmux passes the OSC 52 on to tmux, and tmux inside screen ends
    the DCS string at the ESC of the OSC 52 and takes that as it would on
    its own. Sent both ways, it would land in tmux's buffers twice.
    """
    seq = b"\x1b]52;c;" + base64.b64encode(text.encode("utf-8")) + b"\x07"
    if env.get("STY"):
        seq = b"\x1bP" + seq + b"\x1b\\"
    return seq


def copy_by_terminal(text: str, what: str, env: Mapping[str, str] = os.environ) -> str:
    """Ask the terminal (or tmux, or screen) to copy `text`, and say so."""
    data = osc52(text, env)
    try:
        # straight to the terminal, past Python's buffering. It doesn't move
        # the cursor or change a cell, so curses' idea of the screen holds.
        while data:
            data = data[os.write(TERMINAL, data) :]
    except OSError:
        return f"couldn't send {what} to the terminal to copy"
    if env.get("TMUX"):
        return f"sent {what} to tmux to copy, if set-clipboard is on"
    return f"sent {what} to the terminal to copy, if it can"


# ---- Windows ---- #


def win32() -> tuple[Any, Any, Callable[[], int]]:
    """user32 and kernel32, with every function copy_on_windows calls
    typed, as a handle is 64 bits wide where ctypes would take a C int,
    and what reads the error the last of them left."""
    if sys.platform != "win32":
        raise OSError("the Win32 clipboard is only on Windows")
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # HANDLE, HWND, HGLOBAL and LPVOID; BOOL; UINT; SIZE_T
    handle, boolean, uint = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint
    for fn, argtypes, restype in (
        (user32.OpenClipboard, [handle], boolean),
        (user32.EmptyClipboard, [], boolean),
        (user32.SetClipboardData, [uint, handle], handle),
        (user32.CloseClipboard, [], boolean),
        (kernel32.GlobalAlloc, [uint, ctypes.c_size_t], handle),
        (kernel32.GlobalLock, [handle], handle),
        (kernel32.GlobalUnlock, [handle], boolean),
        (kernel32.GlobalFree, [handle], handle),
    ):
        fn.argtypes, fn.restype = argtypes, restype
    return user32, kernel32, ctypes.get_last_error


def copy_on_windows(text: str, what: str) -> str:
    """Put `text` on the Windows clipboard, and say whether it went."""
    user32, kernel32, last_error = win32()
    for tries in range(OPEN_TRIES):
        if tries:
            time.sleep(OPEN_WAIT)
        # no window of its own to own the clipboard, which it doesn't need
        if user32.OpenClipboard(None):
            break
    else:
        error = last_error()
        if error == ERROR_ACCESS_DENIED:
            return f"couldn't copy {what}: the clipboard is in use"
        return f"couldn't copy {what} to the clipboard (error {error})"
    try:
        failed = fill_clipboard(user32, kernel32, last_error, text)
    finally:
        user32.CloseClipboard()
    if failed is not None:
        return f"couldn't copy {what} to the clipboard (error {failed})"
    return f"copied {what} to the clipboard"


def fill_clipboard(
    user32: Any, kernel32: Any, last_error: Callable[[], int], text: str
) -> int | None:
    """Put `text` on the clipboard copy_on_windows has open. Returns None
    once it's there, or the error that stopped it."""
    import ctypes

    if not user32.EmptyClipboard():
        return last_error()
    data = (text + "\0").encode("utf-16-le")
    memory = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not memory:
        return last_error()
    at = kernel32.GlobalLock(memory)
    if at:
        ctypes.memmove(at, data, len(data))
        kernel32.GlobalUnlock(memory)
        if user32.SetClipboardData(CF_UNICODETEXT, memory):
            return None  # the clipboard has the memory now, and frees it
    error = last_error()
    kernel32.GlobalFree(memory)  # still this program's to free
    return error
