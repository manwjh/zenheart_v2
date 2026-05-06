"""
Resolve **display labels** for read APIs: **``agent_id`` is the canonical identity**;
``agents.agent_name`` is the source of current display text for registered agents.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.model_defs import Agent


def live_display_name_from_snapshot(
    snapshot: str,
    agent: Optional[Agent],
    *,
    fallback_id: str | None = None,
) -> str:
    """Prefer live ``agents.agent_name``; else legacy ``snapshot``; else a short id stub."""
    if agent is not None:
        return agent.agent_name
    s = (snapshot or "").strip()
    if s:
        return s
    if fallback_id:
        fid = str(fallback_id)
        return (fid[:8] + "…") if len(fid) > 8 else fid
    return "Unknown"


def live_comment_from_parts(
    *,
    from_type: str,
    from_agent_id: str | None,
    visitor_label: str | None,
    agent: Optional[Agent],
) -> str | None:
    """Agent comments: ``agents``; anonymous: stored ``visitor_label``."""
    if from_type == "agent" and from_agent_id and agent is not None:
        return agent.agent_name
    if from_type == "anonymous":
        return (visitor_label or "").strip() or "Anonymous"
    return (visitor_label or "").strip() or None


async def load_agent_name_map(
    session: AsyncSession, agent_ids: Iterable[str]
) -> dict[str, str]:
    """``agent_id`` -> ``agent_name`` (includes revoked agents)."""
    ids = [a for a in {x for x in agent_ids if x} if a and a != "system"]
    if not ids:
        return {}
    result = await session.execute(
        select(Agent.agent_id, Agent.agent_name).where(Agent.agent_id.in_(ids))
    )
    return {row[0]: row[1] for row in result.all()}


async def load_active_agent_name_map(
    session: AsyncSession, agent_ids: Iterable[str]
) -> dict[str, str]:
    """``agent_id`` -> current ``agent_name`` for non-revoked agents; missing = no row or revoked."""
    ids = [a for a in {x for x in agent_ids if x} if a]
    if not ids:
        return {}
    result = await session.execute(
        select(Agent.agent_id, Agent.agent_name).where(
            Agent.agent_id.in_(ids),
            Agent.revoked_at.is_(None),
        )
    )
    return {row[0]: row[1] for row in result.all()}


def enrich_social_message_dicts(
    messages: list[dict], name_by_id: dict[str, str]
) -> list[dict]:
    """In-place: set ``agent_name`` from ``name_by_id`` when ``agent_id`` matches."""
    for m in messages:
        aid = m.get("agent_id")
        if isinstance(aid, str) and aid in name_by_id:
            m["agent_name"] = name_by_id[aid]
    return messages


async def enrich_social_lobby_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    rooms: list[dict[str, Any]],
) -> None:
    """
    In-place: for each room dict from ``list_rooms_snapshot``, set ``creator_name`` and
    each ``members[]['agent_name']`` from ``agents`` for non-revoked agents
    (``system`` and unknown ids keep the in-memory value).
    """
    if not rooms:
        return
    ids: set[str] = set()
    for r in rooms:
        cid = r.get("creator_id")
        if isinstance(cid, str) and cid:
            ids.add(cid)
        for m in r.get("members") or []:
            if isinstance(m, dict):
                aid = m.get("agent_id")
                if isinstance(aid, str) and aid:
                    ids.add(aid)
    if not ids:
        return
    async with session_factory() as session:
        name_map = await load_active_agent_name_map(session, ids)
    for r in rooms:
        cid = r.get("creator_id")
        if isinstance(cid, str) and cid in name_map:
            r["creator_name"] = name_map[cid]
        for m in r.get("members") or []:
            if not isinstance(m, dict):
                continue
            aid = m.get("agent_id")
            if isinstance(aid, str) and aid in name_map:
                m["agent_name"] = name_map[aid]


async def enrich_member_dicts_live(
    session_factory: async_sessionmaker[AsyncSession],
    members: list[dict[str, Any]],
) -> None:
    """In-place: set ``agent_name`` on member dicts from ``agents`` by ``agent_id``."""
    if not members:
        return
    async with session_factory() as session:
        name_map = await load_active_agent_name_map(
            session, (m.get("agent_id") for m in members if m.get("agent_id"))
        )
    for m in members:
        aid = m.get("agent_id")
        if isinstance(aid, str) and aid in name_map:
            m["agent_name"] = name_map[aid]
