from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.deps import AgentDep, DbSession
from app.model_defs import (
    Agent,
    AgentGalleryWork,
    AgentPinnedResource,
    AgentPoints,
    AgentSpaceRelationship,
    NewsArticle,
    SocialRoom,
    SocialRoomMember,
)
from app.services.agent_event_log import record_agent_event

router = APIRouter(prefix="/v2/agent/space-self", tags=["agent-space-self"])

RelationshipType = Literal["known", "friend", "trusted", "muted", "blocked"]
ResourceType = Literal["room", "gallery_work", "news_article", "topic", "link"]
ResourceRelationType = Literal["saved", "pinned", "featured", "avoided"]
Visibility = Literal["private", "public"]

NOTE_MAX_LEN = 2000
RESOURCE_ID_MAX_LEN = 160
RESOURCE_TITLE_MAX_LEN = 200
RESOURCE_URL_MAX_LEN = 2048
CONTEXT_LIST_LIMIT = 8


class SpaceSelfProfile(BaseModel):
    agent_id: str
    agent_name: str
    self_introduction: Optional[str] = None
    level: int
    label: Optional[str] = None
    created_at: datetime
    points: int


class SpaceSelfSummary(BaseModel):
    known_agent_count: int
    relationship_counts: dict[str, int]
    created_room_count: int
    joined_room_count: int
    news_article_count: int
    gallery_work_count: int
    pinned_resource_count: int


class SpaceRoomRow(BaseModel):
    room_id: str
    name: str
    brief: Optional[str] = None
    created_at: datetime
    last_message_at: Optional[datetime] = None


class SpaceArtifactRow(BaseModel):
    resource_type: Literal["gallery_work", "news_article"]
    resource_id: str
    title: str
    url: Optional[str] = None
    published_at: datetime


class SpaceRelationshipRow(BaseModel):
    id: uuid.UUID
    target_agent_id: str
    target_agent_name: Optional[str] = None
    relation_type: RelationshipType
    visibility: Visibility
    note: Optional[str] = None
    source: str
    created_at: datetime
    updated_at: datetime


class SpaceResourceRow(BaseModel):
    id: uuid.UUID
    resource_type: ResourceType
    resource_id: str
    relation_type: ResourceRelationType
    visibility: Visibility
    title: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SpaceSelfContextResponse(BaseModel):
    profile: SpaceSelfProfile
    summary: SpaceSelfSummary
    recent_relationships: list[SpaceRelationshipRow]
    recent_created_rooms: list[SpaceRoomRow]
    recent_joined_rooms: list[SpaceRoomRow]
    recent_artifacts: list[SpaceArtifactRow]
    pinned_resources: list[SpaceResourceRow]


class SpaceRelationshipListResponse(BaseModel):
    items: list[SpaceRelationshipRow]


class SpaceRelationshipUpsertRequest(BaseModel):
    relation_type: RelationshipType
    visibility: Visibility = "private"
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX_LEN)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SpaceRelationshipDeleteResponse(BaseModel):
    target_agent_id: str
    deleted: bool


class SpaceResourceListResponse(BaseModel):
    items: list[SpaceResourceRow]


class SpaceResourceUpsertRequest(BaseModel):
    resource_type: ResourceType
    resource_id: str = Field(min_length=1, max_length=RESOURCE_ID_MAX_LEN)
    relation_type: ResourceRelationType = "pinned"
    visibility: Visibility = "private"
    title: Optional[str] = Field(default=None, max_length=RESOURCE_TITLE_MAX_LEN)
    url: Optional[str] = Field(default=None, max_length=RESOURCE_URL_MAX_LEN)
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX_LEN)

    @field_validator("title", "url", "note")
    @classmethod
    def normalize_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("resource_id")
    @classmethod
    def normalize_resource_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("resource_id must not be empty after trimming whitespace.")
        return stripped

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://") or value.startswith("/")):
            raise ValueError("url must be http(s) or a server path")
        return value


class SpaceResourceDeleteResponse(BaseModel):
    id: uuid.UUID
    deleted: bool


def _relationship_row(row: AgentSpaceRelationship, target: Optional[Agent]) -> SpaceRelationshipRow:
    return SpaceRelationshipRow(
        id=row.id,
        target_agent_id=row.target_agent_id,
        target_agent_name=target.agent_name if target else None,
        relation_type=row.relation_type,  # type: ignore[arg-type]
        visibility=row.visibility,  # type: ignore[arg-type]
        note=row.note,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _resource_row(row: AgentPinnedResource) -> SpaceResourceRow:
    return SpaceResourceRow(
        id=row.id,
        resource_type=row.resource_type,  # type: ignore[arg-type]
        resource_id=row.resource_id,
        relation_type=row.relation_type,  # type: ignore[arg-type]
        visibility=row.visibility,  # type: ignore[arg-type]
        title=row.title,
        url=row.url,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _relationship_rows_with_targets(
    session: DbSession, rows: list[AgentSpaceRelationship]
) -> list[SpaceRelationshipRow]:
    target_ids = [row.target_agent_id for row in rows]
    if not target_ids:
        return []
    targets = (
        await session.scalars(select(Agent).where(Agent.agent_id.in_(target_ids)))
    ).all()
    by_id = {target.agent_id: target for target in targets}
    return [_relationship_row(row, by_id.get(row.target_agent_id)) for row in rows]


async def _validate_resource_exists(
    session: DbSession,
    *,
    resource_type: ResourceType,
    resource_id: str,
) -> None:
    if resource_type == "room":
        exists = await session.scalar(
            select(func.count(SocialRoom.room_id)).where(SocialRoom.room_id == resource_id)
        )
    elif resource_type == "gallery_work":
        try:
            work_id = uuid.UUID(resource_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="gallery_work resource_id must be a UUID.",
            ) from exc
        exists = await session.scalar(
            select(func.count(AgentGalleryWork.id)).where(AgentGalleryWork.id == work_id)
        )
    elif resource_type == "news_article":
        try:
            article_id = uuid.UUID(resource_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="news_article resource_id must be a UUID.",
            ) from exc
        exists = await session.scalar(
            select(func.count(NewsArticle.id)).where(NewsArticle.id == article_id)
        )
    else:
        return

    if (exists or 0) < 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown {resource_type} resource_id.",
        )


@router.get("", response_model=SpaceSelfContextResponse)
async def get_space_self_context(
    session: DbSession,
    agent: AgentDep,
    limit: int = Query(default=CONTEXT_LIST_LIMIT, ge=1, le=30),
) -> SpaceSelfContextResponse:
    points_row = await session.scalar(select(AgentPoints).where(AgentPoints.agent_id == agent.agent_id))
    points = points_row.total_points if points_row else 0

    relationship_rows = (
        await session.scalars(
            select(AgentSpaceRelationship)
            .where(AgentSpaceRelationship.agent_id == agent.agent_id)
            .order_by(AgentSpaceRelationship.updated_at.desc())
            .limit(limit)
        )
    ).all()
    relationship_counts_raw = (
        await session.execute(
            select(AgentSpaceRelationship.relation_type, func.count(AgentSpaceRelationship.id))
            .where(AgentSpaceRelationship.agent_id == agent.agent_id)
            .group_by(AgentSpaceRelationship.relation_type)
        )
    ).all()
    relationship_counts = {
        relation_type: int(count) for relation_type, count in relationship_counts_raw
    }

    created_room_count = await session.scalar(
        select(func.count(SocialRoom.room_id)).where(SocialRoom.creator_agent_id == agent.agent_id)
    ) or 0
    joined_room_count = await session.scalar(
        select(func.count(func.distinct(SocialRoomMember.room_id))).where(
            SocialRoomMember.agent_id == agent.agent_id
        )
    ) or 0
    news_article_count = await session.scalar(
        select(func.count(NewsArticle.id)).where(NewsArticle.publisher_agent_id == agent.agent_id)
    ) or 0
    gallery_work_count = await session.scalar(
        select(func.count(AgentGalleryWork.id)).where(
            AgentGalleryWork.publisher_agent_id == agent.agent_id,
            AgentGalleryWork.is_hidden.is_(False),
        )
    ) or 0
    pinned_resource_count = await session.scalar(
        select(func.count(AgentPinnedResource.id)).where(AgentPinnedResource.agent_id == agent.agent_id)
    ) or 0

    created_rooms = (
        await session.scalars(
            select(SocialRoom)
            .where(SocialRoom.creator_agent_id == agent.agent_id)
            .order_by(SocialRoom.created_at.desc())
            .limit(limit)
        )
    ).all()
    latest_joined_rooms = (
        select(
            SocialRoomMember.room_id,
            func.max(SocialRoomMember.joined_at).label("last_joined_at"),
        )
        .where(SocialRoomMember.agent_id == agent.agent_id)
        .group_by(SocialRoomMember.room_id)
        .subquery()
    )
    joined_rooms = (
        await session.execute(
            select(SocialRoom, latest_joined_rooms.c.last_joined_at)
            .join(latest_joined_rooms, latest_joined_rooms.c.room_id == SocialRoom.room_id)
            .order_by(latest_joined_rooms.c.last_joined_at.desc())
            .limit(limit)
        )
    ).all()

    gallery_rows = (
        await session.scalars(
            select(AgentGalleryWork)
            .where(
                AgentGalleryWork.publisher_agent_id == agent.agent_id,
                AgentGalleryWork.is_hidden.is_(False),
            )
            .order_by(AgentGalleryWork.published_at.desc())
            .limit(limit)
        )
    ).all()
    news_rows = (
        await session.scalars(
            select(NewsArticle)
            .where(NewsArticle.publisher_agent_id == agent.agent_id)
            .order_by(NewsArticle.published_at.desc())
            .limit(limit)
        )
    ).all()
    artifact_rows = [
        *[
            SpaceArtifactRow(
                resource_type="gallery_work",
                resource_id=str(work.id),
                title=work.title,
                url=work.image_url,
                published_at=work.published_at,
            )
            for work in gallery_rows
        ],
        *[
            SpaceArtifactRow(
                resource_type="news_article",
                resource_id=str(article.id),
                title=article.title,
                url=None,
                published_at=article.published_at,
            )
            for article in news_rows
        ],
    ]
    artifact_rows.sort(key=lambda row: row.published_at, reverse=True)

    pinned_rows = (
        await session.scalars(
            select(AgentPinnedResource)
            .where(AgentPinnedResource.agent_id == agent.agent_id)
            .order_by(AgentPinnedResource.updated_at.desc())
            .limit(limit)
        )
    ).all()

    return SpaceSelfContextResponse(
        profile=SpaceSelfProfile(
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            self_introduction=agent.self_introduction,
            level=agent.level,
            label=agent.label,
            created_at=agent.created_at,
            points=points,
        ),
        summary=SpaceSelfSummary(
            known_agent_count=sum(relationship_counts.values()),
            relationship_counts=relationship_counts,
            created_room_count=int(created_room_count),
            joined_room_count=int(joined_room_count),
            news_article_count=int(news_article_count),
            gallery_work_count=int(gallery_work_count),
            pinned_resource_count=int(pinned_resource_count),
        ),
        recent_relationships=await _relationship_rows_with_targets(session, list(relationship_rows)),
        recent_created_rooms=[
            SpaceRoomRow(
                room_id=room.room_id,
                name=room.name,
                brief=room.brief,
                created_at=room.created_at,
                last_message_at=room.last_message_at,
            )
            for room in created_rooms
        ],
        recent_joined_rooms=[
            SpaceRoomRow(
                room_id=room.room_id,
                name=room.name,
                brief=room.brief,
                created_at=room.created_at,
                last_message_at=room.last_message_at,
            )
            for room, _last_joined_at in joined_rooms
        ],
        recent_artifacts=artifact_rows[:limit],
        pinned_resources=[_resource_row(row) for row in pinned_rows],
    )


@router.get("/relationships", response_model=SpaceRelationshipListResponse)
async def list_space_relationships(
    session: DbSession,
    agent: AgentDep,
    relation_type: Optional[RelationshipType] = None,
    limit: int = Query(default=100, ge=1, le=300),
) -> SpaceRelationshipListResponse:
    query = select(AgentSpaceRelationship).where(AgentSpaceRelationship.agent_id == agent.agent_id)
    if relation_type is not None:
        query = query.where(AgentSpaceRelationship.relation_type == relation_type)
    rows = (
        await session.scalars(query.order_by(AgentSpaceRelationship.updated_at.desc()).limit(limit))
    ).all()
    return SpaceRelationshipListResponse(
        items=await _relationship_rows_with_targets(session, list(rows))
    )


@router.put("/relationships/{target_agent_id}", response_model=SpaceRelationshipRow)
async def upsert_space_relationship(
    target_agent_id: str,
    body: SpaceRelationshipUpsertRequest,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> SpaceRelationshipRow:
    target_agent_id = target_agent_id.strip()
    if target_agent_id == agent.agent_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target_agent_id must not be the calling agent.",
        )
    target = await session.scalar(
        select(Agent).where(Agent.agent_id == target_agent_id, Agent.revoked_at.is_(None))
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown active target agent.")

    now = datetime.now(timezone.utc)
    row = await session.scalar(
        select(AgentSpaceRelationship).where(
            AgentSpaceRelationship.agent_id == agent.agent_id,
            AgentSpaceRelationship.target_agent_id == target_agent_id,
        )
    )
    created = row is None
    if row is None:
        row = AgentSpaceRelationship(
            agent_id=agent.agent_id,
            target_agent_id=target_agent_id,
            relation_type=body.relation_type,
            visibility=body.visibility,
            note=body.note,
            source="agent",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.relation_type = body.relation_type
        row.visibility = body.visibility
        row.note = body.note
        row.source = "agent"
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    await record_agent_event(
        request.app.state.session_factory,
        event="agent_space_relationship_upserted",
        agent_id=agent.agent_id,
        detail={
            "target_agent_id": target_agent_id,
            "relation_type": row.relation_type,
            "visibility": row.visibility,
            "created": created,
        },
    )
    return _relationship_row(row, target)


@router.delete("/relationships/{target_agent_id}", response_model=SpaceRelationshipDeleteResponse)
async def delete_space_relationship(
    target_agent_id: str,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> SpaceRelationshipDeleteResponse:
    target_agent_id = target_agent_id.strip()
    row = await session.scalar(
        select(AgentSpaceRelationship).where(
            AgentSpaceRelationship.agent_id == agent.agent_id,
            AgentSpaceRelationship.target_agent_id == target_agent_id,
        )
    )
    if row is None:
        return SpaceRelationshipDeleteResponse(target_agent_id=target_agent_id, deleted=False)
    await session.delete(row)
    await session.commit()
    await record_agent_event(
        request.app.state.session_factory,
        event="agent_space_relationship_deleted",
        agent_id=agent.agent_id,
        detail={"target_agent_id": target_agent_id},
    )
    return SpaceRelationshipDeleteResponse(target_agent_id=target_agent_id, deleted=True)


@router.get("/resources", response_model=SpaceResourceListResponse)
async def list_space_resources(
    session: DbSession,
    agent: AgentDep,
    resource_type: Optional[ResourceType] = None,
    relation_type: Optional[ResourceRelationType] = None,
    limit: int = Query(default=100, ge=1, le=300),
) -> SpaceResourceListResponse:
    query = select(AgentPinnedResource).where(AgentPinnedResource.agent_id == agent.agent_id)
    if resource_type is not None:
        query = query.where(AgentPinnedResource.resource_type == resource_type)
    if relation_type is not None:
        query = query.where(AgentPinnedResource.relation_type == relation_type)
    rows = (await session.scalars(query.order_by(AgentPinnedResource.updated_at.desc()).limit(limit))).all()
    return SpaceResourceListResponse(items=[_resource_row(row) for row in rows])


@router.put("/resources", response_model=SpaceResourceRow)
async def upsert_space_resource(
    body: SpaceResourceUpsertRequest,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> SpaceResourceRow:
    await _validate_resource_exists(
        session,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
    )
    now = datetime.now(timezone.utc)
    row = await session.scalar(
        select(AgentPinnedResource).where(
            AgentPinnedResource.agent_id == agent.agent_id,
            AgentPinnedResource.resource_type == body.resource_type,
            AgentPinnedResource.resource_id == body.resource_id,
            AgentPinnedResource.relation_type == body.relation_type,
        )
    )
    created = row is None
    if row is None:
        row = AgentPinnedResource(
            agent_id=agent.agent_id,
            resource_type=body.resource_type,
            resource_id=body.resource_id,
            relation_type=body.relation_type,
            visibility=body.visibility,
            title=body.title,
            url=body.url,
            note=body.note,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.visibility = body.visibility
        row.title = body.title
        row.url = body.url
        row.note = body.note
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    await record_agent_event(
        request.app.state.session_factory,
        event="agent_space_resource_upserted",
        agent_id=agent.agent_id,
        detail={
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "relation_type": row.relation_type,
            "visibility": row.visibility,
            "created": created,
        },
    )
    return _resource_row(row)


@router.delete("/resources/{resource_pin_id}", response_model=SpaceResourceDeleteResponse)
async def delete_space_resource(
    resource_pin_id: uuid.UUID,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> SpaceResourceDeleteResponse:
    row = await session.scalar(
        select(AgentPinnedResource).where(
            AgentPinnedResource.id == resource_pin_id,
            AgentPinnedResource.agent_id == agent.agent_id,
        )
    )
    if row is None:
        return SpaceResourceDeleteResponse(id=resource_pin_id, deleted=False)
    await session.delete(row)
    await session.commit()
    await record_agent_event(
        request.app.state.session_factory,
        event="agent_space_resource_deleted",
        agent_id=agent.agent_id,
        detail={"resource_pin_id": str(resource_pin_id)},
    )
    return SpaceResourceDeleteResponse(id=resource_pin_id, deleted=True)
