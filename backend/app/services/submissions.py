from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.model_defs import Submission, SubmissionComment, SubmissionReview
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import push_message
from app.services.msgbox_notify import push_msgbox_notify_to_agent
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns

VALID_KINDS = {"issue", "proposal"}
VALID_STATUSES = {"pending", "claimed", "changes_requested", "accepted", "rejected", "published"}
OPEN_STATUSES = {"pending", "claimed", "changes_requested"}
VALID_ARTIFACT_TYPES = {"skill", "mcp", "protocol", "doc", "site"}
VALID_REVIEW_DECISIONS = {"claim", "request_changes", "accept", "reject", "publish"}

_DECISION_TO_STATUS = {
    "claim": "claimed",
    "request_changes": "changes_requested",
    "accept": "accepted",
    "reject": "rejected",
    "publish": "published",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_submission_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    return {str(k): v for k, v in payload.items()}


def submission_to_dict(row: Submission, *, include_payload: bool = True) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(row.id),
        "kind": row.kind,
        "status": row.status,
        "source": row.source,
        "artifact_type": row.artifact_type,
        "title": row.title,
        "body": row.body,
        "target_slug": row.target_slug,
        "target_path": row.target_path,
        "submitter_type": row.submitter_type,
        "submitter_agent_id": row.submitter_agent_id,
        "submitter_name": row.submitter_name,
        "reviewer_agent_id": row.reviewer_agent_id,
        "report": row.report,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }
    if include_payload:
        body["payload"] = row.payload
    return body


def comment_to_dict(row: SubmissionComment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "submission_id": str(row.submission_id),
        "author_type": row.author_type,
        "author_agent_id": row.author_agent_id,
        "author_name": row.author_name,
        "visibility": row.visibility,
        "body": row.body,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
    }


def review_to_dict(row: SubmissionReview) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "submission_id": str(row.submission_id),
        "reviewer_agent_id": row.reviewer_agent_id,
        "decision": row.decision,
        "summary": row.summary,
        "owner_report": row.owner_report,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
    }


async def create_submission(
    session: AsyncSession,
    *,
    kind: str,
    source: str,
    title: str,
    body: str,
    submitter_type: str,
    artifact_type: Optional[str] = None,
    target_slug: Optional[str] = None,
    target_path: Optional[str] = None,
    submitter_agent_id: Optional[str] = None,
    submitter_name: Optional[str] = None,
    submitter_contact: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Submission:
    kind = kind.strip()
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid submission kind.")
    if artifact_type is not None and artifact_type not in VALID_ARTIFACT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid artifact_type.")

    now = utc_now()
    row = Submission(
        kind=kind,
        status="pending",
        source=source.strip(),
        artifact_type=artifact_type,
        title=title.strip(),
        body=body.strip(),
        target_slug=(target_slug or "").strip() or None,
        target_path=(target_path or "").strip() or None,
        submitter_type=submitter_type.strip(),
        submitter_agent_id=submitter_agent_id,
        submitter_name=(submitter_name or "").strip() or None,
        submitter_contact=(submitter_contact or "").strip() or None,
        payload=normalize_submission_payload(payload),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def enqueue_submission_review(
    session_factory: async_sessionmaker[AsyncSession],
    registry: Any,
    *,
    submission: Submission,
    preview: Optional[str] = None,
) -> Optional[str]:
    msg_type = f"submission:{submission.kind}"
    message_id = await push_message(
        session_factory,
        scope="global",
        from_type="agent" if submission.submitter_type == "agent" else "anonymous",
        from_agent_id=submission.submitter_agent_id,
        visitor_from_name=submission.submitter_name,
        type=msg_type,
        priority=1 if submission.kind == "proposal" else 2,
        resource_type="submission",
        resource_id=str(submission.id),
        payload={
            "kind": submission.kind,
            "status": submission.status,
            "source": submission.source,
            "artifact_type": submission.artifact_type,
            "target_slug": submission.target_slug,
            "title": submission.title,
            "preview": preview or submission.body[:200],
        },
    )
    if message_id is not None:
        asyncio.create_task(
            push_msgbox_notify_to_sovereigns(
                session_factory,
                registry,
                message_id=message_id,
                kind=msg_type,
                preview=preview or submission.title,
                extra={
                    "resource_type": "submission",
                    "resource_id": str(submission.id),
                    "priority": 1 if submission.kind == "proposal" else 2,
                },
            )
        )
    return message_id


async def notify_submission_submitter(
    session_factory: async_sessionmaker[AsyncSession],
    registry: Any,
    *,
    submission: Submission,
    decision: str,
    summary: str,
) -> Optional[str]:
    if not submission.submitter_agent_id:
        return None
    message_id = await push_message(
        session_factory,
        scope="agent",
        recipient_id=submission.submitter_agent_id,
        from_type="sovereign",
        type="submission_reviewed",
        priority=1 if decision in {"request_changes", "reject"} else 2,
        resource_type="submission",
        resource_id=str(submission.id),
        payload={
            "submission_id": str(submission.id),
            "title": submission.title,
            "decision": decision,
            "status": submission.status,
            "summary": summary[:2000],
        },
    )
    if message_id is not None:
        asyncio.create_task(
            push_msgbox_notify_to_agent(
                registry,
                submission.submitter_agent_id,
                kind="submission_reviewed",
                message_id=message_id,
                preview=summary[:200],
                extra={"resource_type": "submission", "resource_id": str(submission.id), "decision": decision},
            )
        )
    return message_id


async def load_submission_or_404(session: AsyncSession, submission_id: str) -> Submission:
    try:
        parsed = uuid.UUID(submission_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.") from exc
    row = await session.scalar(select(Submission).where(Submission.id == parsed))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    return row


async def list_submission_comments(session: AsyncSession, submission_id: uuid.UUID) -> list[SubmissionComment]:
    rows = (
        await session.scalars(
            select(SubmissionComment)
            .where(SubmissionComment.submission_id == submission_id)
            .order_by(SubmissionComment.created_at.asc())
        )
    ).all()
    return list(rows)


async def list_submission_reviews(session: AsyncSession, submission_id: uuid.UUID) -> list[SubmissionReview]:
    rows = (
        await session.scalars(
            select(SubmissionReview)
            .where(SubmissionReview.submission_id == submission_id)
            .order_by(SubmissionReview.created_at.asc())
        )
    ).all()
    return list(rows)


async def add_submission_comment(
    session: AsyncSession,
    *,
    submission: Submission,
    author_type: str,
    body: str,
    author_agent_id: Optional[str] = None,
    author_name: Optional[str] = None,
    visibility: str = "public",
    payload: Optional[dict[str, Any]] = None,
) -> SubmissionComment:
    now = utc_now()
    row = SubmissionComment(
        submission_id=submission.id,
        author_type=author_type,
        author_agent_id=author_agent_id,
        author_name=(author_name or "").strip() or None,
        visibility=visibility,
        body=body.strip(),
        payload=normalize_submission_payload(payload),
        created_at=now,
    )
    submission.updated_at = now
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def apply_submission_review(
    session: AsyncSession,
    *,
    submission: Submission,
    reviewer_agent_id: str,
    decision: str,
    summary: str,
    owner_report: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> SubmissionReview:
    decision = decision.strip()
    if decision not in VALID_REVIEW_DECISIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid review decision.")

    new_status = _DECISION_TO_STATUS[decision]
    now = utc_now()
    review = SubmissionReview(
        submission_id=submission.id,
        reviewer_agent_id=reviewer_agent_id,
        decision=decision,
        summary=summary.strip(),
        owner_report=(owner_report or "").strip() or None,
        payload=normalize_submission_payload(payload),
        created_at=now,
    )
    submission.status = new_status
    submission.reviewer_agent_id = reviewer_agent_id
    submission.updated_at = now
    submission.reviewed_at = now
    if new_status == "published":
        submission.published_at = now
    if owner_report:
        submission.report = {"owner_report": owner_report.strip(), "decision": decision}
    session.add(review)
    await session.commit()
    await session.refresh(submission)
    await session.refresh(review)
    return review


async def record_submission_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event: str,
    agent_id: Optional[str],
    submission_id: str,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    event_detail = {"submission_id": submission_id}
    if detail:
        event_detail.update(detail)
    await record_agent_event(
        session_factory,
        event=event,
        agent_id=agent_id,
        detail=event_detail,
    )
