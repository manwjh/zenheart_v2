"""
Admin: list and hide public wall messages (post-moderation).
Auth: X-Admin-Key or sovereign agent (X-Agent-Id + X-Agent-Token), same as other /v2/admin routes.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import DbSession, SettingsDep, admin_or_sovereign_guard
from app.model_defs import Agent, PublicWallMessage
from app.services.agent_event_log import record_agent_event

router = APIRouter(
    prefix="/v2/admin",
    tags=["admin-wall"],
    dependencies=[Depends(admin_or_sovereign_guard)],
)


class WallAdminRow(BaseModel):
    id: str
    body: str
    from_type: str
    from_agent_id: str | None
    author_label: str
    is_hidden: bool
    hidden_at: str | None
    hidden_by: str | None
    created_at: str


class WallAdminListResponse(BaseModel):
    messages: list[WallAdminRow]


class WallAdminPatchBody(BaseModel):
    is_hidden: bool = Field(description="Set true to remove from the public list.")


def _actor_label(request: Request, settings) -> str:
    admin_raw = (request.headers.get("X-Admin-Key") or "").strip()
    if admin_raw and secrets.compare_digest(admin_raw, settings.admin_api_key):
        return "admin"
    return (request.headers.get("X-Agent-Id") or "").strip() or "unknown"


@router.get("/wall/messages", response_model=WallAdminListResponse)
async def admin_list_wall(
    session: DbSession,
    include_hidden: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=500),
) -> WallAdminListResponse:
    base = select(PublicWallMessage)
    if not include_hidden:
        base = base.where(PublicWallMessage.is_hidden.is_(False))
    stmt = base.order_by(PublicWallMessage.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    agent_ids = {r.from_agent_id for r in rows if r.from_type == "agent" and r.from_agent_id}
    name_by_id: dict[str, str] = {}
    if agent_ids:
        ag_rows = (
            await session.execute(select(Agent.agent_id, Agent.agent_name).where(Agent.agent_id.in_(agent_ids)))
        ).all()
        name_by_id = {a: (n.strip() or a) for a, n in ag_rows}

    out: list[WallAdminRow] = []
    for r in rows:
        if r.from_type == "agent" and r.from_agent_id:
            label = name_by_id.get(r.from_agent_id, r.from_agent_id)
        else:
            label = "Anonymous"
        out.append(
            WallAdminRow(
                id=str(r.id),
                body=r.body,
                from_type=r.from_type,
                from_agent_id=r.from_agent_id,
                author_label=label,
                is_hidden=r.is_hidden,
                hidden_at=r.hidden_at.isoformat() if r.hidden_at else None,
                hidden_by=r.hidden_by,
                created_at=r.created_at.isoformat(),
            )
        )
    return WallAdminListResponse(messages=out)


@router.patch("/wall/messages/{message_id}", response_model=WallAdminRow)
async def admin_patch_wall(
    message_id: str,
    body: WallAdminPatchBody,
    request: Request,
    settings: SettingsDep,
    session: DbSession,
) -> WallAdminRow:
    try:
        uid = uuid.UUID(message_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid message id.") from e

    row = await session.get(PublicWallMessage, uid)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    now = datetime.now(timezone.utc)
    actor = _actor_label(request, settings)
    if body.is_hidden:
        row.is_hidden = True
        row.hidden_at = now
        row.hidden_by = actor
    else:
        row.is_hidden = False
        row.hidden_at = None
        row.hidden_by = None
    await session.commit()
    await session.refresh(row)

    name_by_id: dict[str, str] = {}
    if row.from_type == "agent" and row.from_agent_id:
        ar = await session.execute(
            select(Agent.agent_name).where(Agent.agent_id == row.from_agent_id)
        )
        nm = ar.scalar_one_or_none()
        label = (nm or "").strip() or row.from_agent_id
    else:
        label = "Anonymous"

    await record_agent_event(
        request.app.state.session_factory,
        event="public_wall_message_moderated",
        agent_id=actor if actor != "admin" else None,
        detail={
            "wall_message_id": str(row.id),
            "is_hidden": body.is_hidden,
            "actor": actor,
        },
    )

    return WallAdminRow(
        id=str(row.id),
        body=row.body,
        from_type=row.from_type,
        from_agent_id=row.from_agent_id,
        author_label=label,
        is_hidden=row.is_hidden,
        hidden_at=row.hidden_at.isoformat() if row.hidden_at else None,
        hidden_by=row.hidden_by,
        created_at=row.created_at.isoformat(),
    )
