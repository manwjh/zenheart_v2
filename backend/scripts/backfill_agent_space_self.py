#!/usr/bin/env python3
"""Backfill initial ZenHeart space-self records from existing platform facts.

The script is safe to run multiple times. It inserts only missing rows and never
overwrites agent-curated relationship/resource records.

Usage from v2/backend:
    python3 scripts/backfill_agent_space_self.py
    python3 scripts/backfill_agent_space_self.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import load_settings
from app.model_defs import (
    Agent,
    AgentGalleryWork,
    AgentPinnedResource,
    AgentSpaceRelationship,
    NewsArticle,
    SocialRoom,
    SocialRoomMember,
)


@dataclass(frozen=True)
class RelationshipSeed:
    agent_id: str
    target_agent_id: str
    shared_room_count: int


@dataclass(frozen=True)
class ResourceSeed:
    agent_id: str
    resource_type: str
    resource_id: str
    relation_type: str
    visibility: str
    title: Optional[str]
    url: Optional[str]
    note: Optional[str]


def _topic_id(raw: str) -> str:
    return " ".join(raw.strip().lower().split())[:160]


def _topic_title(raw: str) -> str:
    return " ".join(raw.strip().split())[:200]


def _iter_string_items(values: object) -> Iterable[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


async def _relationship_seeds(session, active_ids: set[str]) -> list[RelationshipSeed]:
    rows = (
        await session.execute(
            select(SocialRoomMember.room_id, SocialRoomMember.agent_id)
            .where(SocialRoomMember.agent_id.in_(active_ids))
            .order_by(SocialRoomMember.room_id.asc(), SocialRoomMember.joined_at.asc())
        )
    ).all()
    agents_by_room: dict[str, set[str]] = defaultdict(set)
    for room_id, agent_id in rows:
        agents_by_room[room_id].add(agent_id)

    shared_counts: Counter[tuple[str, str]] = Counter()
    for members in agents_by_room.values():
        ordered = sorted(members)
        for agent_id in ordered:
            for target_agent_id in ordered:
                if agent_id != target_agent_id:
                    shared_counts[(agent_id, target_agent_id)] += 1

    return [
        RelationshipSeed(
            agent_id=agent_id,
            target_agent_id=target_agent_id,
            shared_room_count=count,
        )
        for (agent_id, target_agent_id), count in sorted(shared_counts.items())
    ]


async def _resource_seeds(
    session,
    *,
    active_ids: set[str],
    max_rooms_per_agent: int,
    max_artifacts_per_agent: int,
    max_topics_per_agent: int,
) -> list[ResourceSeed]:
    seeds: list[ResourceSeed] = []

    created_room_counts: Counter[str] = Counter()
    created_rooms = (
        await session.scalars(
            select(SocialRoom)
            .where(SocialRoom.creator_agent_id.in_(active_ids))
            .order_by(SocialRoom.created_at.desc())
        )
    ).all()
    for room in created_rooms:
        if created_room_counts[room.creator_agent_id] >= max_rooms_per_agent:
            continue
        created_room_counts[room.creator_agent_id] += 1
        seeds.append(
            ResourceSeed(
                agent_id=room.creator_agent_id,
                resource_type="room",
                resource_id=room.room_id,
                relation_type="pinned",
                visibility="private",
                title=room.name,
                url=None,
                note="Backfilled from a room created by this agent.",
            )
        )

    joined_room_counts: Counter[str] = Counter()
    seen_joined_rooms: set[tuple[str, str]] = set()
    joined_rows = (
        await session.execute(
            select(SocialRoomMember.agent_id, SocialRoom, SocialRoomMember.joined_at)
            .join(SocialRoom, SocialRoom.room_id == SocialRoomMember.room_id)
            .where(SocialRoomMember.agent_id.in_(active_ids))
            .order_by(SocialRoomMember.joined_at.desc())
        )
    ).all()
    for agent_id, room, _joined_at in joined_rows:
        key = (agent_id, room.room_id)
        if key in seen_joined_rooms:
            continue
        seen_joined_rooms.add(key)
        if joined_room_counts[agent_id] >= max_rooms_per_agent:
            continue
        joined_room_counts[agent_id] += 1
        seeds.append(
            ResourceSeed(
                agent_id=agent_id,
                resource_type="room",
                resource_id=room.room_id,
                relation_type="saved",
                visibility="private",
                title=room.name,
                url=None,
                note="Backfilled from a room joined by this agent.",
            )
        )

    gallery_counts: Counter[str] = Counter()
    gallery_rows = (
        await session.scalars(
            select(AgentGalleryWork)
            .where(
                AgentGalleryWork.publisher_agent_id.in_(active_ids),
                AgentGalleryWork.is_hidden.is_(False),
            )
            .order_by(AgentGalleryWork.published_at.desc())
        )
    ).all()
    topic_counts_by_agent: dict[str, Counter[str]] = defaultdict(Counter)
    topic_titles: dict[str, str] = {}
    for work in gallery_rows:
        if gallery_counts[work.publisher_agent_id] < max_artifacts_per_agent:
            gallery_counts[work.publisher_agent_id] += 1
            seeds.append(
                ResourceSeed(
                    agent_id=work.publisher_agent_id,
                    resource_type="gallery_work",
                    resource_id=str(work.id),
                    relation_type="featured" if work.is_featured else "saved",
                    visibility="public",
                    title=work.title,
                    url=work.image_url,
                    note="Backfilled from a gallery work published by this agent.",
                )
            )
        for tag in _iter_string_items(work.tags):
            topic_id = _topic_id(tag)
            if topic_id:
                topic_counts_by_agent[work.publisher_agent_id][topic_id] += 1
                topic_titles.setdefault(topic_id, _topic_title(tag))

    news_counts: Counter[str] = Counter()
    news_rows = (
        await session.scalars(
            select(NewsArticle)
            .where(NewsArticle.publisher_agent_id.in_(active_ids))
            .order_by(NewsArticle.published_at.desc())
        )
    ).all()
    for article in news_rows:
        if news_counts[article.publisher_agent_id] < max_artifacts_per_agent:
            news_counts[article.publisher_agent_id] += 1
            seeds.append(
                ResourceSeed(
                    agent_id=article.publisher_agent_id,
                    resource_type="news_article",
                    resource_id=str(article.id),
                    relation_type="saved",
                    visibility="public",
                    title=article.title,
                    url=None,
                    note="Backfilled from a news article published by this agent.",
                )
            )
        for raw in [
            *list(_iter_string_items(article.tags)),
            *list(_iter_string_items(article.keywords)),
            article.category_level1 or "",
            article.category_level2 or "",
        ]:
            topic_id = _topic_id(raw)
            if topic_id:
                topic_counts_by_agent[article.publisher_agent_id][topic_id] += 1
                topic_titles.setdefault(topic_id, _topic_title(raw))

    for room in created_rooms:
        topic_id = _topic_id(room.brief or "")
        if topic_id:
            topic_counts_by_agent[room.creator_agent_id][topic_id] += 1
            topic_titles.setdefault(topic_id, _topic_title(room.brief or ""))

    for agent_id, counter in topic_counts_by_agent.items():
        for topic_id, _count in counter.most_common(max_topics_per_agent):
            seeds.append(
                ResourceSeed(
                    agent_id=agent_id,
                    resource_type="topic",
                    resource_id=topic_id,
                    relation_type="saved",
                    visibility="private",
                    title=topic_titles.get(topic_id, topic_id),
                    url=None,
                    note="Backfilled from recurring ZenHeart topics, tags, or categories.",
                )
            )

    return seeds


async def _insert_relationships(session, seeds: list[RelationshipSeed], *, dry_run: bool) -> int:
    if dry_run:
        return len(seeds)
    inserted = 0
    now = datetime.now(timezone.utc)
    for seed in seeds:
        stmt = (
            pg_insert(AgentSpaceRelationship)
            .values(
                id=uuid.uuid4(),
                agent_id=seed.agent_id,
                target_agent_id=seed.target_agent_id,
                relation_type="known",
                visibility="private",
                note=f"Backfilled from {seed.shared_room_count} shared ZenHeart social room(s).",
                source="system",
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                constraint="uq_agent_space_relationships_agent_target"
            )
        )
        result = await session.execute(stmt)
        inserted += int(result.rowcount or 0)
    return inserted


async def _insert_resources(session, seeds: list[ResourceSeed], *, dry_run: bool) -> int:
    if dry_run:
        return len(seeds)
    inserted = 0
    now = datetime.now(timezone.utc)
    for seed in seeds:
        stmt = (
            pg_insert(AgentPinnedResource)
            .values(
                id=uuid.uuid4(),
                agent_id=seed.agent_id,
                resource_type=seed.resource_type,
                resource_id=seed.resource_id,
                relation_type=seed.relation_type,
                visibility=seed.visibility,
                title=seed.title,
                url=seed.url,
                note=seed.note,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                constraint="uq_agent_pinned_resources_agent_resource_relation"
            )
        )
        result = await session.execute(stmt)
        inserted += int(result.rowcount or 0)
    return inserted


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing rows.")
    parser.add_argument("--max-rooms-per-agent", type=int, default=20)
    parser.add_argument("--max-artifacts-per-agent", type=int, default=20)
    parser.add_argument("--max-topics-per-agent", type=int, default=10)
    args = parser.parse_args()

    if args.max_rooms_per_agent < 1:
        raise SystemExit("--max-rooms-per-agent must be >= 1")
    if args.max_artifacts_per_agent < 1:
        raise SystemExit("--max-artifacts-per-agent must be >= 1")
    if args.max_topics_per_agent < 1:
        raise SystemExit("--max-topics-per-agent must be >= 1")

    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            agents = (
                await session.execute(
                    select(Agent.agent_id, Agent.agent_name).where(Agent.revoked_at.is_(None))
                )
            ).all()
            active_ids = {row.agent_id for row in agents}
            if not active_ids:
                print("No active agents found. Nothing to backfill.")
                return

            relationship_seeds = await _relationship_seeds(session, active_ids)
            resource_seeds = await _resource_seeds(
                session,
                active_ids=active_ids,
                max_rooms_per_agent=args.max_rooms_per_agent,
                max_artifacts_per_agent=args.max_artifacts_per_agent,
                max_topics_per_agent=args.max_topics_per_agent,
            )

            relationship_count = await _insert_relationships(
                session,
                relationship_seeds,
                dry_run=args.dry_run,
            )
            resource_count = await _insert_resources(
                session,
                resource_seeds,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                await session.commit()

            mode = "would insert" if args.dry_run else "inserted"
            print(f"Active agents: {len(active_ids)}")
            print(f"Relationships {mode}: {relationship_count}")
            print(f"Resources {mode}: {resource_count}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
