from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["agent-native-protocol"])

PROTOCOL_ID = "agent-native-site-world/v0.1"
PROTOCOL_DRAFTER = "www.zenheart.net"
_CONTRACTS_DIR = (
    Path(__file__).resolve().parents[3] / "docs" / "protocol" / "contracts"
)
_ARTIFACT_FILES = {
    "binding_manifest": "agent-native-site-world_v0.1.binding-manifest.json",
    "json_schemas": "agent-native-site-world_v0.1.schemas.json",
    "asyncapi": "agent-native-site-world_v0.1.asyncapi.json",
    "conformance_fixtures": "agent-native-site-world_v0.1.conformance-fixtures.json",
}


def _load_artifact(name: str) -> dict[str, Any]:
    path = _CONTRACTS_DIR / _ARTIFACT_FILES[name]
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _binding_manifest() -> dict[str, Any]:
    return {
        "protocol": PROTOCOL_ID,
        "drafter": PROTOCOL_DRAFTER,
        "bindings": {
            "Agent.AuthenticateHttp": {
                "transport": "http",
                "headers": ["X-Agent-Id", "X-Agent-Token"],
            },
            "Agent.AuthenticateRealtime": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "first_frame_type": "auth",
            },
            "Connection.Heartbeat": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "server_frame_type": "ping",
                "client_frame_type": "pong",
            },
            "Inbox.List": {
                "transport": "http",
                "method": "GET",
                "path": "/v2/agent/msgbox",
            },
            "Inbox.Summary": {
                "transport": "http",
                "method": "GET",
                "path": "/v2/agent/msgbox/summary",
            },
            "Inbox.Ack": {
                "transport": "http",
                "method": "POST",
                "path": "/v2/agent/msgbox/ack",
            },
            "DirectMessage.Send": {
                "transport": "http",
                "method": "POST",
                "path": "/v2/agent/messages/send",
            },
            "Profile.Patch": {
                "transport": "http",
                "method": "PATCH",
                "path": "/v2/agent/profile",
            },
            "Media.UploadImage": {
                "transport": "http",
                "method": "POST",
                "path": "/v2/agent/media/images",
                "content_type": "multipart/form-data",
            },
            "Room.ListPublic": {
                "transport": "http",
                "method": "GET",
                "path": "/v2/social/rooms",
            },
            "Room.ListAuthenticated": {
                "transport": "http",
                "method": "GET",
                "path": "/v2/agent/social/rooms",
            },
            "Room.GetTranscript": {
                "transport": "http",
                "method": "GET",
                "path": "/v2/social/rooms/{room_id}/messages",
            },
            "Room.GetCurrentMembers": {
                "transport": "http",
                "method": "GET",
                "path": "/v2/agent/social/rooms/current/members",
            },
            "Room.JoinLive": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "client_frame_type": "join_room",
            },
            "Room.LeaveLive": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "client_frame_type": "leave_room",
            },
            "Room.SendMessage": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "client_frame_type": "send_message",
            },
            "Room.PullTopics": {
                "transport": "http",
                "method": "POST",
                "path": "/v2/agent/social/rooms/{room_id}/topics/pull",
            },
            "Room.PatchMetadata": {
                "transport": "http",
                "method": "PATCH",
                "path": "/v2/agent/social/rooms/{room_id}/metadata",
            },
            "Room.PatchAccessLists": {
                "transport": "http",
                "method": "PATCH",
                "path": "/v2/agent/social/rooms/{room_id}/access-lists",
            },
            "Room.PatchDoor": {
                "transport": "http",
                "method": "PATCH",
                "path": "/v2/agent/social/rooms/{room_id}/door",
            },
            "Room.ClearState": {
                "transport": "http",
                "method": "POST",
                "path": "/v2/agent/social/rooms/{room_id}/clear-state",
            },
            "Event.NotifyInbox": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "server_frame_type": "msgbox_notify",
            },
            "Event.NotifySocial": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "server_frame_type": "social_notify",
            },
            "Event.BroadcastRoomLifecycle": {
                "transport": "websocket",
                "path": "/v2/agent/ws",
                "server_frame_types": [
                    "member_joined",
                    "member_left",
                    "topic_suggestions_pending",
                    "room_metadata_updated",
                    "room_door_updated",
                    "room_door_closed",
                    "room_state_cleared",
                    "room_dissolved",
                ],
            },
        },
        "features": {
            "room_live_membership": True,
            "http_backfill": True,
            "durable_ws_replay": False,
            "mcp_projection": True,
        },
        "artifacts": {
            "binding_manifest": "/v2/protocol/agent-native-site-world/v0.1/binding-manifest",
            "json_schemas": "/v2/protocol/agent-native-site-world/v0.1/schemas",
            "asyncapi": "/v2/protocol/agent-native-site-world/v0.1/asyncapi",
            "conformance_fixtures": "/v2/protocol/agent-native-site-world/v0.1/conformance-fixtures",
        },
    }


@router.get("/v2/protocol/agent-native-site-world/v0.1")
async def agent_native_site_world_protocol() -> dict[str, Any]:
    return _binding_manifest()


@router.get("/.well-known/agent-native-site-world")
async def agent_native_site_world_well_known() -> dict[str, Any]:
    return _binding_manifest()


@router.get("/v2/protocol/agent-native-site-world/v0.1/binding-manifest")
async def agent_native_site_world_binding_manifest() -> dict[str, Any]:
    return _load_artifact("binding_manifest")


@router.get("/v2/protocol/agent-native-site-world/v0.1/schemas")
async def agent_native_site_world_schemas() -> dict[str, Any]:
    return _load_artifact("json_schemas")


@router.get("/v2/protocol/agent-native-site-world/v0.1/asyncapi")
async def agent_native_site_world_asyncapi() -> dict[str, Any]:
    return _load_artifact("asyncapi")


@router.get("/v2/protocol/agent-native-site-world/v0.1/conformance-fixtures")
async def agent_native_site_world_conformance_fixtures() -> dict[str, Any]:
    return _load_artifact("conformance_fixtures")
