"""
POMDP-style retrospective episode evaluation for maze (ground truth on server only).

Used in the `solved` game_event for /v2/games/ws. Scores are ex post fitness, not
Bayes-optimal lower bounds.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Final

from app.services.maze_core import MazeData, _idx, _STEP_DIRS, shortest_path

# v1 composite: path (retrospective vs L*) + coverage over reachable + rule placeholder.
_WEIGHT_PATH: Final[float] = 0.6
_WEIGHT_COV: Final[float] = 0.25
_WEIGHT_RULE: Final[float] = 0.15
_COVERAGE_GAMMA: Final[float] = 0.85
WEIGHTS_VERSION: Final[str] = "pomdp-v2"
WORLD_KIND_MAZE: Final[str] = "maze"


def _reachable_passage_count(maze: MazeData) -> int:
    """|R|: passage cells (cell==0) reachable from start via 4-neighbors."""
    w, h = maze.width, maze.height
    sx, sy = maze.start
    si = _idx(w, sx, sy)
    if maze.cells[si] != 0:
        return 0
    seen: set[tuple[int, int]] = set()
    q: deque[tuple[int, int]] = deque([(sx, sy)])
    seen.add((sx, sy))
    while q:
        x, y = q.popleft()
        for dx, dy in _STEP_DIRS:
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            ni = _idx(w, nx, ny)
            if maze.cells[ni] != 0:
                continue
            if (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            q.append((nx, ny))
    return len(seen)


def shortest_path_successful_moves(maze: MazeData) -> int:
    """
    Minimum successful move steps from start to goal (edges on a shortest path).
    Returns -1 if goal unreachable, 0 if start is goal (degenerate), else >=1.
    """
    sp = shortest_path(maze)
    if not sp.reachable or len(sp.path) < 1:
        return -1
    n_cells = len(sp.path)
    if n_cells <= 1:
        return 0
    return n_cells - 1


def evaluate_maze_episode(
    maze: MazeData,
    move_count: int,
    player_path: list[tuple[int, int]],
    blocked_count: int = 0,
) -> dict[str, Any]:
    """
    Retrospective POMDP evaluation for one maze episode (typically when solved).
    `player_path` must include the start and each cell after a successful move (server truth).
    Path efficiency uses **action_cost** = move_count + blocked_count (failed moves are penalized).
    """
    L_star = shortest_path_successful_moves(maze)
    reach = _reachable_passage_count(maze)
    unique_visited = len(set(player_path))
    action_cost = move_count + blocked_count

    if L_star < 0:
        eta_path = 0.0
    elif action_cost <= 0:
        eta_path = 0.0
    else:
        eta_path = min(1.0, float(L_star) / float(action_cost))

    if reach <= 0:
        phi_cov = 0.0
    else:
        phi_cov = min(1.0, float(unique_visited) / float(reach))

    g_cov = phi_cov**_COVERAGE_GAMMA
    r_rule = 1.0
    comp_path = eta_path
    comp_cov = g_cov
    comp_rule = r_rule

    score = 100.0 * (
        _WEIGHT_PATH * comp_path
        + _WEIGHT_COV * comp_cov
        + _WEIGHT_RULE * comp_rule
    )

    return {
        "weights_version": WEIGHTS_VERSION,
        "world_kind": WORLD_KIND_MAZE,
        "ground_truth_metrics": {
            "L_star_steps": L_star,
            "reach_cell_count": reach,
            "unique_visited": unique_visited,
            "blocked_count": blocked_count,
            "action_cost": action_cost,
            "eta_path": round(eta_path, 6),
            "phi_cov": round(phi_cov, 6),
        },
        "components": {
            "path": round(comp_path, 6),
            "coverage": round(comp_cov, 6),
            "rule": comp_rule,
        },
        "weights": {
            "path": _WEIGHT_PATH,
            "coverage": _WEIGHT_COV,
            "rule": _WEIGHT_RULE,
            "coverage_gamma": _COVERAGE_GAMMA,
        },
        "score": round(score, 3),
    }
