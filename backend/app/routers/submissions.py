from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import AgentDep, DbSession, admin_or_sovereign_guard
from app.model_defs import Submission
from app.services.submissions import (
    OPEN_STATUSES,
    add_submission_comment,
    apply_submission_review,
    comment_to_dict,
    create_submission,
    enqueue_submission_review,
    list_submission_comments,
    list_submission_reviews,
    load_submission_or_404,
    notify_submission_submitter,
    record_submission_event,
    review_to_dict,
    submission_to_dict,
)

public_router = APIRouter(tags=["submissions"])
agent_router = APIRouter(prefix="/v2/agent/submissions", tags=["agent-submissions"])
admin_router = APIRouter(
    prefix="/v2/admin/submissions",
    tags=["admin-submissions"],
    dependencies=[Depends(admin_or_sovereign_guard)],
)

_RATE_LIMIT = 10
_RATE_WINDOW = 60.0
_timestamps: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    window = [t for t in _timestamps[key] if t > cutoff]
    if len(window) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
        )
    window.append(now)
    _timestamps[key] = window


def _reviewer_id_from_request(request: Request) -> str:
    agent_id = (request.headers.get("X-Agent-Id") or "").strip()
    return agent_id or "admin_http"


def _validate_artifact_provenance(artifact_type: str | None, payload: dict[str, Any]) -> None:
    if artifact_type not in {"skill", "mcp"}:
        return
    required = ("license", "permissions_requested", "secrets_required", "install_instructions")
    missing = [name for name in required if name not in payload]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing provenance fields for {artifact_type}: {', '.join(missing)}.",
        )


class SubmissionCreateResponse(BaseModel):
    id: str
    status: str
    message: str
    submission: dict[str, Any]


class SubmissionListResponse(BaseModel):
    submissions: list[dict[str, Any]]
    count: int


class PublicFaqFeedbackRow(BaseModel):
    id: str
    title: str
    status: str
    doc_slug: Optional[str] = None
    created_at: str
    updated_at: str
    reviewed_at: Optional[str] = None


class PublicFaqFeedbackListResponse(BaseModel):
    submissions: list[PublicFaqFeedbackRow]
    count: int


class SubmissionDetailResponse(BaseModel):
    submission: dict[str, Any]
    comments: list[dict[str, Any]]
    reviews: list[dict[str, Any]]


class FaqFeedbackRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=8000)
    doc_slug: Optional[str] = Field(default=None, max_length=120)
    page_url: Optional[str] = Field(default=None, max_length=2048)
    from_name: Optional[str] = Field(default=None, max_length=120)
    contact: Optional[str] = Field(default=None, max_length=320)


class AgentSubmissionRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=200000)
    source: str = Field(default="agent", min_length=1, max_length=60)
    artifact_type: Optional[str] = Field(default=None, max_length=40)
    target_slug: Optional[str] = Field(default=None, max_length=120)
    target_path: Optional[str] = Field(default=None, max_length=2048)
    payload: dict[str, Any] = Field(default_factory=dict)


class SubmissionCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    payload: dict[str, Any] = Field(default_factory=dict)


class SubmissionReviewRequest(BaseModel):
    decision: str = Field(min_length=1, max_length=30)
    summary: str = Field(min_length=1, max_length=20000)
    owner_report: Optional[str] = Field(default=None, max_length=20000)
    payload: dict[str, Any] = Field(default_factory=dict)


async def _submission_detail(session: DbSession, submission: Submission) -> SubmissionDetailResponse:
    comments = await list_submission_comments(session, submission.id)
    reviews = await list_submission_reviews(session, submission.id)
    return SubmissionDetailResponse(
        submission=submission_to_dict(submission),
        comments=[comment_to_dict(row) for row in comments],
        reviews=[review_to_dict(row) for row in reviews],
    )


@public_router.post(
    "/v2/faq/feedback",
    response_model=SubmissionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_faq_feedback(
    body: FaqFeedbackRequest,
    request: Request,
    session: DbSession,
) -> SubmissionCreateResponse:
    ip = _client_ip(request)
    _check_rate_limit(f"faq-feedback:{ip}")
    payload = {
        "doc_slug": body.doc_slug,
        "page_url": body.page_url,
        "client_ip": ip,
    }
    submission = await create_submission(
        session,
        kind="issue",
        source="faq",
        title=body.title,
        body=body.body,
        target_slug=body.doc_slug,
        target_path=body.page_url,
        submitter_type="human",
        submitter_name=body.from_name,
        submitter_contact=body.contact,
        payload=payload,
    )
    message_id = await enqueue_submission_review(
        request.app.state.session_factory,
        request.app.state.registry,
        submission=submission,
    )
    await record_submission_event(
        request.app.state.session_factory,
        event="submission_created_public",
        agent_id=None,
        submission_id=str(submission.id),
        detail={"kind": submission.kind, "source": submission.source, "message_id": message_id},
    )
    return SubmissionCreateResponse(
        id=str(submission.id),
        status=submission.status,
        message="Feedback received and queued for review.",
        submission=submission_to_dict(submission, include_payload=False),
    )


@public_router.get("/v2/faq/feedback", response_model=PublicFaqFeedbackListResponse)
async def list_faq_feedback(
    session: DbSession,
    limit: int = Query(default=30, ge=1, le=100),
) -> PublicFaqFeedbackListResponse:
    rows = list(
        (
            await session.scalars(
                select(Submission)
                .where(Submission.kind == "issue", Submission.source == "faq")
                .order_by(Submission.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    items = [
        PublicFaqFeedbackRow(
            id=str(row.id),
            title=row.title,
            status=row.status,
            doc_slug=row.target_slug,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
            reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        )
        for row in rows
    ]
    return PublicFaqFeedbackListResponse(submissions=items, count=len(items))


@agent_router.post("", response_model=SubmissionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_submission(
    body: AgentSubmissionRequest,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> SubmissionCreateResponse:
    _validate_artifact_provenance(body.artifact_type, body.payload)
    submission = await create_submission(
        session,
        kind=body.kind,
        source=body.source,
        artifact_type=body.artifact_type,
        title=body.title,
        body=body.body,
        target_slug=body.target_slug,
        target_path=body.target_path,
        submitter_type="agent",
        submitter_agent_id=agent.agent_id,
        submitter_name=agent.agent_name,
        payload=body.payload,
    )
    message_id = await enqueue_submission_review(
        request.app.state.session_factory,
        request.app.state.registry,
        submission=submission,
    )
    await record_submission_event(
        request.app.state.session_factory,
        event="submission_created_agent",
        agent_id=agent.agent_id,
        submission_id=str(submission.id),
        detail={
            "kind": submission.kind,
            "source": submission.source,
            "artifact_type": submission.artifact_type,
            "message_id": message_id,
        },
    )
    return SubmissionCreateResponse(
        id=str(submission.id),
        status=submission.status,
        message="Submission queued for review.",
        submission=submission_to_dict(submission),
    )


@agent_router.get("", response_model=SubmissionListResponse)
async def list_my_submissions(
    session: DbSession,
    agent: AgentDep,
    status_filter: Optional[str] = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
) -> SubmissionListResponse:
    query = (
        select(Submission)
        .where(Submission.submitter_agent_id == agent.agent_id)
        .order_by(Submission.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        query = query.where(Submission.status == status_filter)
    rows = list((await session.scalars(query)).all())
    return SubmissionListResponse(
        submissions=[submission_to_dict(row) for row in rows],
        count=len(rows),
    )


@agent_router.get("/{submission_id}", response_model=SubmissionDetailResponse)
async def get_my_submission(
    submission_id: str,
    session: DbSession,
    agent: AgentDep,
) -> SubmissionDetailResponse:
    submission = await load_submission_or_404(session, submission_id)
    if submission.submitter_agent_id != agent.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission belongs to another agent.")
    return await _submission_detail(session, submission)


@agent_router.post("/{submission_id}/comments", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
async def comment_on_my_submission(
    submission_id: str,
    body: SubmissionCommentRequest,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> dict[str, Any]:
    submission = await load_submission_or_404(session, submission_id)
    if submission.submitter_agent_id != agent.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission belongs to another agent.")
    if submission.status not in OPEN_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submission is closed.")
    comment = await add_submission_comment(
        session,
        submission=submission,
        author_type="agent",
        author_agent_id=agent.agent_id,
        author_name=agent.agent_name,
        body=body.body,
        payload=body.payload,
    )
    await record_submission_event(
        request.app.state.session_factory,
        event="submission_commented_agent",
        agent_id=agent.agent_id,
        submission_id=str(submission.id),
    )
    return {"comment": comment_to_dict(comment)}


@admin_router.get("", response_model=SubmissionListResponse)
async def admin_list_submissions(
    session: DbSession,
    status_filter: Optional[str] = Query(default=None, alias="status", max_length=30),
    kind: Optional[str] = Query(default=None, max_length=20),
    artifact_type: Optional[str] = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
) -> SubmissionListResponse:
    query = select(Submission).order_by(Submission.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Submission.status == status_filter)
    if kind:
        query = query.where(Submission.kind == kind)
    if artifact_type:
        query = query.where(Submission.artifact_type == artifact_type)
    rows = list((await session.scalars(query)).all())
    return SubmissionListResponse(
        submissions=[submission_to_dict(row) for row in rows],
        count=len(rows),
    )


@admin_router.get("/{submission_id}", response_model=SubmissionDetailResponse)
async def admin_get_submission(submission_id: str, session: DbSession) -> SubmissionDetailResponse:
    submission = await load_submission_or_404(session, submission_id)
    return await _submission_detail(session, submission)


@admin_router.post("/{submission_id}/claim", response_model=SubmissionDetailResponse)
async def admin_claim_submission(
    submission_id: str,
    request: Request,
    session: DbSession,
) -> SubmissionDetailResponse:
    submission = await load_submission_or_404(session, submission_id)
    reviewer_id = _reviewer_id_from_request(request)
    await apply_submission_review(
        session,
        submission=submission,
        reviewer_agent_id=reviewer_id,
        decision="claim",
        summary="Claimed for review.",
    )
    await record_submission_event(
        request.app.state.session_factory,
        event="submission_claimed_admin_http",
        agent_id=None if reviewer_id == "admin_http" else reviewer_id,
        submission_id=str(submission.id),
    )
    return await _submission_detail(session, submission)


@admin_router.post("/{submission_id}/review", response_model=SubmissionDetailResponse)
async def admin_review_submission(
    submission_id: str,
    body: SubmissionReviewRequest,
    request: Request,
    session: DbSession,
) -> SubmissionDetailResponse:
    submission = await load_submission_or_404(session, submission_id)
    reviewer_id = _reviewer_id_from_request(request)
    await apply_submission_review(
        session,
        submission=submission,
        reviewer_agent_id=reviewer_id,
        decision=body.decision,
        summary=body.summary,
        owner_report=body.owner_report,
        payload=body.payload,
    )
    message_id = await notify_submission_submitter(
        request.app.state.session_factory,
        request.app.state.registry,
        submission=submission,
        decision=body.decision,
        summary=body.summary,
    )
    await record_submission_event(
        request.app.state.session_factory,
        event="submission_reviewed_admin_http",
        agent_id=None if reviewer_id == "admin_http" else reviewer_id,
        submission_id=str(submission.id),
        detail={"decision": body.decision, "message_id": message_id},
    )
    return await _submission_detail(session, submission)
