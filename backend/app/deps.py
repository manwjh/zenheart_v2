from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.crypto_tokens import constant_time_token_equals, sha256_hex
from app.model_defs import Agent


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
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    x_admin_key: Annotated[Optional[str], Header(alias="X-Admin-Key")] = None,
    x_agent_id: Annotated[Optional[str], Header(alias="X-Agent-Id")] = None,
    x_agent_token: Annotated[Optional[str], Header(alias="X-Agent-Token")] = None,
) -> None:
    """Allow either a valid X-Admin-Key or a level-0 agent (X-Agent-Id / X-Agent-Token).

    If X-Admin-Key is non-empty, it must match; agent headers are not considered as fallback.
    Successful requests emit ``admin_http_mutation`` (POST/PUT/PATCH/DELETE) or
    ``admin_http_read`` (GET) on ``agent_event_logs``.
    """
    admin_raw = (x_admin_key or "").strip()
    if admin_raw:
        if not secrets.compare_digest(admin_raw, settings.admin_api_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin key",
            )
        await _log_admin_http_audit(request, operator="admin_key", agent_id=None)
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
    await _log_admin_http_audit(
        request, operator="sovereign_agent", agent_id=agent.agent_id
    )


async def agent_auth(
    session: DbSession,
    x_agent_id: Annotated[str, Header(alias="X-Agent-Id")],
    x_agent_token: Annotated[str, Header(alias="X-Agent-Token")],
) -> Agent:
    """Shared FastAPI dependency for agent HTTP endpoints (X-Agent-Id / X-Agent-Token)."""
    agent = await session.scalar(select(Agent).where(Agent.agent_id == x_agent_id.strip()))
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown agent.")
    if agent.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent has been revoked.")
    if not constant_time_token_equals(sha256_hex(x_agent_token.strip()), agent.token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    return agent


AgentDep = Annotated[Agent, Depends(agent_auth)]


async def optional_agent_auth(
    session: DbSession,
    x_agent_id: Annotated[Optional[str], Header(alias="X-Agent-Id")] = None,
    x_agent_token: Annotated[Optional[str], Header(alias="X-Agent-Token")] = None,
) -> Optional[Agent]:
    """If both agent headers are absent, return None. If both are set, validate like ``agent_auth``."""
    aid = (x_agent_id or "").strip()
    tok = (x_agent_token or "").strip()
    if not aid and not tok:
        return None
    if not aid or not tok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Both X-Agent-Id and X-Agent-Token are required for agent posting.",
        )
    agent = await session.scalar(select(Agent).where(Agent.agent_id == aid))
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown agent.")
    if agent.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent has been revoked.")
    if not constant_time_token_equals(sha256_hex(tok), agent.token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    return agent


async def _log_admin_http_audit(
    request: Request,
    *,
    operator: str,
    agent_id: Optional[str],
) -> None:
    method = request.method.upper()
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        event = "admin_http_mutation"
    elif method == "GET":
        event = "admin_http_read"
    else:
        return

    from app.services.agent_event_log import record_agent_event

    await record_agent_event(
        request.app.state.session_factory,
        event=event,
        agent_id=agent_id,
        detail={
            "method": request.method,
            "path": request.url.path,
            "operator": operator,
        },
    )
