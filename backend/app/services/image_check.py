from __future__ import annotations

import httpx

_TIMEOUT = 8.0
_FALLBACK_METHODS = ("head", "get")


async def check_image_url(url: str) -> str | None:
    """Verify that *url* resolves to an accessible image resource.

    Tries HEAD first; if the server rejects HEAD (405 / 501) it retries with
    a GET that streams only the response headers (no body downloaded).

    Returns None when the URL is valid and reachable.
    Returns a human-readable error string on any failure so the caller can
    embed it directly in a validation error detail.
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
