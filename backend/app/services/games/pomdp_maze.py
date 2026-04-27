"""
Maze on `/v2/games/ws` as a partially observed sequential decision process.

Orchestration only: handshake game id, actions, and wire frames. World rules
live in maze_world; runner/spectator payloads in maze_observation; session model in
maze_session; post-hoc scoring in maze_pomdp_evaluation.
"""
from __future__ import annotations

from typing import Any, Optional

from app.services.games.maze_observation import maze_state_runner
from app.services.games.maze_pomdp_evaluation import evaluate_maze_episode
from app.services.games.maze_session import MazeSession
from app.services.games.maze_world import MOVE_DELTA, create_maze_run, try_step_to

GAME_ID = "maze"


def run_maze_action(
    session: Optional[MazeSession],
    action: str,
    data: dict[str, Any],
) -> tuple[Optional[MazeSession], list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    if action in ("new", "apply"):
        new_s = create_maze_run()
        out.append(
            {
                "type": "game_state",
                "game": GAME_ID,
                "state": maze_state_runner(new_s),
            }
        )
        return new_s, out

    if action == "move":
        if session is None:
            out.append(
                {
                    "type": "error",
                    "reason": "no_active_session",
                    "game": GAME_ID,
                }
            )
            return None, out
        if session.solved:
            out.append(
                {
                    "type": "error",
                    "reason": "session_already_complete",
                    "game": GAME_ID,
                }
            )
            return session, out

        dkey = data.get("dir")
        if not isinstance(dkey, str) or dkey not in MOVE_DELTA:
            out.append(
                {
                    "type": "error",
                    "reason": "invalid_action_payload",
                    "game": GAME_ID,
                    "detail": "dir must be n, e, s, or w",
                }
            )
            return session, out
        dx, dy = MOVE_DELTA[dkey]
        nx, ny = session.player_x + dx, session.player_y + dy
        step = try_step_to(session, nx, ny)
        if step == "oob":
            out.append(
                {
                    "type": "game_event",
                    "game": GAME_ID,
                    "event": "move_blocked",
                    "blocked_count": session.blocked_count,
                }
            )
            out.append(
                {
                    "type": "game_state",
                    "game": GAME_ID,
                    "state": maze_state_runner(session),
                }
            )
            return session, out
        if step == "wall":
            out.append(
                {
                    "type": "game_event",
                    "game": GAME_ID,
                    "event": "move_blocked",
                    "blocked_count": session.blocked_count,
                }
            )
            out.append(
                {
                    "type": "game_state",
                    "game": GAME_ID,
                    "state": maze_state_runner(session),
                }
            )
            return session, out
        out.append(
            {
                "type": "game_state",
                "game": GAME_ID,
                "state": maze_state_runner(session),
            }
        )
        if session.solved:
            out.append(
                {
                    "type": "game_event",
                    "game": GAME_ID,
                    "event": "solved",
                    "move_count": session.move_count,
                    "blocked_count": session.blocked_count,
                    "action_cost": session.move_count + session.blocked_count,
                    "elapsed_seconds": session.run_elapsed_seconds,
                    "evaluation": evaluate_maze_episode(
                        session.maze,
                        session.move_count,
                        session.player_path,
                        session.blocked_count,
                    ),
                }
            )
        return session, out

    out.append(
        {
            "type": "error",
            "reason": "invalid_action",
            "game": GAME_ID,
            "detail": f"Unknown action {action!r}; use new, apply, or move.",
        }
    )
    return session, out
