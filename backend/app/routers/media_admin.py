"""Admin media upload/management endpoints.

POST   /v2/admin/media/images          — upload an image file
GET    /v2/admin/media/images          — list uploaded images
DELETE /v2/admin/media/images/{name}   — delete an uploaded image

All endpoints require X-Admin-Key header.
The MEDIA_ROOT env var must be set; otherwise a 503 is returned.
Uploaded files are served by the StaticFiles mount at /media/.
"""
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.deps import SettingsDep, admin_or_sovereign_guard
from app.services.image_check import sniff_image_content_type

_ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class ImageUploadResponse(BaseModel):
    url: str
    filename: str
    size: int
    content_type: str


class ImageListItem(BaseModel):
    filename: str
    url: str
    size: int


class ImageListResponse(BaseModel):
    items: list[ImageListItem]


router = APIRouter(
    prefix="/v2/admin/media",
    tags=["admin-media"],
    dependencies=[Depends(admin_or_sovereign_guard)],
)


def _images_dir(settings: SettingsDep) -> Path:
    """Resolve and create the images sub-directory under MEDIA_ROOT."""
    if not settings.media_root.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "MEDIA_ROOT is not configured. "
                "Set it to an absolute directory path in your environment."
            ),
        )
    images_dir = (Path(settings.media_root.strip()) / "images").resolve()
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _public_url(settings: SettingsDep, filename: str) -> str:
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


@router.post("/images", response_model=ImageUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: Annotated[UploadFile, File(description="Image file to upload (max 10 MB)")],
    settings: SettingsDep,
) -> ImageUploadResponse:
    """Upload an image file and return its public URL."""
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

    actual_ct = sniff_image_content_type(data)
    if actual_ct is None or actual_ct not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File is not a recognized image (magic bytes do not match a supported format).",
        )

    images_dir = _images_dir(settings)
    ext = _ALLOWED_CONTENT_TYPES[actual_ct]
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = (images_dir / filename).resolve()

    # Paranoia: ensure the resolved path stays inside images_dir.
    try:
        dest.relative_to(images_dir)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename.")

    dest.write_bytes(data)

    return ImageUploadResponse(
        url=_public_url(settings, filename),
        filename=filename,
        size=len(data),
        content_type=actual_ct,
    )


@router.get("/images", response_model=ImageListResponse)
async def list_images(settings: SettingsDep) -> ImageListResponse:
    """List all uploaded images."""
    images_dir = _images_dir(settings)
    allowed_suffixes = set(_ALLOWED_CONTENT_TYPES.values())
    items = [
        ImageListItem(
            filename=p.name,
            url=_public_url(settings, p.name),
            size=p.stat().st_size,
        )
        for p in sorted(images_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if p.is_file() and p.suffix.lower() in allowed_suffixes
    ]
    return ImageListResponse(items=items)


@router.delete("/images/{filename}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_image(filename: str, settings: SettingsDep) -> Response:
    """Delete an uploaded image by filename."""
    images_dir = _images_dir(settings)
    target = (images_dir / filename).resolve()

    try:
        target.relative_to(images_dir)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename.")

    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    target.unlink()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
