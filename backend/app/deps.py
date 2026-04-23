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


async def admin_or_sovereign_guard(
    session: DbSession,
    settings: SettingsDep,
    x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None,
    x_agent_id: Annotated[str | None, Header(alias="X-Agent-Id")] = None,
    x_agent_token: Annotated[str | None, Header(alias="X-Agent-Token")] = None,
) -> None:
    """Allow either a valid X-Admin-Key or a level-0 agent (X-Agent-Id / X-Agent-Token).

    If X-Admin-Key is non-empty, it must match; agent headers are not considered as fallback.
    """
    from app.models import Agent  # local import to avoid circular

    admin_raw = (x_admin_key or "").strip()
    if admin_raw:
        if not secrets.compare_digest(admin_raw, settings.admin_api_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin key",
            )
        return

    aid = (x_agent_id or "").strip()
    tok = (x_agent_token or "").strip()
    if not aid or not tok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key or missing sovereign agent credentials.",
        )
    agent = await session.scalar(select(Agent).where(Agent.agent_id == aid))
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown agent.",
        )
    if agent.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent has been revoked.",
        )
    if not constant_time_token_equals(sha256_hex(tok), agent.token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )
    if agent.level != 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sovereign agent (level 0) required for this operation.",
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
