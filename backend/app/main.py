import asyncio
import logging
from datetime import timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from app.config import load_settings
from app.db import create_engine, create_session_factory, init_db
from app.routers import admin_agents, faq_public, mail, news_admin, news_public, permissions_admin
from app.routers.media_admin import router as media_admin_router
from app.routers.media_agent import router as media_agent_router
from app.routers.points_public import router as points_router
from app.routers.share import router as share_router
from app.routers.social_public import router as social_router
from app.social_registry import SocialRoomRegistry
from app.social_ttl import run_social_ttl_enforcer
from app.ws_agent import handle_agent_websocket
from app.ws_registry import AgentConnectionRegistry
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
    mail.init_mail_app(app, settings)

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
    await social.ensure_checkin_room()
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


@app.websocket("/v2/agent/ws")
async def agent_ws(websocket: WebSocket) -> None:
    await handle_agent_websocket(websocket)


@app.websocket("/v2/social/ws")
async def social_agent_ws(websocket: WebSocket) -> None:
    await handle_social_agent_websocket(websocket)


@app.websocket("/v2/social/observe")
async def social_observe_ws(websocket: WebSocket) -> None:
    await handle_social_observe_websocket(websocket)
