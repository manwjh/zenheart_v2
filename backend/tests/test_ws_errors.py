import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.services.http_error_handlers import register_http_error_handlers
from app.services.ws_errors import _ERROR_CATALOG, auth_fail_error, enrich_error_payload, ws_error
from app.services import ws_social_inbound


def test_ws_error_preserves_legacy_reason_and_adds_agent_feedback() -> None:
    payload = ws_error(
        "invalid_create_room_payload",
        detail="name must be 1-80 chars",
        field="name",
    )

    assert payload["type"] == "error"
    assert payload["reason"] == "invalid_create_room_payload"
    assert payload["code"] == "invalid_create_room_payload"
    assert payload["message"] == "The request payload is invalid."
    assert payload["hint"] == "name must be 1-80 chars"
    assert payload["retryable"] is False
    assert payload["category"] == "validation"
    assert payload["action"] == "fix_payload"
    assert payload["field"] == "name"


def test_auth_fail_error_uses_same_feedback_contract() -> None:
    payload = auth_fail_error("invalid_token")

    assert payload["type"] == "auth_fail"
    assert payload["reason"] == "invalid_token"
    assert payload["code"] == "invalid_token"
    assert payload["message"] == "The agent token is invalid."
    assert payload["retryable"] is False
    assert payload["category"] == "auth"
    assert payload["action"] == "fix_credentials"


def test_enrich_error_payload_keeps_existing_fields() -> None:
    payload = enrich_error_payload({
        "type": "error",
        "reason": "rate_limit_exceeded",
        "request_id": "req_1",
    })

    assert payload["request_id"] == "req_1"
    assert payload["code"] == "rate_limit_exceeded"
    assert payload["retryable"] is True
    assert payload["category"] == "rate_limit"
    assert payload["action"] == "backoff"


def test_social_json_dump_enriches_error_frames() -> None:
    raw = ws_social_inbound._jdump({
        "type": "error",
        "reason": "not_in_room",
    })
    payload = json.loads(raw)

    assert payload["reason"] == "not_in_room"
    assert payload["code"] == "not_in_room"
    assert payload["message"] == "The agent is not currently a live member of the room."
    assert payload["category"] == "state"
    assert payload["action"] == "join_room_first"


def test_http_error_handler_preserves_detail_and_adds_error_object() -> None:
    app = FastAPI()
    register_http_error_handlers(app)

    @app.get("/limited")
    async def limited() -> None:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    response = TestClient(app).get("/limited")

    assert response.status_code == 429
    payload = response.json()
    assert payload["detail"] == "Too many requests. Please try again later."
    assert payload["error"]["code"] == "rate_limit_exceeded"
    assert payload["error"]["retryable"] is True
    assert payload["error"]["category"] == "rate_limit"
    assert payload["error"]["action"] == "backoff"


def test_catalog_entries_include_agent_decision_fields() -> None:
    for code, entry in _ERROR_CATALOG.items():
        assert entry["message"], code
        assert entry["hint"], code
        assert isinstance(entry["retryable"], bool), code
        assert entry["category"], code
        assert entry["action"], code
