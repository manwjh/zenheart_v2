"""
SocialRoomRegistry – in-memory A2A room state (single-process).

Rooms dissolve after a configurable idle period with no messages (anchor:
last_message_at if any message was sent, else created_at). Capacity is
limited by concurrent WebSocket connections (agents per room; observers
separately), not by a fixed roster size.

Live membership and WebSocket handles are held in memory. Room lifecycle
and chat messages are persisted in PostgreSQL (`social_rooms`,
`social_room_members`, `social_messages`) via `social_db` helpers.
On process start, non-dissolved rows in `social_rooms` are merged into the
registry so empty rooms and `room_id` remain joinable after restarts.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from starlette.websockets import WebSocket

from app.config import SOCIAL_ROOM_IDLE_HOURS_DEFAULT
from app.models import SocialRoom

# ------------------------------------------------------------------ permanent check-in room

CHECKIN_ROOM_ID = "00000000-0000-0000-0000-000000000001"
CHECKIN_ROOM_NAME = "AI Agent Check-in"


def _active_room_name_key(name: str) -> str:
    """Normalize display name for uniqueness: trim + Unicode case-folding."""
    return name.strip().casefold()
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


# Max agent_ids accepted on send_message when using explicit `mention_agent_ids` (see ws_social_inbound).
MAX_MENTION_AGENT_IDS_PER_MESSAGE = 50

# Private room allowlist: creator is always included; cap size for abuse prevention.
MAX_PRIVATE_ROOM_ALLOWLIST = 200


def filter_mention_agent_ids_for_room(
    room: "ChatRoom", raw: list[str]
) -> list[str]:
    """Keep only current room members, preserve order, deduplicate (first wins).

    `raw` is expected to be pre-validated as a list of non-empty str.
    """
    member_ids = set(room.members.keys())
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        if x in member_ids and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def normalize_private_allowlist(creator_id: str, raw: list[Any] | None) -> set[str] | str:
    """Build allowlist; always includes ``creator_id``. Returns error string on invalid input."""
    if raw is None:
        return {creator_id}
    if not isinstance(raw, list):
        return "invalid_allowlist"
    out: set[str] = set()
    for x in raw:
        if not isinstance(x, str) or not x.strip():
            return "invalid_allowlist"
        out.add(x.strip())
    if len(out) > MAX_PRIVATE_ROOM_ALLOWLIST:
        return "allowlist_too_large"
    out.add(creator_id)
    return out


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
    # Invite-only: only creator + allowlist may join. Implies no idle auto-dissolve.
    is_private: bool = False
    # When false, observers and unauthenticated HTTP cannot read room content; card still listable.
    observable: bool = True
    allowlist_agent_ids: set[str] = field(default_factory=set)

    def idle_anchor(self) -> datetime:
        """Time anchor for idle dissolution (no new messages resets the clock)."""
        return self.last_message_at or self.created_at

    def to_summary(
        self, idle_after: timedelta, *, for_public_lobby: bool = False
    ) -> dict[str, Any]:
        """Room snapshot. When ``for_public_lobby`` is true, redact in-room detail for private / hidden rooms."""
        anchor = self.idle_anchor()
        if self.is_private or self.is_permanent:
            idle_dissolves_at: str | None = None
        else:
            idle_dissolves_at = (anchor + idle_after).isoformat()
        redact = for_public_lobby and (self.is_private or not self.observable)
        members = [] if redact else self.member_list()
        if for_public_lobby and (self.is_private or not self.observable):
            rules_out = ""
        else:
            rules_out = self.rules
        return {
            "room_id": self.room_id,
            "status": "active",
            "name": self.name,
            "topic": self.topic,
            "rules": rules_out,
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "member_count": len(self.members),
            "max_concurrent_agents": self.max_concurrent_agents,
            "created_at": self.created_at.isoformat(),
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "idle_anchor_at": anchor.isoformat(),
            "idle_dissolves_at": idle_dissolves_at,
            "members": members,
            "is_permanent": self.is_permanent,
            "is_private": self.is_private,
            "observable": self.observable,
        }

    def member_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.members.values()]

    def name_to_id_map(self) -> dict[str, str]:
        """Returns {lowercase_agent_name: agent_id} for @mention resolution."""
        return {m.agent_name.lower(): m.agent_id for m in self.members.values()}


def _chat_room_from_social_row(row: SocialRoom, *, creator_name: str) -> ChatRoom:
    """Build an in-memory room with no live members (used after DB rehydrate)."""
    allow: set[str] = set()
    if row.is_private:
        if row.allowlist_agent_ids:
            allow.update(str(x) for x in row.allowlist_agent_ids)
        allow.add(row.creator_agent_id)
    return ChatRoom(
        room_id=row.room_id,
        name=row.name,
        topic=row.topic or "",
        rules=row.rules or "",
        creator_id=row.creator_agent_id,
        creator_name=creator_name,
        created_at=row.created_at,
        max_concurrent_agents=row.max_members,
        members={},
        observers=set(),
        message_count=int(row.total_messages),
        is_permanent=(row.room_id == CHECKIN_ROOM_ID),
        last_message_at=row.last_message_at,
        is_private=row.is_private,
        observable=row.observable,
        allowlist_agent_ids=allow,
    )


def chat_room_from_social_row(row: SocialRoom, *, creator_name: str) -> ChatRoom:
    """Build in-memory room with no live members (startup merge / admin resurrect)."""
    return _chat_room_from_social_row(row, creator_name=creator_name)


# ------------------------------------------------------------------ registry

class SocialRoomRegistry:
    """Holds runtime limits; call :meth:`configure` before accepting traffic."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rooms: dict[str, ChatRoom] = {}
        self._agent_room: dict[str, str] = {}  # agent_id → room_id
        self._max_concurrent_agents: int = 50
        self._max_concurrent_observers: int = 50
        self._idle_after: timedelta = timedelta(hours=SOCIAL_ROOM_IDLE_HOURS_DEFAULT)

    def configure(
        self,
        *,
        max_concurrent_agents: int,
        max_concurrent_observers: int,
        idle_after: timedelta,
    ) -> None:
        self._max_concurrent_agents = max(1, max_concurrent_agents)
        self._max_concurrent_observers = max(1, max_concurrent_observers)
        self._idle_after = (
            idle_after
            if idle_after.total_seconds() > 0
            else timedelta(hours=SOCIAL_ROOM_IDLE_HOURS_DEFAULT)
        )

    @property
    def max_concurrent_agents(self) -> int:
        return self._max_concurrent_agents

    @property
    def max_concurrent_observers(self) -> int:
        return self._max_concurrent_observers

    @property
    def idle_after(self) -> timedelta:
        return self._idle_after

    async def apply_agent_display_name(self, agent_id: str, new_name: str) -> None:
        """Update creator and member display names in all in-memory rooms (after DB profile rename)."""
        async with self._lock:
            for room in self._rooms.values():
                if room.creator_id == agent_id:
                    room.creator_name = new_name
                m = room.members.get(agent_id)
                if m is not None:
                    m.agent_name = new_name

    # ------------------------------------------------------------------ actions

    async def create_room(
        self,
        name: str,
        topic: str,
        creator_id: str,
        creator_name: str,
        ws: WebSocket,
        rules: str = "",
        *,
        is_private: bool = False,
        observable: bool = True,
        allowlist_raw: list[Any] | None = None,
    ) -> ChatRoom | str:
        """Return ChatRoom on success, or an error-reason string."""
        allow: set[str] | str = {creator_id}
        if is_private:
            al = normalize_private_allowlist(creator_id, allowlist_raw)
            if isinstance(al, str):
                return al
            allow = al
        async with self._lock:
            if creator_id in self._agent_room:
                return "already_in_room"
            want = _active_room_name_key(name)
            for existing in self._rooms.values():
                if _active_room_name_key(existing.name) == want:
                    return "room_name_taken"
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
                is_private=is_private,
                observable=bool(observable),
                allowlist_agent_ids=set(allow) if is_private else set(),
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
            if room.is_private and agent_id not in room.allowlist_agent_ids:
                return "not_invited"
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
        Remove **occupied** public rooms whose idle anchor exceeds ``idle_after``.

        Permanent and private rooms are skipped. **Empty rooms (no members) are never
        removed by this task** so ``room_id`` and lobby entries stay until admin
        dissolve or explicit DB dissolution.
        Returns a list of (room, reason) pairs; reason is always ``idle_timeout``.
        """
        now = datetime.now(timezone.utc)
        async with self._lock:
            to_dissolve: list[tuple[ChatRoom, str]] = []
            for room in list(self._rooms.values()):
                if room.is_permanent or room.is_private:
                    continue
                if not room.members:
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

    async def merge_persisted_active_rooms(
        self, rows: Sequence[SocialRoom], *, name_by_id: dict[str, str] | None = None
    ) -> int:
        """Load non-dissolved ``social_rooms`` rows into memory (e.g. after restart).

        ``name_by_id`` maps ``creator_agent_id`` -> display name (from ``agents`` when available).
        Skips ``room_id`` already present (including the check-in room).
        """
        nmap = name_by_id or {}
        snapshots: list[ChatRoom] = []
        for r in rows:
            if r.creator_agent_id == "system":
                cn = "system"
            else:
                cn = nmap.get(r.creator_agent_id) or (
                    (r.creator_agent_id[:8] + "…") if len(r.creator_agent_id) > 8 else r.creator_agent_id
                )
            snapshots.append(chat_room_from_social_row(r, creator_name=cn))
        async with self._lock:
            n = 0
            for room in snapshots:
                if room.room_id in self._rooms:
                    continue
                self._rooms[room.room_id] = room
                n += 1
            return n

    async def register_resurrected_room(self, room: ChatRoom) -> bool:
        """Insert a room reloaded from DB after L0 ``admin_resurrect_social_room``.

        Returns ``False`` if ``room_id`` is already in the registry (e.g. race).
        """
        async with self._lock:
            if room.room_id in self._rooms:
                return False
            self._rooms[room.room_id] = room
            return True

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

    async def get_current_room_members_snapshot(self, agent_id: str) -> dict[str, Any] | None:
        """Return current room + live member list for an agent, or None when not in room."""
        async with self._lock:
            room_id = self._agent_room.get(agent_id)
            if room_id is None:
                return None
            room = self._rooms.get(room_id)
            if room is None:
                return None
            return {
                "room_id": room.room_id,
                "name": room.name,
                "members": room.member_list(),
            }

    def list_rooms_snapshot(self) -> list[dict[str, Any]]:
        """Full snapshot of all active rooms. Permanent room is always first."""
        rooms = sorted(
            self._rooms.values(),
            key=lambda r: (0 if r.is_permanent else 1, r.created_at),
        )
        return [r.to_summary(self._idle_after, for_public_lobby=True) for r in rooms]

    async def apply_private_allowlist_after_persist(
        self, room_id: str, creator_id: str, allow: set[str],
    ) -> str | None:
        """Set in-memory allowlist after DB success (``allow`` is already normalized)."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return "room_not_found"
            if room.creator_id != creator_id:
                return "forbidden"
            if not room.is_private:
                return "not_private_room"
            room.allowlist_agent_ids = set(allow)
        return None

    # ---------------------------------------------------------------- observer management

    async def add_observer(
        self, room_id: str, ws: WebSocket
    ) -> tuple[ChatRoom | None, Optional[str]]:
        """Return (room, None) on success, or (None, reason) on failure."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None, "room_not_found"
            if not room.observable:
                return None, "not_observable"
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
