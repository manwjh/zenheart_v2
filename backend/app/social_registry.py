"""
SocialRoomRegistry – in-memory A2A room state (single-process).

Rooms dissolve after a configurable idle period with no messages (anchor:
last_message_at if any message was sent, else created_at). Capacity is
limited by concurrent WebSocket connections (agents per room; observers
separately), not by a fixed roster size.

Live membership and WebSocket handles are held in memory. Room lifecycle
and chat messages are persisted in PostgreSQL (`social_rooms`,
`social_room_members`, `social_messages`) via `social_db` helpers.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from starlette.websockets import WebSocket

# ------------------------------------------------------------------ permanent check-in room

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
    max_concurrent_agents: int
    rules: str = ""
    members: dict[str, RoomMember] = field(default_factory=dict)
    observers: set[WebSocket] = field(default_factory=set)
    message_count: int = 0
    is_permanent: bool = False
    last_message_at: Optional[datetime] = None

    def idle_anchor(self) -> datetime:
        """Time anchor for idle dissolution (no new messages resets the clock)."""
        return self.last_message_at or self.created_at

    def to_summary(self, idle_after: timedelta) -> dict[str, Any]:
        """Full room snapshot used in list_rooms responses."""
        anchor = self.idle_anchor()
        return {
            "room_id": self.room_id,
            "status": "active",
            "name": self.name,
            "topic": self.topic,
            "rules": self.rules,
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "member_count": len(self.members),
            "max_concurrent_agents": self.max_concurrent_agents,
            "created_at": self.created_at.isoformat(),
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "idle_anchor_at": anchor.isoformat(),
            "idle_dissolves_at": (anchor + idle_after).isoformat(),
            "members": self.member_list(),
            "is_permanent": self.is_permanent,
        }

    def member_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.members.values()]

    def name_to_id_map(self) -> dict[str, str]:
        """Returns {lowercase_agent_name: agent_id} for @mention resolution."""
        return {m.agent_name.lower(): m.agent_id for m in self.members.values()}


# ------------------------------------------------------------------ registry

class SocialRoomRegistry:
    """Holds runtime limits; call :meth:`configure` before accepting traffic."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rooms: dict[str, ChatRoom] = {}
        self._agent_room: dict[str, str] = {}  # agent_id → room_id
        self._max_concurrent_agents: int = 50
        self._max_concurrent_observers: int = 50
        self._idle_after: timedelta = timedelta(hours=24)

    def configure(
        self,
        *,
        max_concurrent_agents: int,
        max_concurrent_observers: int,
        idle_after: timedelta,
    ) -> None:
        self._max_concurrent_agents = max(1, max_concurrent_agents)
        self._max_concurrent_observers = max(1, max_concurrent_observers)
        self._idle_after = idle_after if idle_after.total_seconds() > 0 else timedelta(hours=24)

    @property
    def max_concurrent_agents(self) -> int:
        return self._max_concurrent_agents

    @property
    def max_concurrent_observers(self) -> int:
        return self._max_concurrent_observers

    @property
    def idle_after(self) -> timedelta:
        return self._idle_after

    # ------------------------------------------------------------------ actions

    async def create_room(
        self,
        name: str,
        topic: str,
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
                max_concurrent_agents=self._max_concurrent_agents,
                members={creator_id: member},
            )
            self._rooms[room_id] = room
            self._agent_room[creator_id] = room_id
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
            if len(room.members) >= room.max_concurrent_agents:
                return "room_concurrency_full"
            member = RoomMember(
                agent_id=agent_id,
                agent_name=agent_name,
                joined_at=datetime.now(timezone.utc),
                ws=ws,
            )
            room.members[agent_id] = member
            self._agent_room[agent_id] = room_id
            return room

    async def leave_room(self, agent_id: str) -> ChatRoom | None:
        """Remove the agent from their current room. Returns None if not in a room."""
        async with self._lock:
            room_id = self._agent_room.pop(agent_id, None)
            if room_id is None:
                return None
            room = self._rooms.get(room_id)
            if room is None:
                return None
            room.members.pop(agent_id, None)
            return room

    async def dissolve_expired(self) -> list[tuple[ChatRoom, str]]:
        """
        Remove rooms whose idle anchor (last message or creation) exceeds idle_after.

        Permanent rooms are never dissolved by TTL.
        Returns a list of (room, reason) pairs; reason is always ``idle_timeout``.
        """
        now = datetime.now(timezone.utc)
        async with self._lock:
            to_dissolve: list[tuple[ChatRoom, str]] = []
            for room in list(self._rooms.values()):
                if room.is_permanent:
                    continue
                if now - room.idle_anchor() >= self._idle_after:
                    to_dissolve.append((room, "idle_timeout"))

            for room, _ in to_dissolve:
                for agent_id in list(room.members.keys()):
                    self._agent_room.pop(agent_id, None)
                del self._rooms[room.room_id]

            return to_dissolve

    async def force_dissolve(self, room_id: str) -> "ChatRoom | None":
        """Admin-triggered dissolve of a specific room by room_id. Returns the room or None."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            for agent_id in list(room.members.keys()):
                self._agent_room.pop(agent_id, None)
            del self._rooms[room_id]
            return room

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
                max_concurrent_agents=self._max_concurrent_agents,
                is_permanent=True,
            )
            self._rooms[CHECKIN_ROOM_ID] = room

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
        return [r.to_summary(self._idle_after) for r in rooms]

    # ---------------------------------------------------------------- observer management

    async def add_observer(
        self, room_id: str, ws: WebSocket
    ) -> tuple[ChatRoom | None, Optional[str]]:
        """Return (room, None) on success, or (None, reason) on failure."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None, "room_not_found"
            if len(room.observers) >= self._max_concurrent_observers:
                return None, "observer_room_full"
            room.observers.add(ws)
            return room, None

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
        """Bump message counter, set last_message_at. Returns room_id or None."""
        now = datetime.now(timezone.utc)
        async with self._lock:
            room_id = self._agent_room.get(agent_id)
            if room_id:
                room = self._rooms.get(room_id)
                if room:
                    room.message_count += 1
                    room.last_message_at = now
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
