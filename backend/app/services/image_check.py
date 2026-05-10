from __future__ import annotations

from pathlib import Path

import httpx

_TIMEOUT = 8.0
_FALLBACK_METHODS = ("head", "get")


def sniff_image_content_type(data: bytes) -> str | None:
    """Return an ``image/*`` MIME type from magic bytes, or None if unrecognized.

    nginx and browsers map ``Content-Type`` from the stored file extension; the
    upload APIs must save with an extension that matches the real format so
    room messages and ``<img>`` decode correctly.
    """
    if not data:
        return None
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    text_head = data[:4096].decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n")
    lowered = text_head[:512].lower()
    if lowered.startswith("<?xml") or lowered.startswith("<svg") or "<svg" in lowered or lowered.startswith(
        "<!doctype svg"
    ):
        return "image/svg+xml"
    return None


def is_trusted_media_url(url: str, *, public_site_base_url: str, media_public_base_url: str) -> bool:
    """Return True if *url* refers to a locally-hosted image that does not need remote verification.

    Trusted patterns:
    - Relative path starting with /media/ (served by this app's StaticFiles or nginx alias)
    - Absolute URL whose prefix matches MEDIA_PUBLIC_BASE_URL (custom CDN/storage we control)
    - Absolute URL whose prefix matches PUBLIC_SITE_BASE_URL/media (same host, /media path)
    """
    if url.startswith("/media/"):
        return True
    if media_public_base_url.strip():
        prefix = media_public_base_url.rstrip("/") + "/"
        if url.startswith(prefix):
            return True
    if public_site_base_url.strip():
        prefix = public_site_base_url.rstrip("/") + "/media/"
        if url.startswith(prefix):
            return True
    return False


def absolute_url_for_http_fetch(url: str, *, public_site_base_url: str) -> str | None:
    """Return an absolute URL suitable for httpx, or None if *url* is relative and no base is configured."""
    value = (url or "").strip()
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        return f"https:{value}"
    base = public_site_base_url.strip().rstrip("/")
    if not base:
        return None
    if value.startswith("/"):
        return f"{base}{value}"
    return f"{base}/{value}"


def local_media_file_for_url(url: str, *, media_root: str) -> Path | None:
    """If *url* is ``/media/...`` (StaticFiles mount), return the resolved path under MEDIA_ROOT.

    Returns None when the URL is not under ``/media/``, MEDIA_ROOT is unset, or the path escapes the root.
    """
    raw = (url or "").strip()
    if not raw.startswith("/media/"):
        return None
    mr = media_root.strip()
    if not mr:
        return None
    root = Path(mr).resolve()
    suffix = raw.removeprefix("/media/").lstrip("/")
    if not suffix:
        return None
    if ".." in suffix.split("/"):
        return None
    candidate = (root / suffix).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


async def verify_news_cover_image_url(
    url: str,
    *,
    public_site_base_url: str,
    media_root: str,
) -> str | None:
    """Ensure a news cover URL resolves to a non-empty image.

    For ``/media/...`` and configured MEDIA_ROOT, checks the file on disk first (no HTTP).
    Otherwise performs the same HEAD/GET + Content-Type checks as :func:`check_image_url`
    against an absolute URL (needs PUBLIC_SITE_BASE_URL for relative paths).

    Returns None when valid; otherwise a human-readable error string (same style as ``check_image_url``).
    """
    u = url.strip()
    local = local_media_file_for_url(u, media_root=media_root)
    if local is not None:
        if local.is_file() and local.stat().st_size > 0:
            return None
        return "cover_image_url: file does not exist or is empty under MEDIA_ROOT"

    fetch_u = absolute_url_for_http_fetch(u, public_site_base_url=public_site_base_url)
    if fetch_u is None:
        return (
            "cover_image_url: set PUBLIC_SITE_BASE_URL to verify this URL, "
            "or use /media/... with MEDIA_ROOT configured"
        )
    return await check_image_url(fetch_u)


async def check_image_url(url: str) -> str | None:
    """Verify that *url* resolves to an accessible image resource.

    Tries HEAD first; if the server rejects HEAD (405 / 501) it retries with
    a GET that streams only the response headers (no body downloaded).

    Returns None when the URL is valid and reachable.
    Returns a human-readable error string on any failure so the caller can
    embed it directly in a validation error detail.

    News publish flows should use :func:`verify_news_cover_image_url` instead of branching on trust.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT) as client:
        for method in _FALLBACK_METHODS:
            try:
                if method == "head":
                    resp = await client.head(url)
                else:
                    # Stream GET so we never download the body.
                    async with client.stream("GET", url) as resp:
                        pass

            except httpx.TimeoutException:
                return "cover_image_url: request timed out after 8 s"
            except httpx.RequestError as exc:
                return f"cover_image_url: network error — {exc}"

            if resp.status_code in (405, 501) and method == "head":
                # Server does not support HEAD — retry with GET.
                continue

            if resp.status_code >= 400:
                return f"cover_image_url: server returned HTTP {resp.status_code}"

            content_type = resp.headers.get("content-type", "")
            if content_type and not content_type.startswith("image/"):
                return (
                    f"cover_image_url: Content-Type is '{content_type}', expected image/*"
                )

            return None

    return "cover_image_url: could not verify image (HEAD and GET both failed)"
