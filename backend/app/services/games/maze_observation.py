"""
Build runner (fog) and spectator (full) observations from a MazeSession.
"""
from __future__ import annotations

from typing import Any

from app.services.games.maze_session import MazeSession


def _player_path_json(ms: MazeSession) -> list[dict[str, int]]:
    return [{"x": x, "y": y} for x, y in ms.player_path]


def _one_cell(m, w: int, h: int, x: int, y: int) -> int:
    if x < 0 or y < 0 or x >= w or y >= h:
        return 2
    return m.cells[y * w + x]


def _cardinal_from_center(m, w: int, h: int, px: int, py: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, (dx, dy) in (("n", (0, -1)), ("e", (1, 0)), ("s", (0, 1)), ("w", (-1, 0))):
        v = _one_cell(m, w, h, px + dx, py + dy)
        if v == 2:
            out[name] = "out"
        elif v == 1:
            out[name] = "wall"
        else:
            out[name] = "open"
    return out


def _grid_3x3(m, w: int, h: int, px: int, py: int) -> list[list[int]]:
    """3x3 local patch: row 0 = north (y-1), col 0 = west (x-1). 0=passage,1=wall,2=out."""
    g: list[list[int]] = []
    for dy in (-1, 0, 1):
        row: list[int] = []
        for dx in (-1, 0, 1):
            row.append(_one_cell(m, w, h, px + dx, py + dy))
        g.append(row)
    return g


def _toward_goal_dir(
    px: int, py: int, gx: int, gy: int
) -> str | None:
    """One compass step that reduces Manhattan distance to the goal, or 'here' if on goal."""
    ddx, ddy = gx - px, gy - py
    if ddx == 0 and ddy == 0:
        return "here"
    if abs(ddx) >= abs(ddy):
        return "e" if ddx > 0 else "w"
    return "s" if ddy > 0 else "n"


def maze_state_runner(ms: MazeSession) -> dict[str, Any]:
    """
    Runner observation on /v2/games/ws: 3x3 true local view + structured bearings.
    `goal` / distance / toward_goal are omitted until the goal cell is in the server's revealed
    set (same anti-leak rule as the previous full-grid fog); local geometry is always exact.
    """
    m = ms.maze
    w, h = m.width, m.height
    gx, gy = m.goal
    goal_i = gy * w + gx
    goal_in_view = goal_i in ms.revealed
    px, py = ms.player_x, ms.player_y
    out: dict[str, Any] = {
        "width": m.width,
        "height": m.height,
        "start": {"x": m.start[0], "y": m.start[1]},
        "position": {"x": px, "y": py},
        "player": {"x": px, "y": py},
        "grid_3x3": _grid_3x3(m, w, h, px, py),
        "cell_encoding": ["passage", "wall", "out_of_bounds"],
        "cardinal": _cardinal_from_center(m, w, h, px, py),
        "solved": ms.solved,
        "move_count": ms.move_count,
        "blocked_count": ms.blocked_count,
        "action_cost": ms.move_count + ms.blocked_count,
        "visibility": "local_3x3",
    }
    if goal_in_view or ms.solved:
        out["goal"] = {"x": gx, "y": gy}
        out["distance_to_goal"] = abs(gx - px) + abs(gy - py)
        out["toward_goal"] = _toward_goal_dir(px, py, gx, gy)
    else:
        out["goal"] = None
        out["distance_to_goal"] = None
        out["toward_goal"] = None
    if ms.run_elapsed_seconds is not None:
        out["elapsed_seconds"] = ms.run_elapsed_seconds
    return out


def maze_state_for_spectators(ms: MazeSession) -> dict[str, Any]:
    """
    Full map for HTTP/SSE; not the runner observation.
    """
    from app.config import load_settings

    s = load_settings()
    m = ms.maze
    gx, gy = m.goal
    out: dict[str, Any] = {
        "width": m.width,
        "height": m.height,
        "cells": list(m.cells),
        "start": {"x": m.start[0], "y": m.start[1]},
        "goal": {"x": gx, "y": gy},
        "player": {"x": ms.player_x, "y": ms.player_y},
        "solved": ms.solved,
        "move_count": ms.move_count,
        "blocked_count": ms.blocked_count,
        "action_cost": ms.move_count + ms.blocked_count,
        "visibility": "full",
        "player_path": _player_path_json(ms),
    }
    if s.games_spectator_show_template_id and ms.template_id >= 0:
        out["template_id"] = ms.template_id
    if ms.run_elapsed_seconds is not None:
        out["elapsed_seconds"] = ms.run_elapsed_seconds
    return out
