import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.crypto_tokens import constant_time_token_equals, sha256_hex


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def db_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def admin_key_guard(
    settings: SettingsDep,
    x_admin_key: Annotated[str, Header(alias="X-Admin-Key")],
) -> None:
    if not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key",
        )


async def agent_auth(
    session: DbSession,
    x_agent_id: Annotated[str, Header(alias="X-Agent-Id")],
    x_agent_token: Annotated[str, Header(alias="X-Agent-Token")],
) -> "Agent":
    """Shared FastAPI dependency for agent HTTP endpoints (X-Agent-Id / X-Agent-Token)."""
    from app.models import Agent  # local import to avoid circular

    agent = await session.scalar(select(Agent).where(Agent.agent_id == x_agent_id.strip()))
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown agent.")
    if agent.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent has been revoked.")
    if not constant_time_token_equals(sha256_hex(x_agent_token.strip()), agent.token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    return agent


AgentDep = Annotated["Agent", Depends(agent_auth)]
