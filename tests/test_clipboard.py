"""Copying for y: the bytes that ask the terminal to copy, as they go under
tmux, under GNU screen and with neither, and the Win32 calls on Windows,
made here on a stand-in for user32 and kernel32. And that what it says
fits the message line."""

import ctypes
import itertools
import os
import sys

import pytest

from soliterm import clipboard
from soliterm.deals import share_code
from soliterm.engine import GAME_ORDER, GAMES, MAX_DEAL
from soliterm.tui.app import NOTE_WIDTH

from helpers import FakeWin32

CODE = "klondike:d3:48213"
# OSC 52 for the clipboard, the code in base64, and BEL
PLAIN = b"\x1b]52;c;a2xvbmRpa2U6ZDM6NDgyMTM=\x07"
# and that inside the DCS string screen passes on
SCREEN = b"\x1bP" + PLAIN + b"\x1b\\"


def test_the_code_goes_as_osc52_with_no_multiplexer():
    assert clipboard.osc52(CODE, {}) == PLAIN


def test_tmux_takes_the_sequence_as_it_is():
    assert clipboard.osc52(CODE, {"TMUX": "/tmp/tmux-1000/default,1234,0"}) == PLAIN


def test_screen_is_passed_it_inside_a_dcs_string():
    assert clipboard.osc52(CODE, {"STY": "1234.pts-0.host"}) == SCREEN


def test_tmux_and_screen_one_inside_the_other_are_passed_it_as_screen_is():
    env = {"STY": "1234.pts-0.host", "TMUX": "/tmp/tmux-1000/default,1234,0"}
    assert clipboard.osc52(CODE, env) == SCREEN


def test_an_empty_tmux_or_sty_is_not_one():
    assert clipboard.osc52(CODE, {"TMUX": "", "STY": ""}) == PLAIN


def test_the_text_goes_as_utf8():
    assert clipboard.osc52("♠ A", {}) == b"\x1b]52;c;4pmgIEE=\x07"


@pytest.fixture
def terminal(monkeypatch):
    """A pipe standing in for the terminal. Call it for what was written."""
    read, write = os.pipe()
    monkeypatch.setattr(clipboard, "TERMINAL", write)

    def written():
        os.close(write)
        with os.fdopen(read, "rb") as f:
            return f.read()

    return written


@pytest.mark.parametrize(
    "env, sent, said",
    [
        ({}, PLAIN, f"sent {CODE} to the terminal to copy, if it can"),
        ({"TMUX": "x"}, PLAIN, f"sent {CODE} to tmux to copy, if set-clipboard is on"),
        ({"STY": "x"}, SCREEN, f"sent {CODE} to the terminal to copy, if it can"),
    ],
    ids=["plain", "tmux", "screen"],
)
def test_the_sequence_is_written_to_the_terminal(terminal, env, sent, said):
    assert clipboard.copy_by_terminal(CODE, CODE, env) == said
    assert terminal() == sent


def test_a_short_write_is_finished(terminal, monkeypatch):
    real = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: real(fd, data[:5]))
    clipboard.copy_by_terminal(CODE, CODE, {})
    assert terminal() == PLAIN


def broken_pipe():
    """A pipe's end with nothing to read from it, as a terminal that's gone
    leaves. Writing to it fails."""
    read, write = os.pipe()
    os.close(read)
    return write


def test_a_terminal_that_is_gone_is_said(monkeypatch):
    gone = broken_pipe()
    monkeypatch.setattr(clipboard, "TERMINAL", gone)
    said = clipboard.copy_by_terminal(CODE, "the share code", {})
    os.close(gone)
    assert said == "couldn't send the share code to the terminal to copy"


def test_copy_goes_to_the_terminal_off_windows(terminal, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    assert clipboard.copy(CODE, CODE) == f"sent {CODE} to the terminal to copy, if it can"
    assert terminal() == PLAIN


# ---- Windows, on a stand-in ---- #


@pytest.fixture
def win32(monkeypatch):
    """A FakeWin32 for copy() to find on "Windows", with the waits between
    tries written down instead of slept. Call it with FakeWin32's own
    arguments first."""
    waits = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(clipboard.time, "sleep", waits.append)

    def make(**kw):
        fake = FakeWin32(**kw)
        fake.waits = waits
        monkeypatch.setattr(clipboard, "win32", fake)
        return fake

    return make


def test_the_clipboard_calls_go_in_order(win32):
    fake = win32()
    assert clipboard.copy(CODE, CODE) == f"copied {CODE} to the clipboard"
    data = (CODE + "\0").encode("utf-16-le")
    h = FakeWin32.HANDLE
    assert fake.calls == [
        ("OpenClipboard", None),
        ("EmptyClipboard",),
        ("GlobalAlloc", clipboard.GMEM_MOVEABLE, len(data)),
        ("GlobalLock", h),
        ("GlobalUnlock", h),
        ("SetClipboardData", clipboard.CF_UNICODETEXT, h),
        ("CloseClipboard",),
    ]
    assert fake.pasted == CODE + "\0"
    assert fake.waits == []


def test_a_clipboard_in_use_is_tried_again(win32):
    fake = win32(busy=3)
    assert clipboard.copy(CODE, CODE) == f"copied {CODE} to the clipboard"
    assert fake.names()[:5] == ["OpenClipboard"] * 4 + ["EmptyClipboard"]
    assert fake.waits == [clipboard.OPEN_WAIT] * 3
    assert fake.pasted == CODE + "\0"


def test_a_clipboard_in_use_for_good_is_said(win32):
    fake = win32(busy=100)
    said = clipboard.copy(CODE, "the share line")
    assert said == "couldn't copy the share line: the clipboard is in use"
    # never opened, so never closed
    assert fake.names() == ["OpenClipboard"] * clipboard.OPEN_TRIES
    assert fake.waits == [clipboard.OPEN_WAIT] * (clipboard.OPEN_TRIES - 1)


def test_a_clipboard_that_will_not_open_for_another_reason_is_said(win32):
    win32(fails="OpenClipboard", error=1400)
    said = clipboard.copy(CODE, "the share code")
    assert said == "couldn't copy the share code to the clipboard (error 1400)"


def test_memory_the_clipboard_did_not_take_is_freed_and_the_clipboard_closed(win32):
    fake = win32(fails="SetClipboardData", error=1418)
    said = clipboard.copy(CODE, CODE)
    assert said == f"couldn't copy {CODE} to the clipboard (error 1418)"
    h = FakeWin32.HANDLE
    assert fake.calls[-3:] == [
        ("SetClipboardData", clipboard.CF_UNICODETEXT, h),
        ("GlobalFree", h),
        ("CloseClipboard",),
    ]


def test_memory_that_would_not_lock_is_freed(win32):
    fake = win32(fails="GlobalLock")
    assert clipboard.copy(CODE, CODE) == f"couldn't copy {CODE} to the clipboard (error 8)"
    assert fake.names()[-3:] == ["GlobalLock", "GlobalFree", "CloseClipboard"]
    assert "SetClipboardData" not in fake.names()


@pytest.mark.parametrize("fails", ["EmptyClipboard", "GlobalAlloc"])
def test_a_failure_before_there_is_memory_to_free_still_closes(win32, fails):
    fake = win32(fails=fails)
    assert clipboard.copy(CODE, CODE) == f"couldn't copy {CODE} to the clipboard (error 8)"
    assert fake.names()[-2:] == [fails, "CloseClipboard"]
    assert "GlobalFree" not in fake.names()


def test_the_clipboard_is_closed_whatever_goes_wrong(win32):
    fake = win32()

    def mistyped(*args):
        raise ctypes.ArgumentError

    fake.kernel32.GlobalAlloc = mistyped
    with pytest.raises(ctypes.ArgumentError):
        clipboard.copy(CODE, CODE)
    assert fake.names()[-1] == "CloseClipboard"


def test_text_beyond_ascii_goes_as_utf16(win32):
    text = "Soliterm daily 2026-09-24, Klondike: won ♠ in 3:12 \U0001f0a1"
    fake = win32()
    clipboard.copy(text, "the share line")
    assert fake.pasted == text + "\0"
    # the ace outside the BMP takes two UTF-16 units, and the NUL one
    assert fake.calls[2][2] == 2 * (len(text) + 2)


def test_the_win32_api_is_only_looked_for_on_windows():
    if sys.platform == "win32":
        pytest.skip("this is Windows")
    with pytest.raises(OSError, match="only on Windows"):
        clipboard.win32()


@pytest.mark.skipif(sys.platform != "win32", reason="the Win32 API is only on Windows")
def test_every_win32_function_is_typed():
    user32, kernel32, _ = clipboard.win32()
    for dll, names in (
        (user32, ["OpenClipboard", "EmptyClipboard", "SetClipboardData", "CloseClipboard"]),
        (kernel32, ["GlobalAlloc", "GlobalLock", "GlobalUnlock", "GlobalFree"]),
    ):
        for name in names:
            fn = getattr(dll, name)
            assert fn.argtypes is not None, name
            assert fn.restype is not None, name


# ---- what it says ---- #


def longest_code():
    """The longest share code of all: every game with every option, and the
    highest deal number."""
    codes = []
    for key in GAME_ORDER:
        spec = GAMES[key].option_spec()
        names = [name for name, _, _ in spec]
        for values in itertools.product(*(vals for _, _, vals in spec)):
            codes.append(share_code(key, MAX_DEAL, dict(zip(names, values))))
    return max(codes, key=len)


@pytest.mark.parametrize("what", [longest_code(), "the share line", "the share code"])
def test_every_message_fits_the_message_line(win32, monkeypatch, what):
    said = set()
    null, gone = os.open(os.devnull, os.O_WRONLY), broken_pipe()
    try:
        for fd, env in ((null, {}), (null, {"TMUX": "x"}), (gone, {})):
            monkeypatch.setattr(clipboard, "TERMINAL", fd)
            said.add(clipboard.copy_by_terminal(CODE, what, env))
    finally:
        os.close(null)
        os.close(gone)
    for kw in ({}, {"busy": 100}, {"fails": "OpenClipboard", "error": 99999}):
        win32(**kw)
        said.add(clipboard.copy(CODE, what))
    assert len(said) == 6
    assert max(len(s) for s in said) <= NOTE_WIDTH, max(said, key=len)
