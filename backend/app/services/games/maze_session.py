"""
In-memory maze run state for /v2/games/ws (POMDP hidden state on the server).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services.maze_core import MazeData

# Spectator `template_id` is omitted for current procedural play; this is the stored sentinel.
PROCEDURAL_TEMPLATE_ID = -1


@dataclass(slots=True)
class MazeSession:
    """
    Full grid + player pose + revelation set. Runner only receives fog observations
    (see maze_observation).
    """

    maze: MazeData
    player_x: int
    player_y: int
    move_count: int  # successful steps into a passage
    blocked_count: int  # wall or OOB failed `move` (penalized vs move_count; see maze.md)
    solved: bool
    revealed: set[int]
    template_id: int
    world_seed: int
    run_started_monotonic: float
    run_elapsed_seconds: Optional[float]
    player_path: list[tuple[int, int]] = field(default_factory=list)
