"""Core game logic for 2049 -- Mines of Merge.

You are the tile. Slide through a dungeon with 2048 rules, but the
dungeon hides mines (Minesweeper style). Merge to grow powerful,
read the clues, dodge the unseen, and descend to depth 8 to win.

Rules
-----
* Every move slides ALL tiles with 2048 rules; you are a tile of
  value `power`. You merge with equal tiles to double your power.
* Mines are invisible walls for tiles -- tiles pile up against them,
  which is a clue in itself. If YOU step on one, it explodes.
* Standing next to a cell probes it: mines get flagged, safe cells
  show a Minesweeper clue (how many mines touch them).
* Reaching the stairs (>>) takes you deeper. Survive to depth 8.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

BOARD_SIZE = 7
MAX_DEPTH = 8

# Cell kinds
EMPTY = 0
MINE = -1  # hidden mine (never shown until flagged/exploded)
FLAG = -2  # revealed mine
EXIT = -3  # stairs down


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


@dataclass
class Cell:
    kind: int = EMPTY  # EMPTY / MINE / FLAG / EXIT
    value: int = 0  # tile value for tile cells (2, 4, 8, ...)
    clue: int | None = None  # minesweeper clue on revealed safe cells


@dataclass
class Game:
    depth: int = 1
    hp: int = 10
    max_hp: int = 10
    score: int = 0
    power: int = 2  # the player's tile value
    board: list[list[Cell]] = field(
        default_factory=lambda: [
            [Cell() for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)
        ]
    )
    prow: int = BOARD_SIZE - 1
    pcol: int = 0
    messages: list[str] = field(default_factory=list)
    game_over: bool = False
    victory: bool = False
    turn: int = 0
    # per-move stats
    gained_this_move: int = 0
    best_merge_this_move: int = 0

    # ---------------------------------------------------------------- setup
    def start(self) -> None:
        self._spawn_exit()
        self._place_mines(self.mine_target())
        self._spawn_tile()
        self._spawn_tile()
        self._probe()
        self.log(
            f"You wake on depth {self.depth}. Find the stairs (\x1b[1;32m>>\x1b[0m)."
        )

    def mine_target(self) -> int:
        return 2 + self.depth

    def active_mines(self) -> int:
        return sum(1 for row in self.board for c in row if c.kind in (MINE, FLAG))

    def _empty_cells(self) -> list[tuple[int, int]]:
        out = []
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                cell = self.board[r][c]
                if (
                    cell.value == 0
                    and cell.kind in (EMPTY,)
                    and (r, c) != (self.prow, self.pcol)
                ):
                    out.append((r, c))
        return out

    def _spawn_exit(self) -> None:
        spots = self._empty_cells()
        if not spots:
            return
        r, c = random.choice(spots)
        self.board[r][c] = Cell(kind=EXIT)

    def _place_mines(self, n: int) -> None:
        spots = self._empty_cells()
        random.shuffle(spots)
        for r, c in spots[:n]:
            self.board[r][c] = Cell(kind=MINE)

    def _spawn_tile(self) -> None:
        spots = self._empty_cells()
        if not spots:
            return
        r, c = random.choice(spots)
        v = 4 if random.random() < 0.12 else 2
        self.board[r][c] = Cell(value=v)

    def _spawn_mine_if_needed(self) -> None:
        missing = self.mine_target() - self.active_mines()
        if missing > 0 and random.random() < 0.45:
            spots = self._empty_cells()
            if spots:
                r, c = random.choice(spots)
                self.board[r][c] = Cell(kind=MINE)

    # ------------------------------------------------------------ messaging
    def log(self, msg: str) -> None:
        self.messages.append(msg)
        self.messages = self.messages[-4:]

    # -------------------------------------------------------- minesweeper IO
    def _mine_count_around(self, r: int, c: int) -> int:
        n = 0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                if 0 <= rr < BOARD_SIZE and 0 <= cc < BOARD_SIZE:
                    if self.board[rr][cc].kind in (MINE, FLAG):
                        n += 1
        return n

    def _probe(self) -> None:
        """Reveal cells around the player: flag mines, set clues."""
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                r, c = self.prow + dr, self.pcol + dc
                if not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE):
                    continue
                cell = self.board[r][c]
                if cell.kind == MINE:
                    cell.kind = FLAG
                elif cell.kind == EMPTY and cell.clue is None:
                    cell.clue = self._mine_count_around(r, c)

    # -------------------------------------------------------------- movement
    DIRS = {
        "up": (-1, 0),
        "down": (1, 0),
        "left": (0, -1),
        "right": (0, 1),
    }

    def move(self, direction: str) -> None:
        if self.game_over:
            return
        dr, dc = self.DIRS[direction]
        nr, nc = self.prow + dr, self.pcol + dc
        self.gained_this_move = 0
        self.best_merge_this_move = 0

        neighbor = self.board[nr][nc] if self._on_board(nr, nc) else None

        # Stepping onto the stairs: descend.
        if neighbor is not None and neighbor.kind == EXIT:
            self.prow, self.pcol = nr, nc
            self._descend()
            return

        # Stepping onto a mine: boom, the rest of the board holds still.
        if neighbor is not None and neighbor.kind in (MINE, FLAG):
            self._explode(nr, nc)
            self._after_move()
            return

        if not self._slide(dr, dc):
            self.log("You can't slide that way.")
            self._check_crush()
            return

        self.turn += 1
        self.score += self.gained_this_move
        self._probe()
        self._spawn_tile()
        self._spawn_mine_if_needed()
        self._after_move()

    def _on_board(self, r: int, c: int) -> bool:
        return 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE

    def _explode(self, r: int, c: int) -> None:
        dmg = 1 + self.depth
        self.board[r][c] = Cell()
        self.prow, self.pcol = r, c
        self.hp -= dmg
        self.log(f"\x1b[1;31mBOOM! A mine hits you for {dmg} damage!\x1b[0m")
        self._probe()

    def _after_move(self) -> None:
        if self.best_merge_this_move >= 32:
            self.hp = clamp(self.hp + 1, 0, self.max_hp)
            self.log("A mighty merge knits your wounds. \x1b[1;32m+1 HP\x1b[0m.")
        if self.hp <= 0:
            self.hp = 0
            self.game_over = True
            self.log(
                "\x1b[1;31mYour tile shatters. The dungeon keeps your score.\x1b[0m"
            )

    def _check_crush(self) -> None:
        """No legal move at all: the dungeon contracts."""
        if any(self._can_move(d) for d in self.DIRS):
            return
        self.hp -= 1
        self.log("\x1b[1;33mNo room to move! The walls crush you (-1 HP).\x1b[0m")
        tiles = [
            (r, c)
            for r in range(BOARD_SIZE)
            for c in range(BOARD_SIZE)
            if self.board[r][c].value > 0
        ]
        if tiles:
            r, c = random.choice(tiles)
            self.board[r][c] = Cell()
        if self.hp <= 0:
            self.hp = 0
            self.game_over = True
            self.log("\x1b[1;31mCrushed flat. Game over.\x1b[0m")

    def _can_move(self, direction: str) -> bool:
        # Simulate on a copy: the slide must not mutate the real board.
        save_power, save_r, save_c = self.power, self.prow, self.pcol
        save_board = [
            [Cell(kind=c.kind, value=c.value, clue=c.clue) for c in row]
            for row in self.board
        ]
        try:
            return self._slide(*self.DIRS[direction])
        finally:
            self.power, self.prow, self.pcol = save_power, save_r, save_c
            self.board = save_board

    # ------------------------------------------------------------ 2048 slide
    def _slide(self, dr: int, dc: int) -> bool:
        """Slide every tile (including you) with 2048 rules.

        Mines and stairs act as walls that split each line into
        independent 2048 segments. Returns True if anything moved.
        """
        moved = False
        size = BOARD_SIZE
        for i in range(size):
            coords: list[tuple[int, int]] = []
            for j in range(size):
                r = i if dc else j
                c = j if dc else i
                coords.append((r, c))
            if dr > 0 or dc > 0:  # travel order = far side first
                coords.reverse()

            # Tokenize: P=player, T=tile, W=wall (mine/stairs), .=empty
            tokens: list[tuple[str, int, bool] | None] = []
            for r, c in coords:
                cell = self.board[r][c]
                if (r, c) == (self.prow, self.pcol):
                    tokens.append(("P", self.power, False))
                elif cell.kind in (MINE, FLAG, EXIT):
                    tokens.append(("W", 0, False))
                elif cell.value > 0:
                    tokens.append(("T", cell.value, False))
                else:
                    tokens.append(None)

            new_tokens = self._compact_merge(tokens)

            if new_tokens != tokens:
                moved = True
                # Write tokens back, restoring clues on cells left empty.
                for (r, c), tok, old in zip(coords, new_tokens, tokens):
                    if tok is None:
                        old_clue = self.board[r][c].clue if old is None else None
                        self.board[r][c] = Cell(clue=old_clue)
                    elif tok[0] == "W":
                        pass  # wall cell untouched
                    elif tok[0] == "P":
                        self.board[r][c] = Cell()
                        self.prow, self.pcol = r, c
                        self.power = tok[1]
                    else:
                        self.board[r][c] = Cell(value=tok[1])
        return moved

    def _compact_merge(
        self, tokens: list[tuple[str, int, bool] | None]
    ) -> list[tuple[str, int, bool] | None]:
        """2048 compaction of one line; walls split it into segments."""
        out: list[tuple[str, int, bool] | None] = [None] * len(tokens)

        seg: list[tuple[str, int, bool]] = []
        seg_coords: list[int] = []

        def flush() -> None:
            merged: list[tuple[str, int, bool]] = []
            for kind, value, was_merged in seg:
                if (
                    merged
                    and not merged[-1][2]
                    and merged[-1][0] in ("P", "T")
                    and kind in ("P", "T")
                    and not (merged[-1][0] == "P" and kind == "P")
                    and merged[-1][1] == value
                ):
                    new_kind = "P" if "P" in (merged[-1][0], kind) else "T"
                    new_val = value * 2
                    merged[-1] = (new_kind, new_val, True)
                    self.gained_this_move += new_val
                    self.best_merge_this_move = max(self.best_merge_this_move, new_val)
                else:
                    merged.append((kind, value, was_merged))
            for n, slot in enumerate(seg_coords):
                if n < len(merged):
                    out[slot] = merged[n]

        for idx, tok in enumerate(tokens):
            if tok is not None and tok[0] == "W":
                out[idx] = tok
                flush()
                seg, seg_coords = [], []
            else:
                if tok is not None:
                    seg.append(tok)
                seg_coords.append(idx)
        flush()
        return out

    # --------------------------------------------------------------- descend
    def _descend(self) -> None:
        if self.depth >= MAX_DEPTH:
            self.victory = True
            self.game_over = True
            self.log("\x1b[1;32mYou climb out of the mines. YOU WIN!\x1b[0m")
            return
        self.depth += 1
        bonus = self.depth * 5
        self.score += bonus
        heal = 3
        self.hp = clamp(self.hp + heal, 0, self.max_hp)
        self.board = [[Cell() for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self._spawn_exit()
        self._place_mines(self.mine_target())
        self._spawn_tile()
        self._spawn_tile()
        self._probe()
        self.log(
            f"\x1b[1;36mYou descend to depth {self.depth}. "
            f"+{bonus} score, +{heal} HP.\x1b[0m"
        )


def new_game() -> Game:
    g = Game()
    g.start()
    return g
