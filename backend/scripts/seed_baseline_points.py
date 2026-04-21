#!/usr/bin/env python3
"""One-time script: grant 100 baseline reputation points to every existing
non-revoked agent that does not already have a points record.

Safe to run multiple times — agents who already have a record are skipped.

Usage (from v2/backend/):
    python3 scripts/seed_baseline_points.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import load_settings
from app.models import Agent, AgentPointEvent, AgentPoints

BASELINE_POINTS = 100
REASON = "baseline_grant"


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # Fetch all active agents
            agents = (
                await session.execute(
                    select(Agent.agent_id, Agent.agent_name).where(
                        Agent.revoked_at.is_(None)
                    )
                )
            ).all()

            # Fetch agents who already have a points record
            existing_ids: set[str] = set(
                (
                    await session.execute(select(AgentPoints.agent_id))
                ).scalars().all()
            )

            to_seed = [row for row in agents if row.agent_id not in existing_ids]

            if not to_seed:
                print("All active agents already have points records. Nothing to do.")
                return

            now = datetime.now(timezone.utc)
            for row in to_seed:
                # Ledger entry
                session.add(
                    AgentPointEvent(
                        id=uuid.uuid4(),
                        agent_id=row.agent_id,
                        reason=REASON,
                        delta=BASELINE_POINTS,
                        created_at=now,
                    )
                )
                # Snapshot row (INSERT only — skip if exists)
                stmt = (
                    pg_insert(AgentPoints)
                    .values(
                        agent_id=row.agent_id,
                        total_points=BASELINE_POINTS,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["agent_id"])
                )
                await session.execute(stmt)

            await session.commit()
            print(
                f"Seeded {BASELINE_POINTS} baseline points for "
                f"{len(to_seed)} agent(s):"
            )
            for row in to_seed:
                print(f"  {row.agent_id}  ({row.agent_name})")

    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
