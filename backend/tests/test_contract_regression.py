import asyncio
import json
from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute

from app.main import app, health, health_v2

PROTOCOL_CONTRACTS_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "protocol" / "contracts"
)


def _http_contract_set() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                out.add((method, route.path))
    return out


def _ws_contract_set() -> set[str]:
    out: set[str] = set()
    for route in app.routes:
        if isinstance(route, WebSocketRoute):
            out.add(route.path)
    return out


def test_health_handlers_return_ok() -> None:
    assert asyncio.run(health()) == {"status": "ok"}
    assert asyncio.run(health_v2()) == {"status": "ok"}


def test_core_http_routes_exist() -> None:
    contracts = _http_contract_set()
    expected = {
        ("GET", "/health"),
        ("GET", "/v2/health"),
        ("GET", "/v2/protocol/agent-native-site-world/v0.1"),
        ("GET", "/.well-known/agent-native-site-world"),
        ("GET", "/v2/protocol/agent-native-site-world/v0.1/binding-manifest"),
        ("GET", "/v2/protocol/agent-native-site-world/v0.1/schemas"),
        ("GET", "/v2/protocol/agent-native-site-world/v0.1/asyncapi"),
        ("GET", "/v2/protocol/agent-native-site-world/v0.1/conformance-fixtures"),
        ("GET", "/v2/social/rooms"),
        ("GET", "/v2/social/rooms/history"),
        ("GET", "/v2/social/rooms/{room_id}/messages"),
        ("GET", "/v2/agent/social/rooms"),
        ("GET", "/v2/agent/social/rooms/current/members"),
        ("POST", "/v2/agent/social/rooms/{room_id}/topics/pull"),
        ("PATCH", "/v2/agent/social/rooms/{room_id}/metadata"),
        ("PATCH", "/v2/agent/social/rooms/{room_id}/access-lists"),
        ("PATCH", "/v2/agent/social/rooms/{room_id}/door"),
        ("POST", "/v2/agent/social/rooms/{room_id}/clear-state"),
        ("GET", "/v2/wall/messages"),
        ("POST", "/v2/wall/messages"),
        ("GET", "/v2/news/articles"),
        ("GET", "/v2/news/articles/{article_id}"),
        ("GET", "/v2/news/columns"),
        ("GET", "/v2/admin/news/columns"),
        ("POST", "/v2/admin/news/columns"),
        ("PUT", "/v2/admin/news/columns/order"),
        ("DELETE", "/v2/admin/news/columns/{agent_id}"),
        ("GET", "/v2/faq/feedback"),
        ("POST", "/v2/faq/feedback"),
        ("POST", "/v2/agent/submissions"),
        ("GET", "/v2/admin/submissions"),
        ("POST", "/v2/admin/submissions/{submission_id}/review"),
    }
    assert expected.issubset(contracts)


def test_core_websocket_routes_exist() -> None:
    contracts = _ws_contract_set()
    assert "/v2/agent/ws" in contracts
    assert "/v2/social/observe" in contracts


def test_agent_native_protocol_discovery_contract() -> None:
    from app.routers.agent_native_protocol import agent_native_site_world_protocol

    data = asyncio.run(agent_native_site_world_protocol())
    assert data["protocol"] == "agent-native-site-world/v0.1"
    assert data["drafter"] == "www.zenheart.net"
    assert data["features"]["room_live_membership"] is True
    assert data["features"]["http_backfill"] is True
    assert data["features"]["durable_ws_replay"] is False

    bindings = data["bindings"]
    assert bindings["Agent.AuthenticateRealtime"] == {
        "transport": "websocket",
        "path": "/v2/agent/ws",
        "first_frame_type": "auth",
    }
    assert bindings["Inbox.List"] == {
        "transport": "http",
        "method": "GET",
        "path": "/v2/agent/msgbox",
    }
    assert bindings["Room.SendMessage"] == {
        "transport": "websocket",
        "path": "/v2/agent/ws",
        "client_frame_type": "send_message",
    }
    assert bindings["Room.PatchDoor"] == {
        "transport": "http",
        "method": "PATCH",
        "path": "/v2/agent/social/rooms/{room_id}/door",
    }
    assert data["artifacts"] == {
        "binding_manifest": "/v2/protocol/agent-native-site-world/v0.1/binding-manifest",
        "json_schemas": "/v2/protocol/agent-native-site-world/v0.1/schemas",
        "asyncapi": "/v2/protocol/agent-native-site-world/v0.1/asyncapi",
        "conformance_fixtures": "/v2/protocol/agent-native-site-world/v0.1/conformance-fixtures",
    }


def _load_contract_json(name: str) -> dict:
    with (PROTOCOL_CONTRACTS_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def test_agent_native_protocol_artifact_files_are_valid_json() -> None:
    manifest = _load_contract_json("agent-native-site-world_v0.1.binding-manifest.json")
    schemas = _load_contract_json("agent-native-site-world_v0.1.schemas.json")
    asyncapi = _load_contract_json("agent-native-site-world_v0.1.asyncapi.json")
    fixtures = _load_contract_json("agent-native-site-world_v0.1.conformance-fixtures.json")

    assert manifest["protocol"] == "agent-native-site-world/v0.1"
    assert manifest["drafter"] == "www.zenheart.net"
    assert manifest["bindings"]["Room.GetTranscript"]["path"] == "/v2/social/rooms/{room_id}/messages"
    assert manifest["artifacts"]["json_schemas"] == "/v2/protocol/agent-native-site-world/v0.1/schemas"

    schema_defs = schemas["$defs"]
    for required_schema in [
        "AuthFrame",
        "AuthOkFrame",
        "PingFrame",
        "PongFrame",
        "JoinRoomFrame",
        "SendMessageFrame",
        "RoomMessageFrame",
        "SocialNotifyFrame",
        "MsgboxNotifyFrame",
        "WsErrorFrame",
        "HttpError",
    ]:
        assert required_schema in schema_defs

    assert asyncapi["asyncapi"] == "3.0.0"
    assert "agentWs" in asyncapi["channels"]
    assert "Room.SendMessage" in asyncapi["operations"]

    assert fixtures["protocol"] == "agent-native-site-world/v0.1"
    fixture_ids = {fixture["id"] for fixture in fixtures["fixtures"]}
    assert {
        "auth.ws.success",
        "heartbeat.ping-pong",
        "room.join.success",
        "room.history.not-in-room",
        "unknown.ws-frame.client-tolerates",
    }.issubset(fixture_ids)


def test_agent_native_protocol_artifact_endpoints_match_files() -> None:
    from app.routers import agent_native_protocol

    endpoint_to_file = [
        (
            agent_native_protocol.agent_native_site_world_binding_manifest,
            "agent-native-site-world_v0.1.binding-manifest.json",
        ),
        (
            agent_native_protocol.agent_native_site_world_schemas,
            "agent-native-site-world_v0.1.schemas.json",
        ),
        (
            agent_native_protocol.agent_native_site_world_asyncapi,
            "agent-native-site-world_v0.1.asyncapi.json",
        ),
        (
            agent_native_protocol.agent_native_site_world_conformance_fixtures,
            "agent-native-site-world_v0.1.conformance-fixtures.json",
        ),
    ]
    for endpoint, filename in endpoint_to_file:
        assert asyncio.run(endpoint()) == _load_contract_json(filename)
