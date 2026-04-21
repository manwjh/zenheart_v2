"""
SocialRoomRegistry – ephemeral room state backed by CSV snapshots.

Two CSV files live under SOCIAL_STATE_DIR (defaults to OS tempdir):
  social_rooms.csv    – one row per active room
  social_members.csv  – one row per active membership

Both files are wiped on startup and rewritten on every mutation.
WebSocket handles live only in memory; the CSVs are a live file-level
snapshot for external monitoring or debugging without an API call.
"""
from __future__ import annotations

import asyncio
import csv
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from starlette.websockets import WebSocket

# ------------------------------------------------------------------ level limits

_LEVEL_LIMITS: list[tuple[int, int, int]] = [
    # (max_level_inclusive, max_members, max_ttl_minutes)
    (2, 10, 30),
    (5,  5, 20),
    (9,  3, 10),
]
_ROOM_CAPACITY_DEFAULT = 3
_ROOM_TTL_DEFAULT = 30


def get_room_limits(level: int) -> tuple[int, int]:
    """Return (max_members_cap, max_ttl_minutes_cap) for a given agent level.

    Lower level number = higher trust (level 0 = admin).
    """
    for threshold, max_members, max_ttl in _LEVEL_LIMITS:
        if level <= threshold:
            return max_members, max_ttl
    return _LEVEL_LIMITS[-1][1], _LEVEL_LIMITS[-1][2]


# ------------------------------------------------------------------ mention parsing

_MENTION_RE = re.compile(r"@([A-Za-z0-9_\-]+)")


def parse_mentions(text: str, name_to_id: dict[str, str]) -> list[str]:
    """Extract @name references from text and resolve to agent_ids.

    Returns a deduplicated list in order of first appearance.
    """
    seen: dict[str, None] = {}
    for m in _MENTION_RE.finditer(text):
        name = m.group(1).lower()
        agent_id = name_to_id.get(name)
        if agent_id and agent_id not in seen:
            seen[agent_id] = None
    return list(seen)


# ------------------------------------------------------------------ data classes

_ROOMS_HEADER = [
    "room_id", "name", "topic", "creator_id", "creator_name",
    "created_at", "expires_at", "max_members", "ttl_minutes",
]
_MEMBERS_HEADER = ["room_id", "agent_id", "agent_name", "joined_at"]


@dataclass
class RoomMember:
    agent_id: str
    agent_name: str
    joined_at: datetime
    ws: Optional[WebSocket] = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "joined_at": self.joined_at.isoformat(),
        }


@dataclass
class ChatRoom:
    room_id: str
    name: str
    topic: str
    creator_id: str
    creator_name: str
    created_at: datetime
    expires_at: datetime
    max_members: int
    ttl_minutes: int
    rules: str = ""
    members: dict[str, RoomMember] = field(default_factory=dict)
    observers: set[WebSocket] = field(default_factory=set)
    message_count: int = 0

    def to_summary(self) -> dict[str, Any]:
        """Full room snapshot used in list_rooms responses."""
        return {
            "room_id": self.room_id,
            "status": "active",
            "name": self.name,
            "topic": self.topic,
            "rules": self.rules,
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "member_count": len(self.members),
            "max_members": self.max_members,
            "ttl_minutes": self.ttl_minutes,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "members": self.member_list(),
        }

    def member_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.members.values()]

    def name_to_id_map(self) -> dict[str, str]:
        """Returns {lowercase_agent_name: agent_id} for @mention resolution."""
        return {m.agent_name.lower(): m.agent_id for m in self.members.values()}


# ------------------------------------------------------------------ registry

class SocialRoomRegistry:
    def __init__(self, state_dir: Path) -> None:
        self._lock = asyncio.Lock()
        self._rooms: dict[str, ChatRoom] = {}
        self._agent_room: dict[str, str] = {}  # agent_id → room_id
        self._state_dir = state_dir
        self._rooms_file = state_dir / "social_rooms.csv"
        self._members_file = state_dir / "social_members.csv"

    def initialize(self) -> None:
        """Wipe stale CSV state. Call once at server startup."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._write_rooms_csv()
        self._write_members_csv()

    # ------------------------------------------------------------------ CSV I/O

    def _write_rooms_csv(self) -> None:
        with self._rooms_file.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_ROOMS_HEADER)
            w.writeheader()
            for r in self._rooms.values():
                w.writerow({
                    "room_id": r.room_id,
                    "name": r.name,
                    "topic": r.topic,
                    "creator_id": r.creator_id,
                    "creator_name": r.creator_name,
                    "created_at": r.created_at.isoformat(),
                    "expires_at": r.expires_at.isoformat(),
                    "max_members": r.max_members,
                    "ttl_minutes": r.ttl_minutes,
                })

    def _write_members_csv(self) -> None:
        with self._members_file.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_MEMBERS_HEADER)
            w.writeheader()
            for r in self._rooms.values():
                for m in r.members.values():
                    w.writerow({
                        "room_id": r.room_id,
                        "agent_id": m.agent_id,
                        "agent_name": m.agent_name,
                        "joined_at": m.joined_at.isoformat(),
                    })

    def _flush(self) -> None:
        """Rewrite both CSVs. Must be called while _lock is held."""
        self._write_rooms_csv()
        self._write_members_csv()

    # ------------------------------------------------------------------ actions

    async def create_room(
        self,
        name: str,
        topic: str,
        max_members: int,
        ttl_minutes: int,
        creator_id: str,
        creator_name: str,
        ws: WebSocket,
        rules: str = "",
    ) -> ChatRoom | str:
        """Return ChatRoom on success, or an error-reason string."""
        async with self._lock:
            if creator_id in self._agent_room:
                return "already_in_room"
            room_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=ttl_minutes)
            member = RoomMember(
                agent_id=creator_id,
                agent_name=creator_name,
                joined_at=now,
                ws=ws,
            )
            room = ChatRoom(
                room_id=room_id,
                name=name,
                topic=topic,
                rules=rules,
                creator_id=creator_id,
                creator_name=creator_name,
                created_at=now,
                expires_at=expires_at,
                max_members=max_members,
                ttl_minutes=ttl_minutes,
                members={creator_id: member},
            )
            self._rooms[room_id] = room
            self._agent_room[creator_id] = room_id
            self._flush()
            return room

    async def join_room(
        self,
        room_id: str,
        agent_id: str,
        agent_name: str,
        ws: WebSocket,
    ) -> ChatRoom | str:
        """Return ChatRoom on success, or an error-reason string."""
        async with self._lock:
            if agent_id in self._agent_room:
                return "already_in_room"
            room = self._rooms.get(room_id)
            if room is None:
                return "room_not_found"
            if len(room.members) >= room.max_members:
                return "room_full"
            member = RoomMember(
                agent_id=agent_id,
                agent_name=agent_name,
                joined_at=datetime.now(timezone.utc),
                ws=ws,
            )
            room.members[agent_id] = member
            self._agent_room[agent_id] = room_id
            self._flush()
            return room

    async def leave_room(self, agent_id: str) -> tuple[ChatRoom | None, bool]:
        """
        Remove agent from their current room.
        Returns (room, dissolved) where dissolved=True means the room was removed.
        Returns (None, False) if agent was not in any room.
        """
        async with self._lock:
            room_id = self._agent_room.pop(agent_id, None)
            if room_id is None:
                return None, False
            room = self._rooms.get(room_id)
            if room is None:
                return None, False
            room.members.pop(agent_id, None)
            dissolved = len(room.members) == 0
            if dissolved:
                del self._rooms[room_id]
            self._flush()
            return room, dissolved

    async def dissolve_expired(self) -> list[ChatRoom]:
        """Remove all rooms past their expires_at. Returns dissolved rooms."""
        now = datetime.now(timezone.utc)
        async with self._lock:
            expired = [r for r in self._rooms.values() if r.expires_at <= now]
            for room in expired:
                for agent_id in list(room.members.keys()):
                    self._agent_room.pop(agent_id, None)
                del self._rooms[room.room_id]
            if expired:
                self._flush()
            return expired

    async def current_room_id(self, agent_id: str) -> str | None:
        async with self._lock:
            return self._agent_room.get(agent_id)

    async def get_room(self, room_id: str) -> ChatRoom | None:
        async with self._lock:
            return self._rooms.get(room_id)

    async def get_name_to_id_map(self, agent_id: str) -> dict[str, str]:
        """Return {lowercase_name: agent_id} for agents in the same room as agent_id."""
        async with self._lock:
            room_id = self._agent_room.get(agent_id)
            if room_id is None:
                return {}
            room = self._rooms.get(room_id)
            if room is None:
                return {}
            return room.name_to_id_map()

    def list_rooms_snapshot(self) -> list[dict[str, Any]]:
        """Full snapshot of all active rooms including member lists."""
        return [r.to_summary() for r in self._rooms.values()]

    # ---------------------------------------------------------------- observer management

    async def add_observer(self, room_id: str, ws: WebSocket) -> ChatRoom | None:
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            room.observers.add(ws)
            return room

    async def remove_observer(self, room_id: str, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(room_id)
            if room:
                room.observers.discard(ws)

    async def remove_observer_from_all(self, ws: WebSocket) -> None:
        async with self._lock:
            for room in self._rooms.values():
                room.observers.discard(ws)

    # ---------------------------------------------------------------- message helpers

    async def record_message(self, agent_id: str) -> str | None:
        """Increment message counter for agent's room. Returns room_id or None."""
        async with self._lock:
            room_id = self._agent_room.get(agent_id)
            if room_id:
                room = self._rooms.get(room_id)
                if room:
                    room.message_count += 1
            return room_id

    # ---------------------------------------------------------------- broadcast helpers

    async def broadcast_to_room(
        self,
        room_id: str,
        frame: dict[str, Any],
        exclude_agent: str | None = None,
    ) -> None:
        """Deliver frame to all members and observers in a room."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return
            member_targets = [
                m.ws for m in room.members.values()
                if m.ws is not None and m.agent_id != exclude_agent
            ]
            observer_targets = list(room.observers)

        text = json.dumps(frame)
        for ws in member_targets + observer_targets:
            try:
                await ws.send_text(text)
            except Exception:
                pass

    async def broadcast_dissolution(
        self,
        room: ChatRoom,
        reason: str,
    ) -> None:
        """Notify all members and close all observer connections for a dissolved room."""
        frame = {
            "type": "room_dissolved",
            "room_id": room.room_id,
            "name": room.name,
            "reason": reason,
        }
        text = json.dumps(frame)

        member_targets = [m.ws for m in room.members.values() if m.ws is not None]
        for ws in member_targets:
            try:
                await ws.send_text(text)
            except Exception:
                pass

        observer_targets = list(room.observers)
        for ws in observer_targets:
            try:
                await ws.send_text(text)
                await ws.close(code=1000, reason="room_dissolved")
            except Exception:
                pass

    async def close_all_observers(
        self, room_id: str, frame: dict[str, Any], code: int = 1000
    ) -> None:
        """Send a final frame to every observer of a room and close their connections."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return
            targets = list(room.observers)
            room.observers.clear()

        text = json.dumps(frame)
        for ws in targets:
            try:
                await ws.send_text(text)
                await ws.close(code=code, reason="room_dissolved")
            except Exception:
                pass
