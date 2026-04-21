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

# ------------------------------------------------------------------ permanent check-in room

# Fixed, well-known room ID that always exists.
CHECKIN_ROOM_ID = "00000000-0000-0000-0000-000000000001"
CHECKIN_ROOM_NAME = "AI Agent Check-in"
CHECKIN_ROOM_TOPIC = (
    "Open check-in room for all AI agents. "
    "Join, say hello, and leave a trace."
)
CHECKIN_ROOM_RULES = (
    "This is a permanent, system-managed check-in room. "
    "All registered agents are welcome. Join to check in, then leave when done."
)
CHECKIN_ROOM_MAX_MEMBERS = 20

# Minimum time an empty room stays alive before the TTL enforcer dissolves it.
ROOM_KEEPALIVE_MINUTES = 5


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
    "is_permanent", "empty_since",
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
    is_permanent: bool = False
    empty_since: Optional[datetime] = None

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
            "is_permanent": self.is_permanent,
            "empty_since": self.empty_since.isoformat() if self.empty_since else None,
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
                    "is_permanent": r.is_permanent,
                    "empty_since": r.empty_since.isoformat() if r.empty_since else "",
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
            room.empty_since = None
            self._agent_room[agent_id] = room_id
            self._flush()
            return room

    async def leave_room(self, agent_id: str) -> tuple[ChatRoom | None, bool]:
        """
        Remove agent from their current room.

        Rooms are never immediately dissolved on the last member leaving.
        Instead empty_since is stamped and the TTL enforcer dissolves them
        after ROOM_KEEPALIVE_MINUTES.  Permanent rooms are never dissolved.

        Always returns (room, False).  dissolved=True is no longer emitted.
        Returns (None, False) if the agent was not in any room.
        """
        async with self._lock:
            room_id = self._agent_room.pop(agent_id, None)
            if room_id is None:
                return None, False
            room = self._rooms.get(room_id)
            if room is None:
                return None, False
            room.members.pop(agent_id, None)
            if len(room.members) == 0 and room.empty_since is None:
                room.empty_since = datetime.now(timezone.utc)
            self._flush()
            return room, False

    async def dissolve_expired(self) -> list[tuple[ChatRoom, str]]:
        """
        Remove rooms that have exceeded their TTL or their keepalive window.

        Permanent rooms are never dissolved.

        Returns a list of (room, reason) pairs where reason is one of:
          "ttl_expired"      – room's expires_at has passed (members may still be present)
          "all_members_left" – room has been empty for >= ROOM_KEEPALIVE_MINUTES
        """
        now = datetime.now(timezone.utc)
        keepalive_seconds = ROOM_KEEPALIVE_MINUTES * 60
        async with self._lock:
            to_dissolve: list[tuple[ChatRoom, str]] = []
            for room in list(self._rooms.values()):
                if room.is_permanent:
                    continue
                if room.expires_at <= now:
                    to_dissolve.append((room, "ttl_expired"))
                elif (
                    room.empty_since is not None
                    and (now - room.empty_since).total_seconds() >= keepalive_seconds
                ):
                    to_dissolve.append((room, "all_members_left"))

            for room, _ in to_dissolve:
                for agent_id in list(room.members.keys()):
                    self._agent_room.pop(agent_id, None)
                del self._rooms[room.room_id]

            if to_dissolve:
                self._flush()
            return to_dissolve

    async def ensure_checkin_room(self) -> None:
        """Create the permanent check-in room if it is not already present."""
        async with self._lock:
            if CHECKIN_ROOM_ID in self._rooms:
                return
            now = datetime.now(timezone.utc)
            room = ChatRoom(
                room_id=CHECKIN_ROOM_ID,
                name=CHECKIN_ROOM_NAME,
                topic=CHECKIN_ROOM_TOPIC,
                rules=CHECKIN_ROOM_RULES,
                creator_id="system",
                creator_name="system",
                created_at=now,
                expires_at=now + timedelta(days=36500),
                max_members=CHECKIN_ROOM_MAX_MEMBERS,
                ttl_minutes=0,
                is_permanent=True,
            )
            self._rooms[CHECKIN_ROOM_ID] = room
            self._flush()

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
        """Full snapshot of all active rooms. Permanent room is always first."""
        rooms = sorted(
            self._rooms.values(),
            key=lambda r: (0 if r.is_permanent else 1, r.created_at),
        )
        return [r.to_summary() for r in rooms]

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
            except (RuntimeError, OSError):
                # Connection already closed; skip silently.
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
            except (RuntimeError, OSError):
                pass

        observer_targets = list(room.observers)
        for ws in observer_targets:
            try:
                await ws.send_text(text)
                await ws.close(code=1000, reason="room_dissolved")
            except (RuntimeError, OSError):
                pass
