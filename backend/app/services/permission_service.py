from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model_defs import LevelPermission


async def check_permission(
    session: AsyncSession,
    module: str,
    action: str,
    agent_level: int,
) -> bool:
    """
    Return True if an agent at `agent_level` is allowed to perform `action` on `module`.

    Rule: agent_level <= max_level → allowed.
    No matching row in level_permissions → denied by default.
    """
    row = await session.scalar(
        select(LevelPermission).where(
            LevelPermission.module == module,
            LevelPermission.action == action,
        )
    )
    if row is None:
        return False
    return agent_level <= row.max_level


async def get_limit_value(
    session: AsyncSession,
    module: str,
    action: str,
) -> Optional[int]:
    """
    Return the limit_value stored in level_permissions for the given (module, action).
    Returns None if no row exists or if limit_value is null.
    """
    row = await session.scalar(
        select(LevelPermission).where(
            LevelPermission.module == module,
            LevelPermission.action == action,
        )
    )
    if row is None:
        return None
    return row.limit_value
