import html
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, SettingsDep
from app.model_defs import NewsArticle, SocialRoom

router = APIRouter(prefix="/v2/share", tags=["share"])

# Two HTML responses for the same URL (Vary: User-Agent):
# - Default (Safari, Chrome, etc.): OG in <head> + client redirect to the SPA. Crawlers
#   that do not run JS still see og:* in the first response.
# - MicroMessenger: same OG + full-viewport iframe to the hash SPA, so the address bar
#   can stay on /v2/share/news/{id} for in-app "..." sharing.
_SHARE_HTML_HEADERS = {
    "Cache-Control": "private, no-cache, must-revalidate",
    "Vary": "User-Agent",
}


def _to_absolute_url(raw_url: str, public_site_base_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        return f"https:{value}"

    base = (public_site_base_url or "").strip().rstrip("/")
    if not base:
        return value
    if value.startswith("/"):
        return f"{base}{value}"
    return f"{base}/{value}"


_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <meta name="description" content="{description}" />

  <!-- Open Graph -->
  <meta property="og:type"        content="{og_type}" />
  <meta property="og:site_name"   content="Zenheart" />
  <meta property="og:url"         content="{share_url}" />
  <meta property="og:title"       content="{title}" />
  <meta property="og:description" content="{description}" />
  {og_image}

  <!-- Twitter Card -->
  <meta name="twitter:card"        content="{twitter_card}" />
  <meta name="twitter:title"       content="{title}" />
  <meta name="twitter:description" content="{description}" />
  {twitter_image}

  <!-- Canonical URL for crawlers -->
  <link rel="canonical" href="{share_url}" />
  <!-- Do not use meta refresh: some WeChat fetchers follow it and only see the SPA shell
       (card shows site name + image but no title/description). OG is read from this HTML;
       users are sent to the article via script + link below. -->
</head>
<body>
  <script>location.replace({spa_url_js});</script>
  <p><a href="{spa_url}">{cta_label}</a></p>
</body>
</html>
"""

# WeChat in-app: keep this URL in the address bar (do not replace with hash-only),
# or the "..." menu will share a URL that has no per-article OG. Load the SPA in
# a full-viewport iframe so the title bar stays on /v2/share/news/{id}.
_PAGE_WECHAT = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <meta name="description" content="{description}" />

  <meta property="og:type"        content="{og_type}" />
  <meta property="og:site_name"   content="Zenheart" />
  <meta property="og:url"         content="{share_url}" />
  <meta property="og:title"       content="{title}" />
  <meta property="og:description" content="{description}" />
  {og_image}

  <meta name="twitter:card"        content="{twitter_card}" />
  <meta name="twitter:title"       content="{title}" />
  <meta name="twitter:description" content="{description}" />
  {twitter_image}

  <link rel="canonical" href="{share_url}" />
  <style>html,body{{margin:0;height:100%;overflow:hidden}}</style>
</head>
<body>
  <iframe
    style="position:fixed;inset:0;width:100%;height:100%;border:0"
    title="{title}"
    src="{spa_url}"
  ></iframe>
  <p style="position:fixed;left:8px;bottom:8px;font-size:12px;opacity:0.7;margin:0">
    <a href="{spa_url}">Open without frame</a>
  </p>
</body>
</html>
"""


@router.get("/news/{article_id}", response_class=HTMLResponse)
async def share_news_article(
    request: Request,
    article_id: UUID,
    session: DbSession,
    settings: SettingsDep,
) -> HTMLResponse:
    article = await session.scalar(select(NewsArticle).where(NewsArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found.")

    base = settings.public_site_base_url.rstrip("/")
    share_url = f"{base}/v2/share/news/{article_id}"
    spa_url = f"{base}/#/news/{article_id}"

    title = html.escape(article.title, quote=True)
    raw_summary = (article.summary or "").strip()
    if not raw_summary:
        raw_summary = (article.title or "").strip() or "Zenheart"
    description = html.escape(raw_summary[:200], quote=True)

    image_url = _to_absolute_url(article.cover_image_url, settings.public_site_base_url)
    if image_url:
        img = html.escape(image_url, quote=True)
        og_image = (
            f'<meta property="og:image" content="{img}" />'
            f'<meta property="og:image:secure_url" content="{img}" />'
            f'<meta property="og:image:alt" content="{title}" />'
        )
        twitter_image = f'<meta name="twitter:image" content="{img}" />'
        twitter_card = "summary_large_image"
    else:
        og_image = ""
        twitter_image = ""
        twitter_card = "summary"

    common = {
        "title": title,
        "description": description,
        "share_url": html.escape(share_url, quote=True),
        "spa_url": html.escape(spa_url, quote=True),
        "og_image": og_image,
        "twitter_image": twitter_image,
        "twitter_card": twitter_card,
        "og_type": "article",
        "cta_label": html.escape("Continue to article", quote=True),
    }

    ua = (request.headers.get("user-agent") or "").lower()
    is_wechat = "micromessenger" in ua
    if is_wechat:
        body = _PAGE_WECHAT.format(**common)
    else:
        body = _PAGE.format(**common, spa_url_js=json.dumps(spa_url))
    return HTMLResponse(
        content=body, status_code=200, headers=dict(_SHARE_HTML_HEADERS)
    )


_SOCIAL_ROOM_ID_MAX_LEN = 80


async def _social_room_share_title_description(
    request: Request,
    room_id: str,
    session: AsyncSession,
) -> tuple[str, str]:
    """Return (raw_title, raw_description) before HTML escaping."""
    rid = (room_id or "").strip()
    if not rid or len(rid) > _SOCIAL_ROOM_ID_MAX_LEN:
        return "Social room", "Open this link in Zenheart."

    social = request.app.state.social_registry
    live = await social.get_room(rid)
    if live is not None:
        if not live.observable or live.is_private:
            return "Zenheart", "Social room on Zenheart."
        brief = (live.brief or "").strip()
        name = (live.name or "").strip()
        headline = brief or name or "Social room"
        rules = (live.rules or "").strip()
        raw_desc = rules or brief or name or "Join this room on Zenheart."
        return headline[:200], raw_desc[:500]

    row = await session.get(SocialRoom, rid)
    if row is not None:
        if not row.observable or row.is_private:
            return "Zenheart", "Social room on Zenheart."
        brief = (row.brief or "").strip()
        name = (row.name or "").strip()
        headline = brief or name or "Social room"
        rules = (row.rules or "").strip()
        raw_desc = rules or brief or name or "Open this room on Zenheart."
        return headline[:200], raw_desc[:500]

    return "Social room", "Open this link in Zenheart."


@router.get("/social/room/{room_id}", response_class=HTMLResponse)
async def share_social_room(
    request: Request,
    room_id: str,
    session: DbSession,
    settings: SettingsDep,
) -> HTMLResponse:
    base = settings.public_site_base_url.rstrip("/")
    rid = (room_id or "").strip()
    if not rid or len(rid) > _SOCIAL_ROOM_ID_MAX_LEN:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid room id.")

    share_url = f"{base}/v2/share/social/room/{rid}"
    spa_url = f"{base}/#/social/room/{rid}"

    raw_title, raw_desc = await _social_room_share_title_description(request, rid, session)
    title = html.escape((raw_title or "Social room").strip() or "Social room", quote=True)
    description = html.escape((raw_desc or "Zenheart").strip()[:200] or "Zenheart", quote=True)

    og_image = ""
    twitter_image = ""
    twitter_card = "summary"

    common = {
        "title": title,
        "description": description,
        "share_url": html.escape(share_url, quote=True),
        "spa_url": html.escape(spa_url, quote=True),
        "og_image": og_image,
        "twitter_image": twitter_image,
        "twitter_card": twitter_card,
        "og_type": "website",
        "cta_label": html.escape("Open room", quote=True),
    }

    ua = (request.headers.get("user-agent") or "").lower()
    is_wechat = "micromessenger" in ua
    if is_wechat:
        body = _PAGE_WECHAT.format(**common)
    else:
        body = _PAGE.format(**common, spa_url_js=json.dumps(spa_url))
    return HTMLResponse(
        content=body, status_code=200, headers=dict(_SHARE_HTML_HEADERS)
    )
