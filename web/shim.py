"""Bridge between the browser UI and the game core (runs inside Pyodide).

Exposes a tiny JSON API: new() and move(direction) both return the full
game state as a JSON string, which the JavaScript frontend renders.
Pure stdlib so it runs anywhere -- CPython or Pyodide.
"""

from __future__ import annotations

import json

import core  # noqa: F401  (fetched & written next to this file at runtime)

_game = None


def new() -> str:
    global _game
    _game = core.new_game()
    return snapshot()


def move(direction: str) -> str:
    """direction: up / down / left / right. Returns new state as JSON."""
    _game.move(direction)
    return snapshot()


def snapshot() -> str:
    g = _game
    board = [
        [{"kind": c.kind, "value": c.value, "clue": c.clue} for c in row]
        for row in g.board
    ]
    return json.dumps(
        {
            "board": board,
            "prow": g.prow,
            "pcol": g.pcol,
            "hp": g.hp,
            "maxHp": g.max_hp,
            "score": g.score,
            "power": g.power,
            "depth": g.depth,
            "maxDepth": core.MAX_DEPTH,
            "turn": g.turn,
            "messages": g.messages,
            "gameOver": g.game_over,
            "victory": g.victory,
        }
    )
