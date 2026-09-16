# 2049 — Mines of Merge

A tiny roguelike that fuses **2048** and **Minesweeper**. You *are* the tile:
every move slides the whole dungeon with 2048 rules while hidden mines —
Minesweeper style — wait in the dark. Descend 8 depths and escape.

## Run

```sh
uv run game
```

No dependencies beyond Python itself; everything is managed by `uv`.

## How it works

- **2048 half** — every move slides *all* tiles (you included). Slide into an
  equal tile to merge: your power doubles, score goes up. Big merges (32+)
  heal you.
- **Minesweeper half** — mines are invisible and act as walls for tiles
  (tiles piling up against nothing is itself a clue). Standing next to cells
  *probes* them: mines get flagged with `!`, safe cells show a clue number =
  how many mines touch them. **Stepping on any mine explodes it** for
  `1 + depth` damage.
- **Roguelike half** — find the stairs `>>` to descend. Each depth adds
  mines. Run out of moves and the walls crush you. Die and your score is
  all that remains. Reach **depth 8** and climb out to win.

## Controls

| Key | Action |
| --- | --- |
| arrows / `h j k l` | slide up / down / left / right |
| `r` | new run (after death) |
| `q` | quit |

## Layout

```
src/game/
├── core.py    # game state, 2048 slide, mines, probing, descent
├── ui.py      # ANSI board renderer (no deps)
├── input.py   # raw keypress input (POSIX + Windows)
└── main.py    # main loop
```
