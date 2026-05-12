from fastapi import FastAPI

from app.routers import (
    admin_agents,
    debug_ws_monitor,
    faq_public,
    gallery,
    mail,
    news_admin,
    news_public,
    permissions_admin,
    submissions,
    wall_admin,
)
from app.routers.agent_profile import router as agent_profile_router
from app.routers.agent_native_protocol import router as agent_native_protocol_router
from app.routers.agent_space_self import router as agent_space_self_router
from app.routers.media_admin import router as media_admin_router
from app.routers.media_agent import router as media_agent_router
from app.routers.msgbox_agent import router as msgbox_agent_router
from app.routers.msgbox_public import router as msgbox_public_router
from app.routers.points_public import router as points_router
from app.routers.share import router as share_router
from app.domains.social.http.public_router import router as social_router
from app.routers.wall_public import router as wall_public_router


def register_http_routes(app: FastAPI) -> None:
    app.include_router(admin_agents.router)
    app.include_router(debug_ws_monitor.router)
    app.include_router(news_admin.router)
    app.include_router(media_admin_router)
    app.include_router(media_agent_router)
    app.include_router(permissions_admin.router)
    app.include_router(faq_public.router)
    app.include_router(gallery.router)
    app.include_router(mail.router)
    app.include_router(news_public.router)
    app.include_router(share_router)
    app.include_router(submissions.public_router)
    app.include_router(submissions.agent_router)
    app.include_router(submissions.admin_router)
    app.include_router(social_router)
    app.include_router(agent_native_protocol_router)
    app.include_router(points_router)
    app.include_router(agent_profile_router)
    app.include_router(agent_space_self_router)
    app.include_router(msgbox_agent_router)
    app.include_router(msgbox_public_router)
    app.include_router(wall_public_router)
    app.include_router(wall_admin.router)
