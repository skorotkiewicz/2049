"""Terminal rendering for 2049 -- Mines of Merge (pure ANSI, no deps)."""

from __future__ import annotations

from .core import BOARD_SIZE, EMPTY, EXIT, FLAG, Game

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"

TILE_STYLES = {
    2: "\x1b[38;5;250;48;5;236m",
    4: "\x1b[38;5;222;48;5;237m",
    8: "\x1b[38;5;208;48;5;238m",
    16: "\x1b[38;5;203;48;5;239m",
    32: "\x1b[38;5;196;48;5;240m",
    64: "\x1b[1;38;5;196;48;5;52m",
    128: "\x1b[1;38;5;226;48;5;58m",
    256: "\x1b[1;38;5;226;48;5;100m",
    512: "\x1b[1;38;5;118;48;5;22m",
    1024: "\x1b[1;38;5;118;48;5;2m",
    2048: "\x1b[1;38;5;231;48;5;90m",
}


def _tile_str(value: int) -> str:
    style = TILE_STYLES.get(value, "\x1b[1;38;5;231;48;5;90m")
    label = str(value) if value < 10000 else f"{value // 1000}k"
    return f"{style}{label.center(4)}{RESET}"


def _hp_bar(hp: int, max_hp: int) -> str:
    full, lost = hp, max_hp - hp
    return (
        f"\x1b[1;31m{'#' * full}\x1b[0m{DIM}{'.' * lost}{RESET}"
        f" {BOLD}{hp}/{max_hp}{RESET}"
    )


def render(g: Game) -> str:
    lines: list[str] = []

    title = f"  2 0 4 9  --  MINES OF MERGE   (depth {g.depth}/{8})"
    lines.append(f"{BOLD}{title}{RESET}")
    lines.append(
        f"  HP {_hp_bar(g.hp, g.max_hp)}   PWR {BOLD}{g.power}{RESET}"
        f"   SCORE {BOLD}{g.score}{RESET}   T {g.turn}"
    )
    lines.append("  " + "\u2500" * (BOARD_SIZE * 5))

    for r in range(BOARD_SIZE):
        row_parts = [""]
        for c in range(BOARD_SIZE):
            cell = g.board[r][c]
            if (r, c) == (g.prow, g.pcol):
                row_parts.append(
                    f"\x1b[1;38;5;231;48;5;27m{str(g.power).center(4)}{RESET}"
                )
            elif cell.value > 0:
                row_parts.append(_tile_str(cell.value))
            elif cell.kind == FLAG:
                row_parts.append(f"\x1b[1;91;48;5;52m{'!'.center(4)}{RESET}")
            elif cell.kind == EXIT:
                row_parts.append(f"\x1b[1;32;48;5;22m{'>>'.center(4)}{RESET}")
            elif cell.clue is not None and cell.clue > 0:
                color = "\x1b[38;5;78" if cell.clue <= 2 else "\x1b[38;5;220"
                row_parts.append(f"{color}m{str(cell.clue).center(4)}{RESET}")
            elif cell.clue == 0:
                row_parts.append(f"{DIM}{'.'.center(4)}{RESET}")
            else:
                row_parts.append("    ")
        lines.append("".join(row_parts))
    lines.append("  " + "\u2500" * (BOARD_SIZE * 5))
    lines.append(
        f"  {DIM}you=\x1b[0m\x1b[1;38;5;27m{str(g.power).center(4)}{RESET}"
        f"{DIM}  ! = flagged mine  1-9 = clues  >> = stairs{RESET}"
    )
    lines.append(f"  {DIM}move: arrows / hjkl   q: quit{RESET}")

    if g.messages:
        lines.append("")
        for m in g.messages:
            lines.append(f"  {m}")

    if g.game_over:
        outcome = (
            "\x1b[1;32mVICTORY -- you escaped the mines!\x1b[0m"
            if g.victory
            else "\x1b[1;31mGAME OVER\x1b[0m"
        )
        lines.append("")
        lines.append(f"  {outcome}   final score: {BOLD}{g.score}{RESET}")
        lines.append("  press r to restart, q to quit")
    return "\n".join(lines)
