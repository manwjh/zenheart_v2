"""Whether to persist games_ws_message_in for an inbound WebSocket frame."""
from __future__ import annotations

from typing import Any


def should_log_games_ws_message_in(
    msg_type: Any,
    data: dict[str, Any],
    *,
    log_move_inbound_to_db: bool,
) -> bool:
    """Avoid agent_event_log commit on every maze move unless audit flag is enabled."""
    if msg_type != "game":
        return True
    action = data.get("action")
    if action == "move" and not log_move_inbound_to_db:
        return False
    return True
