"""
Maze-only side effects for /v2/games/ws: live spectator snapshot updates and post-solve agent events.

Keeps games_ws.py free of MazeSession / fog / POMDP scoring imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agent_event_log import record_agent_event
from app.services.games.maze_observation import maze_state_for_spectators
from app.services.games.maze_pomdp_evaluation import evaluate_maze_episode
from app.services.games.maze_session import MazeSession
from app.services.games.pomdp_maze import GAME_ID
from app.services.games_live_registry import GamesLiveRegistry


@dataclass(frozen=True, slots=True)
class MazeSideEffectContext:
    connection_id: str
    agent_id: str
    session_factory: object
    live_registry: GamesLiveRegistry


async def apply_maze_ws_side_effects(
    frame: dict[str, Any],
    new_sess: Any,
    ctx: MazeSideEffectContext,
) -> None:
    """Regenerate spectator view or log solve; no-op if frame is not a maze state/event we care about."""
    if frame.get("game") != GAME_ID:
        return
    mt = frame.get("type")
    if mt == "game_state" and isinstance(new_sess, MazeSession):
        await ctx.live_registry.publish_maze(
            ctx.connection_id,
            agent_id=ctx.agent_id,
            state=maze_state_for_spectators(new_sess),
        )
        return
    if mt == "game_event" and frame.get("event") == "solved":
        ms = new_sess
        if not isinstance(ms, MazeSession):
            return
        ev = frame.get("evaluation")
        if not isinstance(ev, dict):
            ev = evaluate_maze_episode(
                ms.maze, ms.move_count, ms.player_path, ms.blocked_count
            )
        await record_agent_event(
            ctx.session_factory,
            event="maze_solved",
            agent_id=ctx.agent_id,
            connection_id=ctx.connection_id,
            detail={
                "move_count": ms.move_count,
                "blocked_count": ms.blocked_count,
                "action_cost": ms.move_count + ms.blocked_count,
                "elapsed_seconds": ms.run_elapsed_seconds,
                "grid": f"{ms.maze.width}x{ms.maze.height}",
                "template_id": ms.template_id,
                "world_seed": ms.world_seed,
                "pomdp_score": ev["score"],
                "pomdp_weights_version": ev["weights_version"],
            },
        )
