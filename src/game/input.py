"""Keyboard input: single keypress, POSIX + Windows.

Robust against:
- escape sequences split across reads (slow terminals, SSH, WSL):
  bytes are buffered until a full sequence arrives
- both arrow encodings (CSI "\\x1b[A" and SS3 "\\x1bOA")
- wasd / hjkl alternatives
- non-TTY stdin (piped/IDE): falls back to line input and parses it
- unknown escape sequences are consumed silently instead of leaking garbage
"""

from __future__ import annotations

import sys

_ARROW_MAP = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
    # application-keypad mode (SS3) variants
    "\x1bOA": "up",
    "\x1bOB": "down",
    "\x1bOC": "right",
    "\x1bOD": "left",
}

_CHAR_MAP = {
    "h": "left",
    "j": "down",
    "k": "up",
    "l": "right",
    "w": "up",
    "s": "down",
    "a": "left",
    "d": "right",
}

_QUIT = {"q", "Q", "\x03"}  # q / Ctrl-C

# Buffer that survives across read_key() calls so split sequences
# (\x1b | [ | C in three separate reads) still assemble into one arrow.
_buf = ""


def _normalize(raw: str) -> str:
    if raw in _ARROW_MAP:
        return _ARROW_MAP[raw]
    if raw in _CHAR_MAP:
        return _CHAR_MAP[raw]
    if raw in _QUIT:
        return "q"
    if raw == "":  # EOF / closed stdin -> quit
        return "q"
    return raw


def _take_key(buf: str) -> tuple[str | None, str]:
    """Extract one logical key from the front of `buf`.

    Returns (key_or_None, rest). None means "need more bytes".
    "" (empty string) as key means "ignore this, continue".
    """
    if not buf:
        return None, buf

    # Longest known sequence wins.
    for seq in sorted(_ARROW_MAP, key=len, reverse=True):
        if buf.startswith(seq):
            return _ARROW_MAP[seq], buf[len(seq):]

    if buf[0] != "\x1b":
        return buf[0], buf[1:]

    # Escape sequence. Is it complete enough to judge?
    if len(buf) < 3 and buf[1:2] in ("", "[", "O"):
        return None, buf  # maybe more bytes coming; wait for them

    if buf[1] in "[O" and len(buf) >= 3:
        final = buf[2]
        if final.isalpha() or final == "~":
            return "", buf[3:]  # complete but unknown -> ignore silently
        # e.g. "\x1b[1~": consume digits until the "~" terminator
        rest = buf[3:]
        while rest and rest[0].isdigit():
            rest = rest[1:]
        if rest.startswith("~"):
            rest = rest[1:]
        return "", rest

    # "\x1b" + some other char (Alt+key): ignore both.
    return "", buf[2:]


def _read_posix() -> str:
    import os
    import select
    import termios
    import tty

    global _buf

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        return _parse_line(sys.stdin.readline())
    try:
        tty.setraw(fd)
        # NOTE: read the raw fd via os.read, NOT sys.stdin.read().
        # sys.stdin is a TextIOWrapper whose internal buffer swallows
        # whole escape sequences on the first read(1), which makes
        # select() on the fd useless and shreds sequences into
        # orphaned fragments ('[', 'C', ...).
        while True:
            key, _buf = _take_key(_buf)
            if key is not None:
                return key
            if _buf.startswith("\x1b"):
                # Incomplete escape: briefly wait for the rest of it.
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    _buf = ""  # lone ESC, or the sender stopped: drop it
                    continue
                data = os.read(fd, 1024)
            else:
                data = os.read(fd, 1)  # nothing buffered: block for input
            if not data:
                return "q"  # EOF
            _buf += data.decode("latin-1")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_windows() -> str:
    import msvcrt

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        ext = msvcrt.getwch()
        return {"H": "\x1b[A", "P": "\x1b[B", "C": "\x1b[C", "D": "\x1b[D"}.get(
            ext, ""
        )
    return ch


def _parse_line(line: str) -> str:
    """Line-mode fallback (stdin is not a TTY, e.g. IDE/piped input)."""
    line = line.strip()
    if not line:
        return ""  # blank line -> just re-render
    for seq, name in _ARROW_MAP.items():
        if seq in line:
            return name
    low = line.lower()
    if low in ("quit", "exit"):
        return "q"
    for word, name in (
        ("up", "up"),
        ("down", "down"),
        ("left", "left"),
        ("right", "right"),
    ):
        if word in low:
            return name
    return _normalize(line[:1])


def read_key() -> str:
    """Return a normalized key: 'up'/'down'/'left'/'right'/'q'/literal."""
    read = _read_windows if sys.platform == "win32" else _read_posix
    try:
        raw = read()
    except (KeyboardInterrupt, EOFError):
        return "q"
    return _normalize(raw)
