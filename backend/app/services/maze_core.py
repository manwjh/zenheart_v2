"""
Procedural mazes: recursive backtracker, same grid semantics as the frontend (1=wall, 0=passage).

Single fixed odd size (21x21) for debugging; multi-difficulty can be reintroduced later.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Final

_DIRS_CARVE: Final[tuple[tuple[int, int], ...]] = ((0, -2), (0, 2), (-2, 0), (2, 0))
_STEP_DIRS: Final[tuple[tuple[int, int], ...]] = ((0, -1), (0, 1), (-1, 0), (1, 0))

# Keep in sync with frontend MAZE_WIDTH / MAZE_HEIGHT
MAZE_WIDTH = 21
MAZE_HEIGHT = 21

# Server maze.cells uses 0 / 1 only. Value 2 is **wire-only** for game_state with fog
# (unrevealed); never stored in MazeData.cells.
CELL_UNKNOWN = 2


def _idx(w: int, x: int, y: int) -> int:
    return y * w + x


def _carve(
    w: int,
    h: int,
    cells: list[int],
    x: int,
    y: int,
    rng: random.Random,
) -> None:
    cells[_idx(w, x, y)] = 0
    order = [0, 1, 2, 3]
    rng.shuffle(order)
    for d in order:
        dx, dy = _DIRS_CARVE[d]
        nx, ny = x + dx, y + dy
        if nx < 0 or ny < 0 or nx >= w or ny >= h:
            continue
        if cells[_idx(w, nx, ny)] != 1:
            continue
        mx, my = x + dx // 2, y + dy // 2
        cells[_idx(w, mx, my)] = 0
        _carve(w, h, cells, nx, ny, rng)


@dataclass(slots=True, frozen=True)
class MazeData:
    width: int
    height: int
    cells: tuple[int, ...]
    start: tuple[int, int]
    goal: tuple[int, int]


def generate_maze(rng: random.Random | None = None) -> MazeData:
    w, h = MAZE_WIDTH, MAZE_HEIGHT
    r = rng or random.Random()
    cells: list[int] = [1] * (w * h)
    _carve(w, h, cells, 1, 1, r)
    gx, gy = w - 2, h - 2
    cells[_idx(w, gx, gy)] = 0
    return MazeData(
        width=w,
        height=h,
        cells=tuple(cells),
        start=(1, 1),
        goal=(gx, gy),
    )


@dataclass(slots=True, frozen=True)
class ShortestPathResult:
    length: int
    path: tuple[tuple[int, int], ...]
    reachable: bool


def shortest_path(maze: MazeData) -> ShortestPathResult:
    w, h = maze.width, maze.height
    sx, sy = maze.start
    gx, gy = maze.goal
    start_i = _idx(w, sx, sy)
    goal_i = _idx(w, gx, gy)
    n_cells = w * h
    dist: list[int] = [-1] * n_cells
    prev: list[int] = [-1] * n_cells
    q: list[int] = [start_i]
    dist[start_i] = 0
    qi = 0
    while qi < len(q):
        cur = q[qi]
        qi += 1
        if cur == goal_i:
            break
        cx, cy = cur % w, cur // w
        for dx, dy in _STEP_DIRS:
            nx, ny = cx + dx, cy + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            ni = _idx(w, nx, ny)
            if maze.cells[ni] != 0 or dist[ni] != -1:
                continue
            dist[ni] = dist[cur] + 1
            prev[ni] = cur
            q.append(ni)

    if dist[goal_i] == -1:
        return ShortestPathResult(0, (), False)

    out: list[tuple[int, int]] = []
    p = goal_i
    while True:
        out.append((p % w, p // w))
        if p == start_i:
            break
        p = prev[p]
    out.reverse()
    return ShortestPathResult(len(out), tuple(out), True)


# --- Builder QA (full-map BFS = oracle "explore" after generation) ---

# Reject if start→goal geodesic (successful `move` steps) exceeds this on 21×21.
_MAZE_QA_MAX_SPG_STEPS: Final[int] = 320
# Fresh seeds to try per run before fallback to last draw (safety: always return a run).
MAZE_QA_MAX_SEED_ATTEMPTS: Final[int] = 48


def shortest_path_successful_move_count(maze: MazeData) -> int | None:
    """
    Successful moves on a shortest path from start to goal, or None if unreachable.
    """
    sp = shortest_path(maze)
    if not sp.reachable or len(sp.path) < 1:
        return None
    return len(sp.path) - 1


def maze_passes_builder_qa(maze: MazeData) -> bool:
    """
    After generate: full-map shortest path must exist; L* in [Manhattan, _MAZE_QA_MAX_SPG_STEPS].
    """
    L = shortest_path_successful_move_count(maze)
    if L is None:
        return False
    m_dist = abs(maze.start[0] - maze.goal[0]) + abs(maze.start[1] - maze.goal[1])
    if L < m_dist:
        return False
    if L > _MAZE_QA_MAX_SPG_STEPS:
        return False
    return True
