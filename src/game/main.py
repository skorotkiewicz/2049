"""Main game loop for 2049 -- Mines of Merge."""

from __future__ import annotations

import sys

from . import input as input_mod
from .core import new_game
from .ui import render

CLEAR = "\x1b[2J\x1b[H"


def main() -> int:
    print(CLEAR, end="")
    while True:
        g = new_game()
        while True:
            sys.stdout.write(CLEAR + render(g) + "\n")
            sys.stdout.flush()
            if g.game_over:
                key = input_mod.read_key()
                if key in ("q", "Q", "\x03"):
                    return 0
                if key in ("r", "R"):
                    break  # new run
                continue
            key = input_mod.read_key()
            if key in ("q", "Q", "\x03"):
                return 0
            if key in ("up", "down", "left", "right"):
                g.move(key)


if __name__ == "__main__":
    raise SystemExit(main())
