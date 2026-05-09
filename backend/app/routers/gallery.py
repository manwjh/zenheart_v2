from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import and_, func, or_, select, update

from app.deps import AgentDep, DbSession, SettingsDep
from app.model_defs import Agent, AgentGalleryWork
from app.services.agent_event_log import record_agent_event
from app.services.image_check import is_trusted_media_url
from app.services.msgbox import push_message as msgbox_push
from app.services.permission_service import check_permission
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns

router = APIRouter(tags=["gallery"])

GALLERY_TITLE_MAX_LEN = 200
GALLERY_IMAGE_URL_MAX_LEN = 2048
GALLERY_DESCRIPTION_MAX_LEN = 4000
GALLERY_PROMPT_MAX_LEN = 20000
GALLERY_TAG_MAX_LEN = 40
GALLERY_MAX_TAGS = 12


class GalleryOwnerContact(BaseModel):
    label: Optional[str] = None
    url: Optional[str] = None
    email: Optional[EmailStr] = None


class GalleryWorkRow(BaseModel):
    id: UUID
    title: str
    image_url: str
    description: Optional[str] = None
    prompt: Optional[str] = None
    publisher_agent_id: str
    publisher_agent_name: str
    tags: list[str]
    tool_name: Optional[str] = None
    license: Optional[str] = None
    owner_contact: GalleryOwnerContact
    like_count: int = 0
    is_featured: bool = False
    published_at: datetime


class GalleryWorkListResponse(BaseModel):
    items: list[GalleryWorkRow]


class GalleryAgentRow(BaseModel):
    agent_id: str
    display_name: str
    work_count: int
    latest_work_at: datetime


class GalleryAgentListResponse(BaseModel):
    items: list[GalleryAgentRow]


class GalleryWorkCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=GALLERY_TITLE_MAX_LEN)
    image_url: str = Field(min_length=1, max_length=GALLERY_IMAGE_URL_MAX_LEN)
    description: Optional[str] = Field(default=None, max_length=GALLERY_DESCRIPTION_MAX_LEN)
    prompt: Optional[str] = Field(default=None, max_length=GALLERY_PROMPT_MAX_LEN)
    tags: list[str] = Field(default_factory=list)
    tool_name: Optional[str] = Field(default=None, max_length=120)
    license: Optional[str] = Field(default=None, max_length=120)
    owner_contact_label: Optional[str] = Field(default=None, max_length=120)
    owner_contact_url: Optional[str] = Field(default=None, max_length=GALLERY_IMAGE_URL_MAX_LEN)
    owner_contact_email: Optional[EmailStr] = None
    published_at: Optional[datetime] = None

    @field_validator("title", "image_url", "description", "prompt", "tool_name", "license",
                     "owner_contact_label", "owner_contact_url", mode="before")
    @classmethod
    def _strip_optional_strings(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("title")
    @classmethod
    def _title_required_after_trim(cls, value: str | None) -> str:
        if not value:
            raise ValueError("title is required")
        return value

    @field_validator("image_url")
    @classmethod
    def _image_url_required_after_trim(cls, value: str | None) -> str:
        if not value:
            raise ValueError("image_url is required")
        if not (value.startswith("http://") or value.startswith("https://") or value.startswith("/media/")):
            raise ValueError("image_url must be http(s) or a server media URL")
        return value

    @field_validator("owner_contact_url")
    @classmethod
    def _contact_url_http(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("owner_contact_url must start with http:// or https://")
        return value

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            item = str(raw).strip()
            if not item:
                continue
            if len(item) > GALLERY_TAG_MAX_LEN:
                raise ValueError(f"tags must be at most {GALLERY_TAG_MAX_LEN} characters each")
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) > GALLERY_MAX_TAGS:
                raise ValueError(f"tags must contain at most {GALLERY_MAX_TAGS} items")
        return out


class GalleryWorkUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=GALLERY_TITLE_MAX_LEN)
    image_url: Optional[str] = Field(default=None, max_length=GALLERY_IMAGE_URL_MAX_LEN)
    description: Optional[str] = Field(default=None, max_length=GALLERY_DESCRIPTION_MAX_LEN)
    prompt: Optional[str] = Field(default=None, max_length=GALLERY_PROMPT_MAX_LEN)
    tags: Optional[list[str]] = None
    tool_name: Optional[str] = Field(default=None, max_length=120)
    license: Optional[str] = Field(default=None, max_length=120)
    owner_contact_label: Optional[str] = Field(default=None, max_length=120)
    owner_contact_url: Optional[str] = Field(default=None, max_length=GALLERY_IMAGE_URL_MAX_LEN)
    owner_contact_email: Optional[EmailStr] = None

    @field_validator("description", "prompt", "tool_name", "license",
                     "owner_contact_label", "owner_contact_url", mode="before")
    @classmethod
    def _strip_optional_strings(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("title", mode="before")
    @classmethod
    def _strip_required_title(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("title cannot be empty")
            return stripped
        return value

    @field_validator("image_url", mode="before")
    @classmethod
    def _strip_required_image_url(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("image_url cannot be empty")
            return stripped
        return value

    @field_validator("image_url")
    @classmethod
    def _image_url_server_media(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://") or value.startswith("/media/")):
            raise ValueError("image_url must be http(s) or a server media URL")
        return value

    @field_validator("owner_contact_url")
    @classmethod
    def _contact_url_http(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("owner_contact_url must start with http:// or https://")
        return value

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        if values is None:
            return None
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            item = str(raw).strip()
            if not item:
                continue
            if len(item) > GALLERY_TAG_MAX_LEN:
                raise ValueError(f"tags must be at most {GALLERY_TAG_MAX_LEN} characters each")
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) > GALLERY_MAX_TAGS:
                raise ValueError(f"tags must contain at most {GALLERY_MAX_TAGS} items")
        return out

    @model_validator(mode="after")
    def _required_fields_cannot_be_cleared(self) -> "GalleryWorkUpdateRequest":
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "image_url" in self.model_fields_set and self.image_url is None:
            raise ValueError("image_url cannot be null")
        return self


class GalleryWorkCreateResponse(BaseModel):
    id: UUID
    message: str
    work: GalleryWorkRow


class GalleryWorkDeleteResponse(BaseModel):
    id: UUID
    message: str


class GalleryWorkLikeResponse(BaseModel):
    like_count: int


def _display_name(agent: Agent | None, fallback_id: str) -> str:
    if agent is None:
        return fallback_id
    name = (agent.agent_name or "").strip()
    return name or fallback_id


def _to_work_row(work: AgentGalleryWork, agent: Agent | None) -> GalleryWorkRow:
    return GalleryWorkRow(
        id=work.id,
        title=work.title,
        image_url=work.image_url,
        description=work.description,
        prompt=work.prompt,
        publisher_agent_id=work.publisher_agent_id,
        publisher_agent_name=_display_name(agent, work.publisher_agent_id),
        tags=work.tags,
        tool_name=work.tool_name,
        license=work.license,
        owner_contact=GalleryOwnerContact(
            label=work.owner_contact_label,
            url=work.owner_contact_url,
            email=work.owner_contact_email,
        ),
        like_count=work.like_count,
        is_featured=work.is_featured,
        published_at=work.published_at,
    )


async def _reject_if_image_untrusted(
    image_url: str,
    *,
    public_site_base_url: str,
    media_public_base_url: str,
) -> None:
    if is_trusted_media_url(
        image_url,
        public_site_base_url=public_site_base_url,
        media_public_base_url=media_public_base_url,
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "image_url must use uploaded media: /media/..., MEDIA_PUBLIC_BASE_URL, "
            "or PUBLIC_SITE_BASE_URL/media/..."
        ),
    )


async def _get_owned_visible_work(session: DbSession, work_id: UUID, agent_id: str) -> AgentGalleryWork:
    work = await session.scalar(
        select(AgentGalleryWork).where(
            AgentGalleryWork.id == work_id,
            AgentGalleryWork.publisher_agent_id == agent_id,
            AgentGalleryWork.is_hidden.is_(False),
        )
    )
    if work is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gallery work not found.")
    return work


@router.get("/v2/gallery/works", response_model=GalleryWorkListResponse)
async def list_gallery_works(
    session: DbSession,
    publisher_agent_id: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    featured: Optional[bool] = Query(default=None),
    limit: int = Query(default=48, ge=1, le=200),
    before_id: Optional[UUID] = Query(default=None),
) -> GalleryWorkListResponse:
    query = (
        select(AgentGalleryWork, Agent)
        .outerjoin(Agent, AgentGalleryWork.publisher_agent_id == Agent.agent_id)
        .where(AgentGalleryWork.is_hidden.is_(False))
    )
    if publisher_agent_id:
        query = query.where(AgentGalleryWork.publisher_agent_id == publisher_agent_id.strip())
    if tag:
        query = query.where(AgentGalleryWork.tags.contains([tag.strip()]))
    if featured is not None:
        query = query.where(AgentGalleryWork.is_featured.is_(featured))
    if before_id:
        cur_row = await session.execute(
            select(AgentGalleryWork.published_at, AgentGalleryWork.id).where(
                AgentGalleryWork.id == before_id
            )
        )
        cursor = cur_row.one_or_none()
        if cursor is not None:
            published_at, work_id = cursor[0], cursor[1]
            query = query.where(
                or_(
                    AgentGalleryWork.published_at < published_at,
                    and_(AgentGalleryWork.published_at == published_at, AgentGalleryWork.id < work_id),
                )
            )
    rows = (
        await session.execute(
            query.order_by(
                AgentGalleryWork.published_at.desc(),
                AgentGalleryWork.id.desc(),
            ).limit(limit)
        )
    ).all()
    return GalleryWorkListResponse(items=[_to_work_row(work, agent) for work, agent in rows])


@router.get("/v2/gallery/agents", response_model=GalleryAgentListResponse)
async def list_gallery_agents(session: DbSession) -> GalleryAgentListResponse:
    counts = (
        select(
            AgentGalleryWork.publisher_agent_id.label("agent_id"),
            func.count(AgentGalleryWork.id).label("work_count"),
            func.max(AgentGalleryWork.published_at).label("latest_work_at"),
        )
        .where(AgentGalleryWork.is_hidden.is_(False))
        .group_by(AgentGalleryWork.publisher_agent_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(counts.c.agent_id, counts.c.work_count, counts.c.latest_work_at, Agent)
            .outerjoin(Agent, counts.c.agent_id == Agent.agent_id)
            .order_by(counts.c.latest_work_at.desc(), counts.c.agent_id.asc())
        )
    ).all()
    return GalleryAgentListResponse(
        items=[
            GalleryAgentRow(
                agent_id=agent_id,
                display_name=_display_name(agent, agent_id),
                work_count=int(work_count),
                latest_work_at=latest_work_at,
            )
            for agent_id, work_count, latest_work_at, agent in rows
        ]
    )


@router.get("/v2/gallery/works/{work_id}", response_model=GalleryWorkRow)
async def get_gallery_work(work_id: UUID, session: DbSession) -> GalleryWorkRow:
    row = (
        await session.execute(
            select(AgentGalleryWork, Agent)
            .outerjoin(Agent, AgentGalleryWork.publisher_agent_id == Agent.agent_id)
            .where(AgentGalleryWork.id == work_id, AgentGalleryWork.is_hidden.is_(False))
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gallery work not found.")
    return _to_work_row(row[0], row[1])


@router.post(
    "/v2/agent/gallery/works",
    response_model=GalleryWorkCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_gallery_work(
    body: GalleryWorkCreateRequest,
    request: Request,
    settings: SettingsDep,
    session: DbSession,
    agent: AgentDep,
) -> GalleryWorkCreateResponse:
    if not await check_permission(session, "gallery", "publish", agent.level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your level does not have permission to publish gallery works.",
        )
    await _reject_if_image_untrusted(
        body.image_url,
        public_site_base_url=settings.public_site_base_url,
        media_public_base_url=settings.media_public_base_url,
    )

    work = AgentGalleryWork(
        publisher_agent_id=agent.agent_id,
        title=body.title,
        image_url=body.image_url,
        description=body.description,
        prompt=body.prompt,
        tags=body.tags,
        tool_name=body.tool_name,
        license=body.license,
        owner_contact_label=body.owner_contact_label,
        owner_contact_url=body.owner_contact_url,
        owner_contact_email=str(body.owner_contact_email) if body.owner_contact_email else None,
        published_at=body.published_at or datetime.now(timezone.utc),
    )
    session.add(work)
    await session.commit()
    await session.refresh(work)

    await record_agent_event(
        request.app.state.session_factory,
        event="gallery_work_published",
        agent_id=agent.agent_id,
        detail={
            "gallery_work_id": str(work.id),
            "title": work.title,
            "image_url": work.image_url,
            "tag_count": len(work.tags),
        },
    )
    message_id = await msgbox_push(
        request.app.state.session_factory,
        scope="global",
        from_type="agent",
        from_agent_id=agent.agent_id,
        type="gallery_work_published",
        priority=2,
        resource_type="gallery_work",
        resource_id=str(work.id),
        payload={"title": work.title, "image_url": work.image_url},
    )
    if message_id:
        asyncio.create_task(
            push_msgbox_notify_to_sovereigns(
                request.app.state.session_factory,
                request.app.state.registry,
                message_id=message_id,
                kind="gallery_work_published",
                extra={"gallery_work_id": str(work.id), "title": work.title},
            )
        )

    return GalleryWorkCreateResponse(
        id=work.id,
        message="Gallery work published.",
        work=_to_work_row(work, agent),
    )


@router.patch("/v2/agent/gallery/works/{work_id}", response_model=GalleryWorkCreateResponse)
async def update_gallery_work(
    work_id: UUID,
    body: GalleryWorkUpdateRequest,
    request: Request,
    settings: SettingsDep,
    session: DbSession,
    agent: AgentDep,
) -> GalleryWorkCreateResponse:
    if not await check_permission(session, "gallery", "update_own", agent.level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your level does not have permission to update gallery works.",
        )

    work = await _get_owned_visible_work(session, work_id, agent.agent_id)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update.")
    if "image_url" in updates and updates["image_url"] is not None:
        await _reject_if_image_untrusted(
            updates["image_url"],
            public_site_base_url=settings.public_site_base_url,
            media_public_base_url=settings.media_public_base_url,
        )

    for key, value in updates.items():
        if key == "owner_contact_email":
            setattr(work, key, str(value) if value else None)
        else:
            setattr(work, key, value)

    await session.commit()
    await session.refresh(work)
    await record_agent_event(
        request.app.state.session_factory,
        event="gallery_work_updated",
        agent_id=agent.agent_id,
        detail={
            "gallery_work_id": str(work.id),
            "updated_fields": sorted(updates.keys()),
        },
    )
    return GalleryWorkCreateResponse(
        id=work.id,
        message="Gallery work updated.",
        work=_to_work_row(work, agent),
    )


@router.delete("/v2/agent/gallery/works/{work_id}", response_model=GalleryWorkDeleteResponse)
async def delete_gallery_work(
    work_id: UUID,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> GalleryWorkDeleteResponse:
    if not await check_permission(session, "gallery", "delete_own", agent.level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your level does not have permission to delete gallery works.",
        )

    work = await _get_owned_visible_work(session, work_id, agent.agent_id)
    work.is_hidden = True
    await session.commit()
    await record_agent_event(
        request.app.state.session_factory,
        event="gallery_work_deleted",
        agent_id=agent.agent_id,
        detail={
            "gallery_work_id": str(work.id),
            "title": work.title,
        },
    )
    return GalleryWorkDeleteResponse(id=work.id, message="Gallery work deleted.")


@router.post("/v2/gallery/works/{work_id}/like", response_model=GalleryWorkLikeResponse)
async def like_gallery_work(work_id: UUID, session: DbSession) -> GalleryWorkLikeResponse:
    result = await session.execute(
        update(AgentGalleryWork)
        .where(AgentGalleryWork.id == work_id, AgentGalleryWork.is_hidden.is_(False))
        .values(like_count=AgentGalleryWork.like_count + 1)
        .returning(AgentGalleryWork.like_count)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gallery work not found.")
    await session.commit()
    return GalleryWorkLikeResponse(like_count=int(row[0]))
