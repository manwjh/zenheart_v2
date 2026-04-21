from __future__ import annotations

from typing import Any, Dict

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent
from app.schemas import UpdateSkillWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.permission_service import check_permission
from app.services.skills_storage import SKILLS_DIR, is_valid_slug


async def handle_update_skill_ws_message(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle authenticated agent JSON with type update_skill.
    Overwrites SKILLS_DIR/<slug>.md.  Fails if the file does not exist.
    Returns a dict to send as one WebSocket text frame (JSON).
    """
    try:
        payload = UpdateSkillWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_update_skill_payload",
            "detail": exc.errors(),
        }

    if not is_valid_slug(payload.slug):
        return {"type": "error", "reason": "invalid_slug", "detail": payload.slug}

    if not SKILLS_DIR.is_dir():
        return {
            "type": "error",
            "reason": "skills_dir_not_found",
            "detail": str(SKILLS_DIR),
        }

    skill_path = SKILLS_DIR / f"{payload.slug}.md"

    if not skill_path.is_file():
        return {
            "type": "error",
            "reason": "skill_not_found",
            "detail": f"No skill with slug '{payload.slug}' exists. Use publish_skill to create it.",
        }

    async with session_factory() as session:
        agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if agent is None:
            return {"type": "error", "reason": "unknown_agent"}

        if not await check_permission(session, "skills", "update", agent.level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "Your level does not have permission to update skills.",
            }

    try:
        skill_path.write_text(payload.markdown, encoding="utf-8")
    except OSError as exc:
        return {"type": "error", "reason": "skill_write_failed", "detail": str(exc)}

    await record_agent_event(
        session_factory,
        event="skill_updated_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"slug": payload.slug, "byte_length": len(payload.markdown.encode("utf-8"))},
    )

    return {
        "type": "update_skill_ok",
        "slug": payload.slug,
        "message": f"Skill '{payload.slug}' updated successfully",
    }
