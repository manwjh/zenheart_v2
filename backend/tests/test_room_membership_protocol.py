import asyncio
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.domains.social.persistence import social_repository
from app.domains.social.http import public_router
from app.model_defs import Agent, SocialRoom
from app.services import ws_admin_ops, ws_send_direct_message, ws_social_inbound
from app.social_registry import CHECKIN_ROOM_ID, SocialRoomRegistry, chat_room_from_social_row


class _FakeSession:
    def __init__(self, scalars=None):
        self._scalars = list(scalars or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def scalar(self, _stmt):
        return self._scalars.pop(0) if self._scalars else None

    async def commit(self):
        return None


class _FakeSessionFactory:
    def __init__(self, scalars=None):
        self._scalars = list(scalars or [])

    def __call__(self):
        return _FakeSession(self._scalars)


class _FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


class _FakeRegistry:
    async def get_connection_id(self, _agent_id):
        return None


def _agent(agent_id: str, name: str = "Agent", level: int = 1) -> Agent:
    return Agent(
        agent_id=agent_id,
        email=f"{agent_id}@example.invalid",
        level=level,
        token_hash="hash",
        agent_name=name,
    )


def test_live_membership_is_distinct_from_history_after_leave() -> None:
    async def run():
        registry = SocialRoomRegistry()
        ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=ws,
        )
        assert not isinstance(room, str)
        assert await registry.is_live_member("agent-a", room.room_id) is True

        left_room = await registry.leave_room("agent-a")
        assert left_room is room
        assert await registry.is_live_member("agent-a", room.room_id) is False

    asyncio.run(run())


def test_room_history_requires_current_live_member(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=_FakeWebSocket(),
        )
        assert not isinstance(room, str)
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    social_registry=registry,
                    session_factory=_FakeSessionFactory(),
                ),
            ),
        )
        messages_called = False

        async def fake_get_room_messages(*_args, **_kwargs):
            nonlocal messages_called
            messages_called = True
            return [{"id": "m1", "room_id": room.room_id, "text": "hello"}]

        monkeypatch.setattr(public_router, "get_room_messages", fake_get_room_messages)

        member_resp = await public_router.get_room_message_history(
            room.room_id,
            request,
            _agent("agent-a"),
        )
        assert member_resp.status_code == 200
        assert messages_called is True

        await registry.leave_room("agent-a")
        non_member_resp = await public_router.get_room_message_history(
            room.room_id,
            request,
            _agent("agent-a"),
        )
        assert non_member_resp.status_code == 403
        error_body = json.loads(non_member_resp.body)
        assert error_body["detail"]["reason"] == "not_in_room"
        assert error_body["detail"]["room_id"] == room.room_id

    asyncio.run(run())


def test_join_room_same_live_room_is_idempotent(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=ws,
        )
        assert not isinstance(room, str)

        events = []
        member_join_records = []

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_count_rooms_today(*_args, **_kwargs):
            return 0

        async def fake_record_member_join(*args, **kwargs):
            member_join_records.append((args, kwargs))
            return True

        async def fake_record_event(_session_factory, event, agent_id=None, detail=None, **_kwargs):
            events.append({"event": event, "agent_id": agent_id, "detail": detail or {}})

        async def fake_get_room_messages(*_args, **_kwargs):
            return []

        async def fake_pending_topics(*_args, **_kwargs):
            return []

        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "count_rooms_today", fake_count_rooms_today)
        monkeypatch.setattr(ws_social_inbound, "record_member_join", fake_record_member_join)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)
        monkeypatch.setattr(ws_social_inbound, "get_room_messages", fake_get_room_messages)
        monkeypatch.setattr(ws_social_inbound, "list_pending_topic_suggestions", fake_pending_topics)

        await ws_social_inbound._handle_join_room(
            ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(),
            "agent-a",
            "Agent A",
            1,
            {"room_id": room.room_id},
        )

        assert ws.sent[-2]["type"] == "room_joined"
        assert ws.sent[-2]["room_id"] == room.room_id
        assert ws.sent[-2]["already_in_room"] is True
        assert ws.sent[-2]["room_online"] is True
        assert member_join_records == []
        assert any(event["event"] == "a2a_room_join_idempotent" for event in events)

    asyncio.run(run())


def test_join_room_sends_pending_topics_only_to_creator(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)

        pending_topics_called = False

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_count_rooms_today(*_args, **_kwargs):
            return 0

        async def fake_record_member_join(*_args, **_kwargs):
            return True

        async def fake_record_event(*_args, **_kwargs):
            return None

        async def fake_get_room_messages(*_args, **_kwargs):
            return []

        async def fake_pending_topics(*_args, **_kwargs):
            nonlocal pending_topics_called
            pending_topics_called = True
            return [{"id": "topic-1", "text": "Owner only", "created_at": "2026-05-09T00:00:00+00:00"}]

        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "count_rooms_today", fake_count_rooms_today)
        monkeypatch.setattr(ws_social_inbound, "record_member_join", fake_record_member_join)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)
        monkeypatch.setattr(ws_social_inbound, "get_room_messages", fake_get_room_messages)
        monkeypatch.setattr(ws_social_inbound, "list_pending_topic_suggestions", fake_pending_topics)

        await ws_social_inbound._handle_join_room(
            peer_ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(),
            "agent-b",
            "Agent B",
            1,
            {"room_id": room.room_id},
        )

        assert pending_topics_called is False
        assert [frame["type"] for frame in peer_ws.sent] == ["room_joined"]

    asyncio.run(run())


def test_pending_topic_updates_notify_observers_and_live_creator(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        observer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(room.room_id, "agent-b", "Agent B", peer_ws)
        assert not isinstance(joined, str)
        observed, reason = await registry.add_observer(room.room_id, observer_ws)
        assert observed is room
        assert reason is None

        async def fake_pending_topics(*_args, **_kwargs):
            return [{"id": "topic-1", "text": "Owner only", "created_at": "2026-05-09T00:00:00+00:00"}]

        monkeypatch.setattr(
            social_repository, "list_pending_topic_suggestions", fake_pending_topics
        )

        await registry.notify_topic_suggestions_pending(_FakeSessionFactory(), room.room_id)

        assert [frame["type"] for frame in creator_ws.sent] == ["topic_suggestions_pending"]
        assert creator_ws.sent[0]["topics"][0]["text"] == "Owner only"
        assert peer_ws.sent == []
        assert [frame["type"] for frame in observer_ws.sent] == ["topic_suggestions_pending"]
        assert observer_ws.sent[0]["topics"][0]["text"] == "Owner only"

    asyncio.run(run())


def test_message_notify_recipients_include_absent_room_creator_once() -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)

        assert ws_social_inbound._message_notify_recipient_ids(room, "agent-b") == ["agent-a"]

        await registry.leave_room("agent-a")
        assert ws_social_inbound._message_notify_recipient_ids(room, "agent-b") == ["agent-a"]

    asyncio.run(run())


def test_creator_can_update_room_metadata(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="old room",
            brief="old brief",
            rules="old rules",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)

        events = []

        async def fake_update_room_metadata(*_args, **_kwargs):
            return True

        async def fake_record_event(_session_factory, event, agent_id=None, detail=None, **_kwargs):
            events.append({"event": event, "agent_id": agent_id, "detail": detail or {}})

        monkeypatch.setattr(ws_social_inbound, "db_update_room_metadata", fake_update_room_metadata)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)

        await ws_social_inbound._handle_update_room_metadata(
            creator_ws,
            registry,
            _FakeSessionFactory(),
            "agent-a",
            {
                "room_id": room.room_id,
                "name": "new room",
                "brief": "new brief",
                "rules": "",
            },
        )

        assert creator_ws.sent[-1]["type"] == "room_metadata_updated"
        assert creator_ws.sent[-1]["name"] == "new room"
        assert creator_ws.sent[-1]["brief"] == "new brief"
        assert creator_ws.sent[-1]["rules"] == ""
        assert peer_ws.sent[-1]["type"] == "room_metadata_updated"
        assert peer_ws.sent[-1]["name"] == "new room"
        updated = await registry.get_room(room.room_id)
        assert updated is not None
        assert updated.name == "new room"
        assert updated.brief == "new brief"
        assert updated.rules == ""
        assert any(event["event"] == "a2a_room_metadata_updated" for event in events)

    asyncio.run(run())


def test_room_door_close_kicks_peers_and_blocks_join(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        joiner_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)

        leave_records = []

        async def fake_update_room_door(*_args, **_kwargs):
            return True

        async def fake_record_member_leave(_session_factory, room_id, agent_id, left_at=None):
            leave_records.append((room_id, agent_id, left_at))

        async def fake_record_event(*_args, **_kwargs):
            return None

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_count_rooms_today(*_args, **_kwargs):
            return 0

        monkeypatch.setattr(ws_social_inbound, "db_update_room_door_state", fake_update_room_door)
        monkeypatch.setattr(ws_social_inbound, "record_member_leave", fake_record_member_leave)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)
        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "count_rooms_today", fake_count_rooms_today)

        await ws_social_inbound._handle_update_room_door(
            creator_ws,
            registry,
            _FakeSessionFactory(),
            "agent-a",
            {"room_id": room.room_id, "door_state": "closed"},
        )

        assert creator_ws.sent[-1]["type"] == "room_door_updated"
        assert creator_ws.sent[-1]["door_state"] == "closed"
        assert creator_ws.sent[-1]["kicked_agent_ids"] == ["agent-b"]
        assert peer_ws.sent[-1]["type"] == "room_door_closed"
        assert await registry.is_live_member("agent-b", room.room_id) is False
        assert leave_records[0][0:2] == (room.room_id, "agent-b")

        await ws_social_inbound._handle_join_room(
            joiner_ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(),
            "agent-c",
            "Agent C",
            1,
            {"room_id": room.room_id},
        )

        assert joiner_ws.sent[-1]["type"] == "error"
        assert joiner_ws.sent[-1]["reason"] == "room_door_closed"
        assert joiner_ws.sent[-1]["door_state"] == "closed"

    asyncio.run(run())


def test_room_owner_can_join_closed_room(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        owner_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=owner_ws,
        )
        assert not isinstance(room, str)
        await registry.leave_room("agent-a")
        room.door_closed = True

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_count_rooms_today(*_args, **_kwargs):
            return 0

        async def fake_record_member_join(*_args, **_kwargs):
            return True

        async def fake_record_event(*_args, **_kwargs):
            return None

        async def fake_get_room_messages(*_args, **_kwargs):
            return []

        async def fake_pending_topics(*_args, **_kwargs):
            return []

        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "count_rooms_today", fake_count_rooms_today)
        monkeypatch.setattr(ws_social_inbound, "record_member_join", fake_record_member_join)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)
        monkeypatch.setattr(ws_social_inbound, "get_room_messages", fake_get_room_messages)
        monkeypatch.setattr(ws_social_inbound, "list_pending_topic_suggestions", fake_pending_topics)

        await ws_social_inbound._handle_join_room(
            owner_ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(),
            "agent-a",
            "Agent A",
            1,
            {"room_id": room.room_id},
        )

        assert owner_ws.sent[-2]["type"] == "room_joined"
        assert owner_ws.sent[-2]["door_state"] == "closed"
        assert await registry.is_live_member("agent-a", room.room_id) is True

    asyncio.run(run())


def test_checkin_room_loaded_from_db_is_standard() -> None:
    created_at = datetime.now(timezone.utc)
    row = SocialRoom(
        room_id=CHECKIN_ROOM_ID,
        name="AI Agent Check-in",
        brief="brief",
        creator_agent_id="agent-a",
        created_at=created_at,
        max_members=10,
        ttl_minutes=60,
        expires_at=None,
        total_messages=0,
        is_private=False,
        observable=True,
        door_closed=False,
    )

    room = chat_room_from_social_row(row, creator_name="Agent A", agent_cap=10)
    summary = room.to_summary(SocialRoomRegistry().idle_after)

    assert room.is_permanent is False
    assert summary["is_permanent"] is False
    assert summary["idle_dissolves_at"] is not None


def test_room_owner_transfer_updates_closed_room_membership() -> None:
    async def run():
        registry = SocialRoomRegistry()
        owner_ws = _FakeWebSocket()
        successor_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=owner_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=successor_ws,
        )
        assert not isinstance(joined, str)
        room.door_closed = True

        updated, kicked, error = await registry.apply_room_owner_after_persist(
            room.room_id,
            new_creator_id="agent-b",
            new_creator_name="Agent B",
        )

        assert error is None
        assert updated is room
        assert room.creator_id == "agent-b"
        assert [member.agent_id for member in kicked] == ["agent-a"]
        assert await registry.is_live_member("agent-a", room.room_id) is False
        assert await registry.is_live_member("agent-b", room.room_id) is True

    asyncio.run(run())


def test_l0_can_transfer_social_room_owner(monkeypatch) -> None:
    async def run():
        social = SocialRoomRegistry()
        room = await social.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=_FakeWebSocket(),
        )
        assert not isinstance(room, str)
        successor = _agent("agent-b", "Agent B", level=1)
        row = SocialRoom(
            room_id=room.room_id,
            name="room",
            brief="brief",
            creator_agent_id="agent-a",
            created_at=room.created_at,
            max_members=10,
            is_private=False,
            observable=True,
            door_closed=False,
        )
        events = []

        async def fake_record_event(_session_factory, event, agent_id=None, detail=None, **_kwargs):
            events.append({"event": event, "agent_id": agent_id, "detail": detail or {}})

        monkeypatch.setattr(ws_admin_ops, "record_agent_event", fake_record_event)

        out = await ws_admin_ops.handle_admin_transfer_social_room_owner(
            session_factory=_FakeSessionFactory([successor, row]),
            social=social,
            sovereign_agent_id="agent-l0",
            agent_level=0,
            connection_id="conn-1",
            data={
                "room_id": room.room_id,
                "new_owner_agent_id": "agent-b",
                "note": "handoff",
            },
        )

        assert out["type"] == "admin_transfer_social_room_owner_ok"
        assert out["old_owner_agent_id"] == "agent-a"
        assert out["new_owner_agent_id"] == "agent-b"
        assert room.creator_id == "agent-b"
        assert row.creator_agent_id == "agent-b"
        assert events[0]["event"] == "admin_transfer_social_room_owner_via_ws"

    asyncio.run(run())


def test_room_door_open_does_not_reset_in_memory_history(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)
        await registry.record_message("agent-a")
        room.door_closed = True
        assert room.message_count == 1
        assert room.last_message_at is not None

        calls = []

        async def fake_update_room_door(_session_factory, room_id, *, door_closed):
            calls.append((room_id, door_closed))
            return True

        async def fake_record_event(*_args, **_kwargs):
            return None

        monkeypatch.setattr(ws_social_inbound, "db_update_room_door_state", fake_update_room_door)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)

        await ws_social_inbound._handle_update_room_door(
            creator_ws,
            registry,
            _FakeSessionFactory(),
            "agent-a",
            {"room_id": room.room_id, "door_state": "open"},
        )

        assert calls == [(room.room_id, False)]
        assert creator_ws.sent[-1]["type"] == "room_door_updated"
        assert creator_ws.sent[-1]["door_state"] == "open"
        assert "cleared_history" not in creator_ws.sent[-1]
        assert room.door_closed is False
        assert room.message_count == 1
        assert room.last_message_at is not None

    asyncio.run(run())


def test_room_creator_can_clear_room_state(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)
        await registry.record_message("agent-a")
        assert room.message_count == 1
        assert room.last_message_at is not None

        calls = []
        events = []
        pending_notifications = []

        async def fake_clear_room_state(_session_factory, room_id, *, clear_messages, clear_signals):
            calls.append((room_id, clear_messages, clear_signals))
            return True

        async def fake_record_event(_session_factory, event, agent_id=None, detail=None, **_kwargs):
            events.append({"event": event, "agent_id": agent_id, "detail": detail or {}})

        async def fake_notify_topics(_session_factory, room_id):
            pending_notifications.append(room_id)

        monkeypatch.setattr(ws_social_inbound, "db_clear_room_state", fake_clear_room_state)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)
        monkeypatch.setattr(registry, "notify_topic_suggestions_pending", fake_notify_topics)

        await ws_social_inbound._handle_clear_room_state(
            creator_ws,
            registry,
            _FakeSessionFactory(),
            "agent-a",
            {
                "room_id": room.room_id,
                "clear_messages": True,
                "clear_signals": True,
            },
        )

        assert calls == [(room.room_id, True, True)]
        assert creator_ws.sent[-1]["type"] == "room_state_cleared"
        assert creator_ws.sent[-1]["cleared_messages"] is True
        assert creator_ws.sent[-1]["cleared_signals"] is True
        assert peer_ws.sent[-1]["type"] == "room_state_cleared"
        assert room.message_count == 0
        assert room.last_message_at is None
        assert pending_notifications == [room.room_id]
        assert any(event["event"] == "a2a_room_state_cleared" for event in events)

    asyncio.run(run())


def test_room_creator_receives_message_notify_after_leaving_room(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        creator_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=creator_ws,
        )
        assert not isinstance(room, str)
        await registry.leave_room("agent-a")
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)

        notify_calls = []
        recorded_messages = []

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_noop(*_args, **_kwargs):
            return None

        async def fake_record_social_message(*_args, **kwargs):
            recorded_messages.append(kwargs)
            return True

        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "record_social_message", fake_record_social_message)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_noop)
        monkeypatch.setattr(ws_social_inbound, "award_points", fake_noop)
        monkeypatch.setattr(
            ws_social_inbound,
            "schedule_social_notify",
            lambda **kwargs: notify_calls.append(kwargs),
        )

        await ws_social_inbound._handle_send_message(
            peer_ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(social_require_explicit_mentions=False),
            "agent-b",
            "Agent B",
            1,
            {"text": "hello owner"},
        )

        assert peer_ws.sent[-1]["type"] == "message"
        mid = peer_ws.sent[-1]["id"]
        uuid.UUID(mid)
        assert str(recorded_messages[0]["message_id"]) == mid
        assert notify_calls[0]["recipient_agent_ids"] == ["agent-a"]
        assert notify_calls[0]["ws_body"]["id"] == mid
        assert notify_calls[0]["webhook_payload"]["id"] == mid

    asyncio.run(run())


def test_out_of_room_mentions_are_dropped_not_msgbox_enqueued(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        sender_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=sender_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)

        events = []
        msgbox_calls = []
        notify_calls = []
        recorded_messages = []

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_find_unknown(_session_factory, agent_ids):
            return []

        async def fake_record_event(_session_factory, event, agent_id=None, detail=None, **_kwargs):
            events.append({"event": event, "agent_id": agent_id, "detail": detail or {}})

        async def fake_noop(*_args, **_kwargs):
            return None

        async def fake_record_social_message(*_args, **kwargs):
            recorded_messages.append(kwargs)
            return True

        async def fake_push_message(*args, **kwargs):
            msgbox_calls.append((args, kwargs))
            return "msgbox-id"

        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "_find_unknown_agent_ids", fake_find_unknown)
        monkeypatch.setattr(ws_social_inbound, "record_social_message", fake_record_social_message)
        monkeypatch.setattr(ws_social_inbound, "record_agent_event", fake_record_event)
        monkeypatch.setattr(ws_social_inbound, "award_points", fake_noop)
        monkeypatch.setattr(
            ws_social_inbound,
            "schedule_social_notify",
            lambda **kwargs: notify_calls.append(kwargs),
        )
        monkeypatch.setattr(ws_send_direct_message, "push_message", fake_push_message)

        await ws_social_inbound._handle_send_message(
            sender_ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(social_require_explicit_mentions=False),
            "agent-a",
            "Agent A",
            1,
            {
                "text": "hello",
                "mention_agent_ids": ["agent-b", "agent-c"],
                "reply_to_message_id": "00000000-0000-4000-8000-000000000001",
                "expected_last_message_id": "00000000-0000-4000-8000-000000000001",
            },
        )

        echo = sender_ws.sent[-1]
        assert echo["type"] == "message"
        uuid.UUID(echo["id"])
        assert str(recorded_messages[0]["message_id"]) == echo["id"]
        assert str(recorded_messages[0]["reply_to_message_id"]) == "00000000-0000-4000-8000-000000000001"
        assert str(recorded_messages[0]["expected_last_message_id"]) == "00000000-0000-4000-8000-000000000001"
        assert echo["reply_to_message_id"] == "00000000-0000-4000-8000-000000000001"
        assert echo["mentions"] == ["agent-b"]
        assert echo["dropped_mention_agent_ids"] == ["agent-c"]
        assert notify_calls[0]["recipient_agent_ids"] == ["agent-b"]
        assert notify_calls[0]["ws_body"]["id"] == echo["id"]
        assert notify_calls[0]["ws_body"]["reply_to_message_id"] == "00000000-0000-4000-8000-000000000001"
        assert notify_calls[0]["webhook_payload"]["id"] == echo["id"]
        assert msgbox_calls == []
        assert any(event["event"] == "a2a_room_mention_dropped" for event in events)

    asyncio.run(run())


def test_room_message_stale_expected_last_id_is_not_broadcast(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        sender_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=sender_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)

        notify_calls = []

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_record_social_message(*_args, **_kwargs):
            return SimpleNamespace(
                ok=False,
                stale=True,
                current_last_message={
                    "id": "00000000-0000-4000-8000-000000000099",
                    "text": "newer",
                },
            )

        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "record_social_message", fake_record_social_message)
        monkeypatch.setattr(
            ws_social_inbound,
            "schedule_social_notify",
            lambda **kwargs: notify_calls.append(kwargs),
        )

        await ws_social_inbound._handle_send_message(
            sender_ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(social_require_explicit_mentions=False),
            "agent-a",
            "Agent A",
            1,
            {
                "text": "stale reply",
                "expected_last_message_id": "00000000-0000-4000-8000-000000000001",
            },
        )

        assert sender_ws.sent[-1]["type"] == "error"
        assert sender_ws.sent[-1]["reason"] == "stale_room_state"
        assert sender_ws.sent[-1]["current_last_message"]["id"] == "00000000-0000-4000-8000-000000000099"
        assert peer_ws.sent == []
        assert notify_calls == []
        assert room.message_count == 0

    asyncio.run(run())


def test_room_message_is_not_broadcast_when_persist_fails(monkeypatch) -> None:
    async def run():
        registry = SocialRoomRegistry()
        sender_ws = _FakeWebSocket()
        peer_ws = _FakeWebSocket()
        room = await registry.create_room(
            name="room",
            brief="brief",
            creator_id="agent-a",
            creator_name="Agent A",
            ws=sender_ws,
        )
        assert not isinstance(room, str)
        joined = await registry.join_room(
            room_id=room.room_id,
            agent_id="agent-b",
            agent_name="Agent B",
            ws=peer_ws,
        )
        assert not isinstance(joined, str)

        notify_calls = []

        async def fake_check_permission(*_args, **_kwargs):
            return True

        async def fake_record_social_message(*_args, **_kwargs):
            return False

        monkeypatch.setattr(ws_social_inbound, "check_permission", fake_check_permission)
        monkeypatch.setattr(ws_social_inbound, "record_social_message", fake_record_social_message)
        monkeypatch.setattr(
            ws_social_inbound,
            "schedule_social_notify",
            lambda **kwargs: notify_calls.append(kwargs),
        )

        await ws_social_inbound._handle_send_message(
            sender_ws,
            registry,
            _FakeSessionFactory(),
            SimpleNamespace(),
            SimpleNamespace(social_require_explicit_mentions=False),
            "agent-a",
            "Agent A",
            1,
            {"text": "hello"},
        )

        assert sender_ws.sent[-1]["type"] == "error"
        assert sender_ws.sent[-1]["reason"] == "message_persist_failed"
        assert peer_ws.sent == []
        assert notify_calls == []
        assert room.message_count == 0

    asyncio.run(run())


def test_build_message_notify_carries_message_id() -> None:
    from app.services.social_notify import build_message_notify

    ws_body, hook = build_message_notify(
        room_id="room-1",
        room_name="Hall",
        sender_agent_id="agt_a",
        sender_agent_name="A",
        text="ping",
        mentions=["agt_b"],
        sent_at="2026-05-12T12:00:00+00:00",
        routing_mode="explicit",
        message_id="00000000-0000-4000-8000-000000000001",
    )
    assert ws_body["id"] == "00000000-0000-4000-8000-000000000001"
    assert hook["id"] == ws_body["id"]


def test_direct_message_still_uses_msgbox(monkeypatch) -> None:
    async def run():
        sender = _agent("agent-a", "Agent A")
        recipient = _agent("agent-b", "Agent B")
        calls = []
        notify_calls = []

        async def fake_push_message(*args, **kwargs):
            calls.append((args, kwargs))
            return "dm-id"

        async def fake_record_event(*_args, **_kwargs):
            return None

        async def fake_notify(*args, **kwargs):
            notify_calls.append((args, kwargs))

        monkeypatch.setattr(ws_send_direct_message, "push_message", fake_push_message)
        monkeypatch.setattr(ws_send_direct_message, "record_agent_event", fake_record_event)
        def fake_create_task(coro):
            coro.close()
            return None

        monkeypatch.setattr(ws_send_direct_message, "push_msgbox_notify_to_agent", fake_notify)
        monkeypatch.setattr(ws_send_direct_message.asyncio, "create_task", fake_create_task)

        result = await ws_send_direct_message.handle_send_direct_message_ws_message(
            session_factory=_FakeSessionFactory([sender, recipient]),
            registry=_FakeRegistry(),
            agent_id="agent-a",
            connection_id="conn-a",
            data={"type": "send_direct_message", "to_agent_id": "agent-b", "body": "hi"},
        )

        assert result == {
            "type": "send_direct_message_ok",
            "message_id": "dm-id",
            "to_agent_id": "agent-b",
        }
        assert calls[0][1]["type"] == "direct_message"

    asyncio.run(run())
