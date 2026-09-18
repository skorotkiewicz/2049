"""Main game loop for 2049 -- Mines of Merge."""

from __future__ import annotations

import sys
import time

from . import input as input_mod
from . import jev
from .core import new_game
from .ui import render

CLEAR = "\x1b[2J\x1b[H"
MOVES = ("up", "down", "left", "right")


def _key_diagnostic() -> int:
    """Print raw key codes until Ctrl-C or q -- for debugging terminals."""
    print("Press keys to see their codes (q / Ctrl-C to exit):")
    while True:
        key = input_mod.read_key()
        print(repr(key), flush=True)
        if key == "q":
            return 0


def main() -> int:
    if "--keys" in sys.argv:
        return _key_diagnostic()
    ai_mode = "--ai" in sys.argv
    print(CLEAR, end="")
    while True:
        g = new_game()
        last_key = ""
        if ai_mode:
            g.log(
                "jev is playing"
                + ("" if jev._api_key() else " (no API key: random moves)")
            )
        while True:
            sys.stdout.write(CLEAR + render(g) + "\n")
            sys.stdout.flush()
            if g.game_over:
                key = input_mod.read_key()
                if key == "q":
                    return 0
                if key == "r":
                    break  # new run
                continue
            if ai_mode:
                move, ms = jev.choose_move(g)
                if move is None:
                    move = jev.fallback_move(g)
                    if move is None:
                        time.sleep(0.2)
                        continue
                    g.log(f"fallback: {move}")
                else:
                    g.log(f"jev: {move} ({ms:.0f}ms)")
                g.move(move)
                time.sleep(0.25)  # pace the autoplay so it's watchable
                last_key = ""
                continue
            key = input_mod.read_key()
            if key == "q":
                return 0
            if key in ("a", "A"):
                ai_mode = not ai_mode
                g.log(
                    "AI ON -- press a to take over"
                    if ai_mode
                    else "AI OFF -- you have control"
                )
                continue
            if key in ("r", "R"):
                # Double-press guard: abandoning a live run must be deliberate.
                if last_key in ("r", "R"):
                    break  # new run
                g.log("Press r again to abandon this run.")
                last_key = key
                continue
            last_key = key
            if key in MOVES:
                g.move(key)
            elif key in ("f", "F", "!"):
                g.log(
                    "Flags (!) are automatic - stand next to a cell to probe it."
                )
            elif key:
                g.log(f"Unknown key {key!r}: use arrows / wasd, q to quit.")


if __name__ == "__main__":
    raise SystemExit(main())
