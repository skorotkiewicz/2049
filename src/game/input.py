"""Keyboard input: single keypress, POSIX + Windows."""

from __future__ import annotations

import sys

_ARROW_MAP = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
}


def _read_posix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        # Not a TTY (piped input): read a line, take its first char.
        line = sys.stdin.readline()
        return line[:1]
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":  # escape sequence: drain it (non-blocking-ish)
            import select

            seq = ch
            while select.select([sys.stdin], [], [], 0.01)[0]:
                nxt = sys.stdin.read(1)
                if not nxt:
                    break
                seq += nxt
            return seq
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_windows() -> str:
    import msvcrt

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        ext = msvcrt.getwch()
        return {"H": "\x1b[A", "P": "\x1b[B", "C": "\x1b[C", "D": "\x1b[D"}.get(ext, "")
    return ch


def read_key() -> str:
    """Return a normalized key name: 'up'/'down'/'left'/'right'/literal."""
    read = _read_windows if sys.platform == "win32" else _read_posix
    try:
        raw = read()
    except (KeyboardInterrupt, EOFError):
        return "q"
    if raw in _ARROW_MAP:
        return _ARROW_MAP[raw]
    if raw == "":  # EOF / closed stdin -> quit
        return "q"
    return raw
