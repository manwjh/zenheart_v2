from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent
from app.schemas import DeleteSkillWsPayload, PublishSkillWsPayload, UpdateSkillWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.permission_service import check_permission
from app.services.points_service import award_points
from app.services.skills_storage import SKILLS_DIR, is_valid_slug


def _utf8_byte_length(text: str) -> int:
    return len(text.encode("utf-8"))


def _skill_md_path(slug: str) -> Path:
    return SKILLS_DIR / f"{slug}.md"


def _skills_dir_error() -> Dict[str, Any] | None:
    if SKILLS_DIR.is_dir():
        return None
    return {
        "type": "error",
        "reason": "skills_dir_not_found",
        "detail": str(SKILLS_DIR),
    }


async def handle_delete_skill_ws_message(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle authenticated agent JSON with type delete_skill.
    Removes SKILLS_DIR/<slug>.md.
    Fails if the .md file does not exist.
    Returns a dict to send as one WebSocket text frame (JSON).
    """
    try:
        payload = DeleteSkillWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_delete_skill_payload",
            "detail": exc.errors(),
        }

    if not is_valid_slug(payload.slug):
        return {"type": "error", "reason": "invalid_slug", "detail": payload.slug}

    err = _skills_dir_error()
    if err is not None:
        return err

    md_path = _skill_md_path(payload.slug)
    if not md_path.is_file():
        return {
            "type": "error",
            "reason": "skill_not_found",
            "detail": f"No skill with slug '{payload.slug}' exists.",
        }

    async with session_factory() as session:
        agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if agent is None:
            return {"type": "error", "reason": "unknown_agent"}

        if not await check_permission(session, "skills", "delete", agent.level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "Your level does not have permission to delete skills.",
            }

    try:
        md_path.unlink()
    except OSError as exc:
        return {"type": "error", "reason": "skill_delete_failed", "detail": str(exc)}

    await record_agent_event(
        session_factory,
        event="skill_deleted_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"slug": payload.slug},
    )

    return {
        "type": "delete_skill_ok",
        "slug": payload.slug,
        "message": f"Skill '{payload.slug}' deleted successfully",
    }


async def handle_publish_skill_ws_message(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle authenticated agent JSON with type publish_skill.
    Creates SKILLS_DIR/<slug>.md.  Fails if the file already exists.
    Returns a dict to send as one WebSocket text frame (JSON).
    """
    try:
        payload = PublishSkillWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_publish_skill_payload",
            "detail": exc.errors(),
        }

    if not is_valid_slug(payload.slug):
        return {"type": "error", "reason": "invalid_slug", "detail": payload.slug}

    err = _skills_dir_error()
    if err is not None:
        return err

    skill_path = _skill_md_path(payload.slug)

    if skill_path.exists():
        return {
            "type": "error",
            "reason": "skill_already_exists",
            "detail": f"A skill with slug '{payload.slug}' already exists. Use update_skill to overwrite.",
        }

    async with session_factory() as session:
        agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if agent is None:
            return {"type": "error", "reason": "unknown_agent"}

        if not await check_permission(session, "skills", "publish", agent.level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "Your level does not have permission to publish skills.",
            }

    try:
        skill_path.write_text(payload.markdown, encoding="utf-8")
    except OSError as exc:
        return {"type": "error", "reason": "skill_write_failed", "detail": str(exc)}

    byte_length = _utf8_byte_length(payload.markdown)
    await record_agent_event(
        session_factory,
        event="skill_published_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"slug": payload.slug, "byte_length": byte_length},
    )
    await award_points(session_factory, agent_id, "publish_skill")

    return {
        "type": "publish_skill_ok",
        "slug": payload.slug,
        "message": f"Skill '{payload.slug}' published successfully",
    }


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

    err = _skills_dir_error()
    if err is not None:
        return err

    skill_path = _skill_md_path(payload.slug)

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

    byte_length = _utf8_byte_length(payload.markdown)
    await record_agent_event(
        session_factory,
        event="skill_updated_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"slug": payload.slug, "byte_length": byte_length},
    )
    await award_points(session_factory, agent_id, "update_skill")

    return {
        "type": "update_skill_ok",
        "slug": payload.slug,
        "message": f"Skill '{payload.slug}' updated successfully",
    }
