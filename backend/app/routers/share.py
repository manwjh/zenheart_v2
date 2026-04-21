import html
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.deps import DbSession, SettingsDep
from app.models import NewsArticle

router = APIRouter(prefix="/v2/share", tags=["share"])

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>

  <!-- Open Graph -->
  <meta property="og:type"        content="article" />
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

  <!-- Canonical redirect -->
  <link rel="canonical" href="{share_url}" />
  <meta http-equiv="refresh" content="0;url={spa_url}" />
</head>
<body>
  <script>location.replace({spa_url_js});</script>
  <p><a href="{spa_url}">Continue to article →</a></p>
</body>
</html>
"""


@router.get("/news/{article_id}", response_class=HTMLResponse)
async def share_news_article(
    article_id: UUID, session: DbSession, settings: SettingsDep
) -> HTMLResponse:
    article = await session.scalar(select(NewsArticle).where(NewsArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found.")

    base = settings.public_site_base_url.rstrip("/")
    share_url = f"{base}/share/news/{article_id}"
    spa_url = f"{base}/#/news?article={article_id}"

    title = html.escape(article.title, quote=True)
    description = html.escape(article.summary[:200], quote=True)

    if article.cover_image_url:
        img = html.escape(article.cover_image_url, quote=True)
        og_image = f'<meta property="og:image" content="{img}" />'
        twitter_image = f'<meta name="twitter:image" content="{img}" />'
        twitter_card = "summary_large_image"
    else:
        og_image = ""
        twitter_image = ""
        twitter_card = "summary"

    body = _PAGE.format(
        title=title,
        description=description,
        share_url=html.escape(share_url, quote=True),
        spa_url=html.escape(spa_url, quote=True),
        spa_url_js=f'"{spa_url}"',
        og_image=og_image,
        twitter_image=twitter_image,
        twitter_card=twitter_card,
    )
    return HTMLResponse(content=body, status_code=200)
