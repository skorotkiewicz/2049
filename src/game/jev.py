"""jev.py -- the typesafe/jev-1.13 decision model plays 2049.

The model answers one narrow, typed question per turn: which way to
slide. The game owns the workflow; jev only decides. Decisions come
back in ~70ms, fast enough to play a move every few frames.

Set OPENROUTER_API_KEY (or API_KEY) to enable it; without a key the
AI falls back to random legal moves.
"""

from __future__ import annotations

import json
import os
import random
import re
import time

import requests

from .core import BOARD_SIZE, EXIT, FLAG, Game

# Any Jev-compatible decisions API works here. Point JEVD_API_URL at a
# self-hosted Laya server (server.py) to play offline: no key, no egress.
API_URL = os.environ.get("JEVD_API_URL", "https://openrouter.ai/api/alpha/decisions")
MODEL = "typesafe/jev-1.13"
TIMEOUT = 2.0  # generous; jev usually answers in ~70ms

DIRS = ("up", "down", "left", "right")

RULES = """\
You are tile P on a 7x7 grid. Each move slides ALL tiles with 2048 \
rules (merge equal tiles to double them; merging as P grows your \
power and scores). Mines are invisible walls; stepping on one (or a \
flagged `!` mine) explodes for 1+depth damage. Numbers on empty cells \
are minesweeper clues. `>>` are stairs: step onto them to descend. \
Survive to depth 8. Avoid mines, merge to grow, reach the stairs.
Finish game ASAP.
"""

DIR_HELP = {
    "up": "slide everything up",
    "down": "slide everything down",
    "left": "slide everything left",
    "right": "slide everything right",
}


def _api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY") or os.environ.get("API_KEY")


def describe_state(g: Game) -> str:
    """Render the board as compact text for the model."""
    rows = []
    for r in range(BOARD_SIZE):
        cells = []
        for c in range(BOARD_SIZE):
            cell = g.board[r][c]
            if (r, c) == (g.prow, g.pcol):
                cells.append(f"P{g.power}")
            elif cell.kind == EXIT:
                cells.append(">>")
            elif cell.kind == FLAG:
                cells.append("!")
            elif cell.value > 0:
                cells.append(str(cell.value))
            elif cell.clue is not None:
                cells.append(str(cell.clue))
            else:
                cells.append(".")
        rows.append(" ".join(cells))
    legal = legal_moves(g)
    return "\n".join(
        rows
        + [
            f"depth: {g.depth}/8 (mines on this depth: {g.mine_target()})",
            f"hp: {g.hp}/{g.max_hp}  power: {g.power}  score: {g.score}",
            f"last events: "
            f"{' ; '.join(_ANSI.sub('', m) for m in g.messages[-2:])}",
            f"legal moves: {', '.join(legal)}",
        ]
    )


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def legal_moves(g: Game) -> list[str]:
    return [d for d in DIRS if g._can_move(d)]


def choose_move(g: Game) -> tuple[str | None, float]:
    """Ask jev which way to slide. Returns (direction, elapsed_ms).

    direction is None when the API is unavailable or answers
    something illegal -- the caller decides what to do then.
    """
    legal = legal_moves(g)
    if not legal:
        return None, 0.0

    key = _api_key()
    if not key and "openrouter.ai" in API_URL:
        return None, 0.0  # only the official API needs a key

    t0 = time.perf_counter()
    try:
        response = requests.post(
            url=API_URL,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "model": MODEL,
                    "state": describe_state(g),
                    "questions": {
                        "move": {
                            "type": "choice",
                            "instructions": RULES,
                            "criteria": {d: DIR_HELP[d] for d in legal},
                        }
                    },
                }
            ),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        move = response.json()["answers"]["move"]["choice"]
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None, (time.perf_counter() - t0) * 1000

    elapsed = (time.perf_counter() - t0) * 1000
    return (move, elapsed) if move in legal else (None, elapsed)


def fallback_move(g: Game) -> str | None:
    """Random legal move, used when jev is offline."""
    legal = legal_moves(g)
    return random.choice(legal) if legal else None
