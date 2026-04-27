import asyncio
import logging
from datetime import timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.config import load_settings
from app.db import create_engine, create_session_factory, init_db
from app.models import SocialRoom
from app.services.display_name_resolve import load_agent_name_map
from app.routers import admin_agents, faq_public, mail, news_admin, news_public, permissions_admin, wall_admin
from app.routers.wall_public import router as wall_public_router
from app.routers.media_admin import router as media_admin_router
from app.routers.media_agent import router as media_agent_router
from app.routers.agent_profile import router as agent_profile_router
from app.routers.msgbox_agent import router as msgbox_agent_router
from app.routers.msgbox_public import router as msgbox_public_router
from app.routers.points_public import router as points_router
from app.routers.share import router as share_router
from app.routers.games_public import router as games_public_router
from app.routers.social_public import router as social_router
from app.social_registry import SocialRoomRegistry
from app.social_ttl import run_social_ttl_enforcer
from app.ws_agent import handle_agent_websocket
from app.ws_registry import AgentConnectionRegistry
from app.services.games_spectator_registry import GamesSpectatorRegistry
from app.ws_games import handle_games_websocket
from app.ws_social import handle_social_agent_websocket
from app.ws_social_observe import handle_social_observe_websocket

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    await init_db(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.registry = AgentConnectionRegistry()
    app.state.games_spectator_registry = GamesSpectatorRegistry()
    mail.init_mail_app(app, settings)

    _pub_base = (settings.public_site_base_url or "").strip().lower()
    if _pub_base.startswith("https://") and not (settings.social_observe_shared_token or "").strip():
        logger.warning(
            "SOCIAL_OBSERVE_SHARED_TOKEN is empty while PUBLIC_SITE_BASE_URL is HTTPS; "
            "/v2/social/observe is unauthenticated. Set SOCIAL_OBSERVE_SHARED_TOKEN (and frontend VITE_SOCIAL_OBSERVE_TOKEN)."
        )

    if settings.media_root.strip():
        media_images_dir = Path(settings.media_root.strip()) / "images"
        media_images_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/media", StaticFiles(directory=settings.media_root.strip()), name="media")
    else:
        logger.warning(
            "MEDIA_ROOT is not set; image upload API (/v2/admin/media/images) will return 503. "
            "Set MEDIA_ROOT to an absolute directory to enable media uploads."
        )

    social = SocialRoomRegistry()
    social.configure(
        max_concurrent_agents=settings.social_room_max_concurrent_agents,
        max_concurrent_observers=settings.social_room_max_concurrent_observers,
        idle_after=timedelta(hours=settings.social_room_idle_hours),
    )
    _idle_h = float(settings.social_room_idle_hours)
    logger.info(
        "A2A social: idle dissolve after %.4g h (%.4g d) of no new messages; "
        "enforcer every 30s; max %d agent WS / %d observer WS per room",
        _idle_h,
        _idle_h / 24.0,
        settings.social_room_max_concurrent_agents,
        settings.social_room_max_concurrent_observers,
    )
    await social.ensure_checkin_room()
    async with session_factory() as session:
        result = await session.execute(
            select(SocialRoom).where(SocialRoom.dissolved_at.is_(None))
        )
        persisted = list(result.scalars().all())
        cids = {
            r.creator_agent_id
            for r in persisted
            if r.creator_agent_id and r.creator_agent_id != "system"
        }
        name_by_id = await load_agent_name_map(session, cids) if cids else {}
        merged = await social.merge_persisted_active_rooms(persisted, name_by_id=name_by_id)
    if merged:
        logger.info("A2A social: merged %d active room(s) from database into registry", merged)
    app.state.social_registry = social

    ttl_task = asyncio.create_task(
        run_social_ttl_enforcer(social, session_factory, app.state.registry, settings)
    )

    yield

    ttl_task.cancel()
    try:
        await ttl_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(title="Zenheart v2 backend", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v2/health")
async def health_v2() -> dict[str, str]:
    """Same as /health; use when the reverse proxy only forwards /v2/*."""
    return {"status": "ok"}


app.include_router(admin_agents.router)
app.include_router(news_admin.router)
app.include_router(media_admin_router)
app.include_router(media_agent_router)
app.include_router(permissions_admin.router)
app.include_router(faq_public.router)
app.include_router(mail.router)
app.include_router(news_public.router)
app.include_router(share_router)
app.include_router(social_router)
app.include_router(points_router)
app.include_router(agent_profile_router)
app.include_router(msgbox_agent_router)
app.include_router(msgbox_public_router)
app.include_router(wall_public_router)
app.include_router(wall_admin.router)
app.include_router(games_public_router)


@app.websocket("/v2/agent/ws")
async def agent_ws(websocket: WebSocket) -> None:
    await handle_agent_websocket(websocket)


@app.websocket("/v2/games/ws")
async def games_agent_ws(websocket: WebSocket) -> None:
    await handle_games_websocket(websocket)


@app.websocket("/v2/social/ws")
async def social_agent_ws(websocket: WebSocket) -> None:
    await handle_social_agent_websocket(websocket)


@app.websocket("/v2/social/observe")
async def social_observe_ws(websocket: WebSocket) -> None:
    await handle_social_observe_websocket(websocket)
