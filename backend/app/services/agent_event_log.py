import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.event_detail import sanitize_detail
from app.models import AgentEventLog

logger = logging.getLogger(__name__)


async def record_agent_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event: str,
    agent_id: Optional[str],
    connection_id: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    safe_detail = sanitize_detail(detail)
    row = AgentEventLog(
        agent_id=agent_id,
        connection_id=connection_id,
        event=event,
        detail=safe_detail,
    )
    try:
        async with session_factory() as session:
            session.add(row)
            await session.commit()
    except Exception:
        logger.exception("Failed to persist agent event log: event=%s agent_id=%s", event, agent_id)
