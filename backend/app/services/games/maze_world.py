"""
Deterministic maze dynamics: new run, one attempted step, neighborhood revelation.
No wire framing; see pomdp_maze for /v2/games/ws JSON.
"""
from __future__ import annotations

import random
import secrets
import time
from typing import Final, Literal

from app.services.maze_core import (
    MazeData,
    MAZE_QA_MAX_SEED_ATTEMPTS,
    generate_maze,
    maze_passes_builder_qa,
)
from app.services.games.maze_session import MazeSession, PROCEDURAL_TEMPLATE_ID

# Cardinal moves for "dir" in wire protocol.
MOVE_DELTA: Final[dict[str, tuple[int, int]]] = {
    "n": (0, -1),
    "e": (1, 0),
    "s": (0, 1),
    "w": (-1, 0),
}

# Center + 4-neighbors: cells revealed around the player (fog).
NEIGHBORS: Final[tuple[tuple[int, int], ...]] = ((0, 0), (0, -1), (0, 1), (-1, 0), (1, 0))

StepOutcome = Literal["oob", "wall", "moved"]


def reveal_around(maze: MazeData, x: int, y: int, revealed: set[int]) -> None:
    w = maze.width
    for dx, dy in NEIGHBORS:
        nx, ny = x + dx, y + dy
        if 0 <= nx < maze.width and 0 <= ny < maze.height:
            revealed.add(ny * w + nx)


def _build_session(maze: MazeData, world_seed: int) -> MazeSession:
    sx, sy = maze.start
    revealed: set[int] = set()
    reveal_around(maze, sx, sy, revealed)
    now = time.monotonic()
    return MazeSession(
        maze=maze,
        player_x=sx,
        player_y=sy,
        move_count=0,
        blocked_count=0,
        solved=False,
        revealed=revealed,
        template_id=PROCEDURAL_TEMPLATE_ID,
        world_seed=world_seed,
        run_started_monotonic=now,
        run_elapsed_seconds=None,
        player_path=[(sx, sy)],
    )


def create_maze_run() -> MazeSession:
    """
    Procedural draw + **builder QA**: full-map shortest path must pass `maze_passes_builder_qa`
    (reachable; start→goal geodesic not absurdly long). Rejection sampling with fresh seeds; if
    all attempts fail the soft cap, the last sample is used so a run still starts.
    """
    last: tuple[MazeData, int] | None = None
    for _ in range(MAZE_QA_MAX_SEED_ATTEMPTS):
        world_seed = secrets.randbits(64)
        maze = generate_maze(random.Random(world_seed))
        last = (maze, world_seed)
        if maze_passes_builder_qa(maze):
            return _build_session(maze, world_seed)
    assert last is not None
    maze, world_seed = last
    return _build_session(maze, world_seed)


def try_step_to(session: MazeSession, nx: int, ny: int) -> StepOutcome:
    """
    One transition from the current cell toward (nx, ny) as an adjacent target.
    Mutates `session` for wall bump (reveal only), successful move, or goal solve.
    """
    w, h = session.maze.width, session.maze.height
    if nx < 0 or ny < 0 or nx >= w or ny >= h:
        session.blocked_count += 1
        return "oob"
    cidx = ny * w + nx
    if session.maze.cells[cidx] != 0:
        session.revealed.add(cidx)
        session.blocked_count += 1
        return "wall"
    session.player_x, session.player_y = nx, ny
    session.move_count += 1
    session.player_path.append((nx, ny))
    reveal_around(session.maze, nx, ny, session.revealed)
    gx, gy = session.maze.goal
    if nx == gx and ny == gy:
        session.solved = True
        session.run_elapsed_seconds = round(
            time.monotonic() - session.run_started_monotonic, 3
        )
    return "moved"
