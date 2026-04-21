import asyncio
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket

from app.config import load_settings
from app.db import create_engine, create_session_factory, init_db
from app.routers import admin_agents, faq_public, mail, news_admin, news_public, permissions_admin
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

    if settings.social_state_dir:
        state_dir = Path(settings.social_state_dir)
    else:
        state_dir = Path(tempfile.gettempdir())
        logger.warning(
            "SOCIAL_STATE_DIR is not set; social room CSV state will be written to %s. "
            "Set SOCIAL_STATE_DIR to a stable, auditable path in production.",
            state_dir,
        )
    social = SocialRoomRegistry(state_dir)
    social.initialize()
    await social.ensure_checkin_room()
    app.state.social_registry = social

    ttl_task = asyncio.create_task(run_social_ttl_enforcer(social, session_factory))

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
app.include_router(permissions_admin.router)
app.include_router(faq_public.router)
app.include_router(mail.router)
app.include_router(news_public.router)
app.include_router(share_router)
app.include_router(social_router)


@app.websocket("/v2/agent/ws")
async def agent_ws(websocket: WebSocket) -> None:
    await handle_agent_websocket(websocket)


@app.websocket("/v2/social/ws")
async def social_agent_ws(websocket: WebSocket) -> None:
    await handle_social_agent_websocket(websocket)


@app.websocket("/v2/social/observe")
async def social_observe_ws(websocket: WebSocket) -> None:
    await handle_social_observe_websocket(websocket)
