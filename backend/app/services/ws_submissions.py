"""
Submission frame handlers for the unified `/v2/agent/ws` socket.

This module handles `submit_submission` after `app.ws_agent` has authenticated
and owns the agent session. It is not a separate WebSocket endpoint.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.agent_event_log import record_agent_event
from app.services.submissions import (
    create_submission,
    enqueue_submission_review,
    submission_to_dict,
)


class _SubmitSubmissionPayload(BaseModel):
    kind: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=200000)
    source: str = Field(default="agent_ws", min_length=1, max_length=60)
    artifact_type: str | None = Field(default=None, max_length=40)
    target_slug: str | None = Field(default=None, max_length=120)
    target_path: str | None = Field(default=None, max_length=2048)
    payload: dict[str, Any] = Field(default_factory=dict)


def _validate_artifact_provenance(artifact_type: str | None, payload: dict[str, Any]) -> Dict[str, Any] | None:
    if artifact_type not in {"skill", "plugin"}:
        return None
    required = ("license", "permissions_requested", "secrets_required", "install_instructions")
    missing = [name for name in required if name not in payload]
    if missing:
        return {
            "type": "error",
            "reason": "missing_artifact_provenance",
            "detail": f"Missing provenance fields for {artifact_type}: {', '.join(missing)}.",
        }
    return None


async def handle_submit_submission_ws_message(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: Any,
    agent_id: str,
    agent_name: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        payload = _SubmitSubmissionPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_submit_submission_payload", "detail": exc.errors()}

    provenance_error = _validate_artifact_provenance(payload.artifact_type, payload.payload)
    if provenance_error is not None:
        return provenance_error

    async with session_factory() as session:
        try:
            submission = await create_submission(
                session,
                kind=payload.kind,
                source=payload.source,
                artifact_type=payload.artifact_type,
                title=payload.title,
                body=payload.body,
                target_slug=payload.target_slug,
                target_path=payload.target_path,
                submitter_type="agent",
                submitter_agent_id=agent_id,
                submitter_name=agent_name,
                payload=payload.payload,
            )
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            if isinstance(detail, str):
                return {"type": "error", "reason": "submission_create_failed", "detail": detail}
            return {"type": "error", "reason": "submission_create_failed"}

    message_id = await enqueue_submission_review(
        session_factory,
        registry,
        submission=submission,
    )
    await record_agent_event(
        session_factory,
        event="submission_created_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={
            "submission_id": str(submission.id),
            "kind": submission.kind,
            "artifact_type": submission.artifact_type,
            "message_id": message_id,
        },
    )
    return {
        "type": "submit_submission_ok",
        "submission_id": str(submission.id),
        "status": submission.status,
        "submission": submission_to_dict(submission),
    }
