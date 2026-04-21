from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select

from app.deps import DbSession, admin_key_guard
from app.models import LevelPermission
from app.schemas import (
    LevelPermissionListResponse,
    LevelPermissionRow,
    LevelPermissionUpsertRequest,
)

router = APIRouter(
    prefix="/v2/admin/permissions",
    tags=["admin-permissions"],
    dependencies=[Depends(admin_key_guard)],
)


@router.get("", response_model=LevelPermissionListResponse)
async def list_permissions(session: DbSession) -> LevelPermissionListResponse:
    result = await session.scalars(
        select(LevelPermission).order_by(LevelPermission.module, LevelPermission.action)
    )
    rows = result.all()
    return LevelPermissionListResponse(
        items=[
            LevelPermissionRow(
                module=row.module,
                action=row.action,
                max_level=row.max_level,
                limit_value=row.limit_value,
                description=row.description,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
    )


@router.put("/{module}/{action}", response_model=LevelPermissionRow)
async def upsert_permission(
    module: str, action: str, body: LevelPermissionUpsertRequest, session: DbSession
) -> LevelPermissionRow:
    """Create or update the max_level for a (module, action) pair."""
    row = await session.scalar(
        select(LevelPermission).where(
            LevelPermission.module == module,
            LevelPermission.action == action,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = LevelPermission(
            module=module,
            action=action,
            max_level=body.max_level,
            limit_value=body.limit_value,
            description=body.description,
            updated_at=now,
        )
        session.add(row)
    else:
        row.max_level = body.max_level
        row.limit_value = body.limit_value
        row.description = body.description
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return LevelPermissionRow(
        module=row.module,
        action=row.action,
        max_level=row.max_level,
        limit_value=row.limit_value,
        description=row.description,
        updated_at=row.updated_at,
    )


@router.delete("/{module}/{action}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(module: str, action: str, session: DbSession) -> None:
    """Remove a permission rule; the action becomes deny-by-default."""
    result = await session.execute(
        delete(LevelPermission).where(
            LevelPermission.module == module,
            LevelPermission.action == action,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission rule not found.",
        )
    await session.commit()
