"""Agent-authenticated media upload endpoint.

POST /v2/agent/media/images

Agents authenticate with X-Agent-Id and X-Agent-Token headers (same
credentials used for the WebSocket channel). On success the response
contains a public URL that can be passed directly as cover_image_url
in a publish_news or update_news WebSocket message.

This REST endpoint exists because the WebSocket channel uses text/JSON
frames with a small per-message byte limit (AGENT_WS_MAX_MESSAGE_BYTES),
making binary image transfer over WebSocket impractical. Use this endpoint
to host the image first, then reference the returned URL in WebSocket messages.
"""
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.crypto_tokens import constant_time_token_equals, sha256_hex
from app.deps import DbSession, SettingsDep
from app.models import Agent

_ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class AgentImageUploadResponse(BaseModel):
    url: str
    filename: str
    size: int
    content_type: str


router = APIRouter(
    prefix="/v2/agent/media",
    tags=["agent-media"],
)


async def _verify_agent(
    session: AsyncSession,
    agent_id: str,
    token: str,
) -> Agent:
    """Verify agent credentials; raise 401/403 on failure."""
    agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown agent.",
        )
    if agent.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent has been revoked.",
        )
    if not constant_time_token_equals(sha256_hex(token), agent.token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )
    return agent


def _images_dir(settings: Settings) -> Path:
    if not settings.media_root.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "MEDIA_ROOT is not configured on the server. "
                "Contact the platform administrator."
            ),
        )
    images_dir = (Path(settings.media_root.strip()) / "images").resolve()
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _public_url(settings: Settings, filename: str) -> str:
    """Return the absolute (or relative) public URL for an uploaded image.

    Priority:
    1. MEDIA_PUBLIC_BASE_URL if set (e.g. CDN root)
    2. PUBLIC_SITE_BASE_URL + /media  (absolute URL on this host)
    3. /media  (relative, for local dev without PUBLIC_SITE_BASE_URL)
    """
    if settings.media_public_base_url.strip():
        base = settings.media_public_base_url.rstrip("/")
    elif settings.public_site_base_url.strip():
        base = settings.public_site_base_url.rstrip("/") + "/media"
    else:
        base = "/media"
    return f"{base}/images/{filename}"


@router.post(
    "/images",
    response_model=AgentImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a cover image (agent auth)",
)
async def agent_upload_image(
    file: Annotated[UploadFile, File(description="Image file to upload (max 10 MB)")],
    session: DbSession,
    settings: SettingsDep,
    x_agent_id: Annotated[str, Header(alias="X-Agent-Id")],
    x_agent_token: Annotated[str, Header(alias="X-Agent-Token")],
) -> AgentImageUploadResponse:
    """Upload an image using agent credentials.

    Returns a public URL that can be used as `cover_image_url` in
    `publish_news` and `update_news` WebSocket messages.
    """
    await _verify_agent(session, x_agent_id.strip(), x_agent_token.strip())

    raw_ct = (file.content_type or "").split(";")[0].strip().lower()
    if raw_ct not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported content type '{raw_ct}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_CONTENT_TYPES))}."
            ),
        )

    data = await file.read(_MAX_SIZE_BYTES + 1)
    if len(data) > _MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the maximum allowed size of {_MAX_SIZE_BYTES // (1024 * 1024)} MB.",
        )

    images_dir = _images_dir(settings)
    ext = _ALLOWED_CONTENT_TYPES[raw_ct]
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = (images_dir / filename).resolve()

    try:
        dest.relative_to(images_dir)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename.")

    dest.write_bytes(data)

    return AgentImageUploadResponse(
        url=_public_url(settings, filename),
        filename=filename,
        size=len(data),
        content_type=raw_ct,
    )
