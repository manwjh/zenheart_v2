import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.config import load_settings
from app.db import create_engine, create_session_factory, init_db
from app.model_defs import SocialRoom
from app.routers import mail
from app.services.display_name_resolve import load_agent_name_map
from app.services.ws_debug_tap import WsDebugTap
from app.social_registry import SocialRoomRegistry
from app.social_ttl import run_social_ttl_enforcer
from app.ws_registry import AgentConnectionRegistry

logger = logging.getLogger(__name__)


async def _configure_social_registry(app: FastAPI) -> SocialRoomRegistry:
    settings = app.state.settings
    session_factory = app.state.session_factory
    social = SocialRoomRegistry()
    social.configure(
        max_concurrent_agents=settings.social_room_max_concurrent_agents,
        max_concurrent_observers=settings.social_room_max_concurrent_observers,
        idle_after=timedelta(hours=settings.social_room_idle_hours),
    )
    idle_h = float(settings.social_room_idle_hours)
    logger.info(
        "A2A social: idle dissolve after %.4g h (%.4g d) of no new messages; "
        "enforcer every 30s; max %d agent WS / %d observer WS per room",
        idle_h,
        idle_h / 24.0,
        settings.social_room_max_concurrent_agents,
        settings.social_room_max_concurrent_observers,
    )
    async with session_factory() as session:
        result = await session.execute(select(SocialRoom).where(SocialRoom.dissolved_at.is_(None)))
        persisted = list(result.scalars().all())
        creator_ids = {
            room.creator_agent_id
            for room in persisted
            if room.creator_agent_id and room.creator_agent_id != "system"
        }
        name_by_id = await load_agent_name_map(session, creator_ids) if creator_ids else {}
        merged = await social.merge_persisted_active_rooms(persisted, name_by_id=name_by_id)
    if merged:
        logger.info("A2A social: merged %d active room(s) from database into registry", merged)
    return social


def _configure_media_mount(app: FastAPI) -> None:
    settings = app.state.settings
    if settings.media_root.strip():
        media_images_dir = Path(settings.media_root.strip()) / "images"
        media_images_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/media", StaticFiles(directory=settings.media_root.strip()), name="media")
        return
    logger.warning(
        "MEDIA_ROOT is not set; image upload API (/v2/admin/media/images) will return 503. "
        "Set MEDIA_ROOT to an absolute directory to enable media uploads."
    )


def _warn_social_observe_security(app: FastAPI) -> None:
    settings = app.state.settings
    pub_base = (settings.public_site_base_url or "").strip().lower()
    if pub_base.startswith("https://") and not (settings.social_observe_shared_token or "").strip():
        logger.warning(
            "SOCIAL_OBSERVE_SHARED_TOKEN is empty while PUBLIC_SITE_BASE_URL is HTTPS; "
            "/v2/social/observe is unauthenticated. Set SOCIAL_OBSERVE_SHARED_TOKEN (and frontend VITE_SOCIAL_OBSERVE_TOKEN)."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    await init_db(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    ws_debug_tap = WsDebugTap(max_events=800)
    app.state.ws_debug_tap = ws_debug_tap
    app.state.registry = AgentConnectionRegistry(debug_tap=ws_debug_tap)
    mail.init_mail_app(app, settings)
    _warn_social_observe_security(app)
    _configure_media_mount(app)
    app.state.social_registry = await _configure_social_registry(app)
    ttl_task = asyncio.create_task(
        run_social_ttl_enforcer(
            app.state.social_registry,
            app.state.session_factory,
            app.state.registry,
            app.state.settings,
        )
    )
    yield
    ttl_task.cancel()
    try:
        await ttl_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
