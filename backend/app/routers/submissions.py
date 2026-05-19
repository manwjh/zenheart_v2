from __future__ import annotations

import json
import base64
import io
import time
import zipfile
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import AgentDep, DbSession, admin_or_sovereign_guard, optional_agent_auth
from app.model_defs import Agent, Submission
from app.services.skills_storage import is_valid_slug, skill_markdown_path
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
public_integration_router = APIRouter(
    prefix="/v2/public/submissions",
    tags=["public-submissions"],
)
admin_router = APIRouter(
    prefix="/v2/admin/submissions",
    tags=["admin-submissions"],
    dependencies=[Depends(admin_or_sovereign_guard)],
)

_RATE_LIMIT = 10
_PUBLIC_AGENT_RATE_LIMIT = 60
_PUBLIC_PAYLOAD_MAX_BYTES = 262_144
_PUBLIC_SKILL_BUNDLE_MAX_BYTES = 1_048_576
_PUBLIC_SKILL_PAYLOAD_MAX_BYTES = 1_500_000
_PUBLIC_SKILL_BUNDLE_MAX_FILES = 64
_PUBLIC_FEED_BODY_PREVIEW_MAX = 280
_RATE_WINDOW = 60.0
_timestamps: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(key: str, *, limit: int = _RATE_LIMIT) -> None:
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    window = [t for t in _timestamps[key] if t > cutoff]
    if len(window) >= limit:
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
    if artifact_type not in {"skill", "plugin"}:
        return
    required = ("license", "permissions_requested", "secrets_required", "install_instructions")
    missing = [name for name in required if name not in payload]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing provenance fields for {artifact_type}: {', '.join(missing)}.",
        )
    if not isinstance(payload["permissions_requested"], list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="permissions_requested must be a list.",
        )
    if not isinstance(payload["secrets_required"], bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="secrets_required must be a boolean.",
        )
    if not str(payload["license"]).strip() or not str(payload["install_instructions"]).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="license and install_instructions are required.",
        )


def _validate_public_slug(slug: str) -> None:
    if not is_valid_slug(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid slug. Use lowercase letters, numbers, and hyphens.",
        )


def _validate_public_payload_size(
    payload: dict[str, Any],
    *,
    max_bytes: int = _PUBLIC_PAYLOAD_MAX_BYTES,
) -> None:
    byte_length = len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if byte_length > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Submission payload is too large.",
        )


def _idempotency_key(request: Request) -> str | None:
    raw = (request.headers.get("Idempotency-Key") or "").strip()
    if not raw:
        return None
    if len(raw) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key is too long.",
        )
    return raw


async def _load_idempotent_submission(
    session: DbSession,
    *,
    source: str,
    idempotency_key: str,
    agent_id: str | None = None,
    client_ip: str | None = None,
) -> Submission | None:
    query = (
        select(Submission)
        .where(Submission.source == source)
        .order_by(Submission.created_at.desc())
        .limit(100)
    )
    if agent_id is not None:
        query = query.where(Submission.submitter_agent_id == agent_id)
    else:
        query = query.where(Submission.submitter_agent_id.is_(None))
    rows = list((await session.scalars(query)).all())
    for row in rows:
        payload = row.payload or {}
        if payload.get("idempotency_key") != idempotency_key:
            continue
        if agent_id is None and client_ip is not None and payload.get("client_ip") != client_ip:
            continue
        return row
    return None


def _idempotent_response(
    response: Response,
    submission: Submission,
    *,
    include_payload: bool = True,
) -> SubmissionCreateResponse:
    response.status_code = status.HTTP_200_OK
    return SubmissionCreateResponse(
        id=str(submission.id),
        status=submission.status,
        message="Existing submission returned for idempotency key.",
        submission=submission_to_dict(submission, include_payload=include_payload),
    )


def _public_body_preview(body: str) -> str:
    """Short plain-text preview for public list views (not full submission body)."""
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= _PUBLIC_FEED_BODY_PREVIEW_MAX:
        return text
    return text[: _PUBLIC_FEED_BODY_PREVIEW_MAX - 1] + "…"


def _public_submission_feed_row(row: Submission) -> dict[str, Any]:
    submitter_name = (row.submitter_name or "").strip() or None
    return {
        "id": str(row.id),
        "kind": row.kind,
        "status": row.status,
        "source": row.source,
        "artifact_type": row.artifact_type,
        "title": row.title,
        "body_preview": _public_body_preview(row.body),
        "target_slug": row.target_slug,
        "target_path": row.target_path,
        "submitter_type": row.submitter_type,
        "submitter_name": submitter_name,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


class SubmissionCreateResponse(BaseModel):
    id: str
    status: str
    message: str
    submission: dict[str, Any]


class SubmissionListResponse(BaseModel):
    submissions: list[dict[str, Any]]
    count: int


class PublicSubmissionFeedResponse(BaseModel):
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


class PublicFeedbackRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=8000)
    page_url: Optional[str] = Field(default=None, max_length=2048)
    category: str = Field(default="other", max_length=40)
    from_name: Optional[str] = Field(default=None, max_length=120)
    contact: Optional[str] = Field(default=None, max_length=320)


class PublicPluginSubmissionRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=10, max_length=20000)
    plugin_kind: str = Field(default="mcp_server", min_length=1, max_length=60)
    manifest: Optional[dict[str, Any]] = None
    documentation_markdown: Optional[str] = Field(default=None, max_length=200000)
    license: str = Field(min_length=1, max_length=120)
    permissions_requested: list[str] = Field(default_factory=list)
    secrets_required: bool
    install_instructions: str = Field(min_length=1, max_length=20000)
    repository_url: Optional[str] = Field(default=None, max_length=2048)
    security_notes: Optional[str] = Field(default=None, max_length=20000)


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


def _validate_skill_markdown(markdown: str) -> None:
    stripped = markdown.strip()
    if not stripped.startswith("#"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Skill markdown must start with a Markdown heading.",
        )


def _safe_bundle_path(raw_path: str) -> str:
    path = raw_path.replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/") or "\x00" in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bundle path.")
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bundle path.")
    return "/".join(parts)


def _flatten_outer_wrapper(files: dict[str, bytes]) -> dict[str, bytes]:
    if "SKILL.md" in files:
        return files
    first_parts = {path.split("/", 1)[0] for path in files}
    if len(first_parts) != 1:
        return files
    wrapper = next(iter(first_parts))
    prefix = f"{wrapper}/"
    flattened = {
        path[len(prefix):]: data
        for path, data in files.items()
        if path.startswith(prefix) and path != prefix
    }
    return flattened if "SKILL.md" in flattened else files


def _encoded_bundle_payload(files: dict[str, bytes]) -> dict[str, Any]:
    normalized = _flatten_outer_wrapper(files)
    if len(normalized) > _PUBLIC_SKILL_BUNDLE_MAX_FILES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Too many files in skill bundle.")
    total_bytes = sum(len(data) for data in normalized.values())
    if total_bytes > _PUBLIC_SKILL_BUNDLE_MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Skill bundle is too large.")
    skill_md = normalized.get("SKILL.md")
    if skill_md is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKILL.md is required at the bundle root.")
    try:
        skill_markdown = skill_md.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKILL.md must be UTF-8 text.") from exc
    _validate_skill_markdown(skill_markdown)
    encoded_files = {
        path: {
            "encoding": "base64",
            "size": len(data),
            "data": base64.b64encode(data).decode("ascii"),
        }
        for path, data in sorted(normalized.items())
    }
    return {
        "bundle_files": encoded_files,
        "file_count": len(encoded_files),
        "byte_length": total_bytes,
        "markdown": skill_markdown,
    }


async def _read_skill_bundle_uploads(
    *,
    bundle: UploadFile | None,
    files: list[UploadFile] | None,
) -> dict[str, Any]:
    uploaded_files = files or []
    if bundle is None and not uploaded_files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a skill folder or .zip package.")
    if bundle is not None and uploaded_files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload either a folder or a .zip package, not both.")

    raw_files: dict[str, bytes] = {}
    if bundle is not None:
        name = _safe_bundle_path(bundle.filename or "bundle.zip")
        if not name.lower().endswith(".zip"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill package must be a .zip file.")
        data = await bundle.read()
        if len(data) > _PUBLIC_SKILL_BUNDLE_MAX_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Skill package is too large.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                entries = [info for info in zf.infolist() if not info.is_dir()]
                if len(entries) > _PUBLIC_SKILL_BUNDLE_MAX_FILES:
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Too many files in skill bundle.")
                if sum(info.file_size for info in entries) > _PUBLIC_SKILL_BUNDLE_MAX_BYTES:
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Skill package is too large.")
                for info in entries:
                    path = _safe_bundle_path(info.filename)
                    raw_files[path] = zf.read(info)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid .zip package.") from exc
    else:
        if len(uploaded_files) > _PUBLIC_SKILL_BUNDLE_MAX_FILES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Too many files in skill bundle.")
        total_bytes = 0
        for item in uploaded_files:
            path = _safe_bundle_path(item.filename or "")
            data = await item.read()
            total_bytes += len(data)
            if total_bytes > _PUBLIC_SKILL_BUNDLE_MAX_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Skill bundle is too large.")
            raw_files[path] = data

    return _encoded_bundle_payload(raw_files)


async def _validate_public_skill_slug_available(
    session: DbSession,
    *,
    slug: str,
    agent_id: str,
) -> None:
    existing = await session.scalar(
        select(Submission)
        .where(
            Submission.kind == "proposal",
            Submission.artifact_type == "skill",
            Submission.target_slug == slug,
            Submission.status.in_(OPEN_STATUSES),
        )
        .limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A skill submission with this slug is already open.",
        )
    if skill_markdown_path(slug) is None:
        return

    owner = await session.scalar(
        select(Submission)
        .where(
            Submission.kind == "proposal",
            Submission.artifact_type == "skill",
            Submission.target_slug == slug,
            Submission.status == "published",
        )
        .order_by(Submission.published_at.desc().nullslast(), Submission.updated_at.desc())
        .limit(1)
    )
    if owner is None or owner.submitter_agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Published skill owner is unknown; third-party overwrite is not allowed.",
        )
    if owner.submitter_agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Skill slug belongs to another agent.",
        )


def _validate_public_skill_license(*, license_value: str, license_agreed: bool) -> None:
    if license_value.strip() != "MIT-0":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public skills must use MIT-0.",
        )
    if not license_agreed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MIT-0 license agreement is required.",
        )


def _validate_plugin_request(body: PublicPluginSubmissionRequest) -> None:
    if body.manifest is None and not (body.repository_url or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plugin submissions require either manifest or repository_url.",
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


@public_integration_router.post(
    "/feedback",
    response_model=SubmissionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_public_feedback(
    body: PublicFeedbackRequest,
    request: Request,
    response: Response,
    session: DbSession,
    agent: Optional[Agent] = Depends(optional_agent_auth),
) -> SubmissionCreateResponse:
    ip = _client_ip(request)
    _check_rate_limit(f"public-feedback:{ip}")
    if agent is not None:
        _check_rate_limit(
            f"public-feedback-agent:{agent.agent_id}",
            limit=_PUBLIC_AGENT_RATE_LIMIT,
        )
    source = "partner_feedback" if agent is not None else "public_feedback"
    idempotency_key = _idempotency_key(request)
    if idempotency_key is not None:
        existing = await _load_idempotent_submission(
            session,
            source=source,
            idempotency_key=idempotency_key,
            agent_id=agent.agent_id if agent is not None else None,
            client_ip=ip if agent is None else None,
        )
        if existing is not None:
            return _idempotent_response(response, existing, include_payload=False)

    payload = {
        "page_url": body.page_url,
        "category": body.category,
        "client_ip": ip,
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    _validate_public_payload_size(payload)
    submission = await create_submission(
        session,
        kind="issue",
        source=source,
        title=body.title,
        body=body.body,
        target_path=body.page_url,
        submitter_type="agent" if agent is not None else "human",
        submitter_agent_id=agent.agent_id if agent is not None else None,
        submitter_name=agent.agent_name if agent is not None else body.from_name,
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
        event="public_submission_feedback_created",
        agent_id=agent.agent_id if agent is not None else None,
        submission_id=str(submission.id),
        detail={"source": source, "message_id": message_id},
    )
    return SubmissionCreateResponse(
        id=str(submission.id),
        status=submission.status,
        message="Feedback received and queued for review.",
        submission=submission_to_dict(submission, include_payload=False),
    )


@public_integration_router.post(
    "/skills",
    response_model=SubmissionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_public_skill(
    request: Request,
    response: Response,
    session: DbSession,
    agent: AgentDep,
    slug: str = Form(min_length=1, max_length=120),
    display_name: str = Form(min_length=3, max_length=200),
    version: str = Form(
        min_length=5,
        max_length=40,
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
    ),
    tags: str = Form(default=""),
    summary: str = Form(min_length=10, max_length=20000),
    license_value: str = Form(default="MIT-0", alias="license"),
    license_agreed: bool = Form(default=False),
    bundle: Optional[UploadFile] = File(default=None),
    files: Optional[list[UploadFile]] = File(default=None),
) -> SubmissionCreateResponse:
    _check_rate_limit(f"public-skill:{agent.agent_id}")
    _validate_public_slug(slug)
    _validate_public_skill_license(
        license_value=license_value,
        license_agreed=license_agreed,
    )
    await _validate_public_skill_slug_available(
        session,
        slug=slug,
        agent_id=agent.agent_id,
    )
    submission_intent = "update" if skill_markdown_path(slug) is not None else "create"
    idempotency_key = _idempotency_key(request)
    if idempotency_key is not None:
        existing = await _load_idempotent_submission(
            session,
            source="public_skill_submission",
            idempotency_key=idempotency_key,
            agent_id=agent.agent_id,
        )
        if existing is not None:
            return _idempotent_response(response, existing)

    bundle_payload = await _read_skill_bundle_uploads(bundle=bundle, files=files)
    payload = {
        "license": license_value,
        "license_agreed": license_agreed,
        "display_name": display_name,
        "version": version,
        "tags": [part.strip() for part in tags.split(",") if part.strip()],
        "submission_intent": submission_intent,
        "permissions_requested": [],
        "secrets_required": False,
        "install_instructions": "Install as a Zenheart/OpenClaw skill bundle after sovereign review.",
        **bundle_payload,
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    _validate_artifact_provenance("skill", payload)
    _validate_public_payload_size(payload, max_bytes=_PUBLIC_SKILL_PAYLOAD_MAX_BYTES)
    submission = await create_submission(
        session,
        kind="proposal",
        source="public_skill_submission",
        artifact_type="skill",
        title=display_name,
        body=summary,
        target_slug=slug,
        submitter_type="agent",
        submitter_agent_id=agent.agent_id,
        submitter_name=agent.agent_name,
        payload=payload,
    )
    message_id = await enqueue_submission_review(
        request.app.state.session_factory,
        request.app.state.registry,
        submission=submission,
    )
    await record_submission_event(
        request.app.state.session_factory,
        event="public_submission_skill_created",
        agent_id=agent.agent_id,
        submission_id=str(submission.id),
        detail={"artifact_type": "skill", "message_id": message_id},
    )
    return SubmissionCreateResponse(
        id=str(submission.id),
        status=submission.status,
        message="Skill proposal queued for review.",
        submission=submission_to_dict(submission),
    )


@public_integration_router.post(
    "/plugins",
    response_model=SubmissionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_public_plugin(
    body: PublicPluginSubmissionRequest,
    request: Request,
    response: Response,
    session: DbSession,
    agent: AgentDep,
) -> SubmissionCreateResponse:
    _check_rate_limit(f"public-plugin:{agent.agent_id}")
    _validate_public_slug(body.slug)
    _validate_plugin_request(body)
    idempotency_key = _idempotency_key(request)
    if idempotency_key is not None:
        existing = await _load_idempotent_submission(
            session,
            source="public_plugin_submission",
            idempotency_key=idempotency_key,
            agent_id=agent.agent_id,
        )
        if existing is not None:
            return _idempotent_response(response, existing)

    payload = {
        "license": body.license,
        "permissions_requested": body.permissions_requested,
        "secrets_required": body.secrets_required,
        "install_instructions": body.install_instructions,
        "plugin_kind": body.plugin_kind,
        "manifest": body.manifest,
        "documentation_markdown": body.documentation_markdown,
        "repository_url": body.repository_url,
        "security_notes": body.security_notes,
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    _validate_artifact_provenance("plugin", payload)
    _validate_public_payload_size(payload)
    submission = await create_submission(
        session,
        kind="proposal",
        source="public_plugin_submission",
        artifact_type="plugin",
        title=body.title,
        body=body.summary,
        target_slug=body.slug,
        submitter_type="agent",
        submitter_agent_id=agent.agent_id,
        submitter_name=agent.agent_name,
        payload=payload,
    )
    message_id = await enqueue_submission_review(
        request.app.state.session_factory,
        request.app.state.registry,
        submission=submission,
    )
    await record_submission_event(
        request.app.state.session_factory,
        event="public_submission_plugin_created",
        agent_id=agent.agent_id,
        submission_id=str(submission.id),
        detail={"artifact_type": "plugin", "message_id": message_id},
    )
    return SubmissionCreateResponse(
        id=str(submission.id),
        status=submission.status,
        message="Plugin proposal queued for review.",
        submission=submission_to_dict(submission),
    )


@public_integration_router.get("", response_model=PublicSubmissionFeedResponse)
async def list_public_submissions(
    request: Request,
    session: DbSession,
    status_filter: Optional[str] = Query(default=None, alias="status", max_length=30),
    artifact_type: Optional[str] = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=100),
) -> PublicSubmissionFeedResponse:
    _check_rate_limit(
        f"public-submission-feed:{_client_ip(request)}",
        limit=_PUBLIC_AGENT_RATE_LIMIT,
    )
    query = select(Submission).order_by(Submission.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Submission.status == status_filter)
    if artifact_type:
        query = query.where(Submission.artifact_type == artifact_type)
    rows = list((await session.scalars(query)).all())
    return PublicSubmissionFeedResponse(
        submissions=[_public_submission_feed_row(row) for row in rows],
        count=len(rows),
    )


@public_integration_router.get("/{submission_id}", response_model=SubmissionDetailResponse)
async def get_public_submission(
    submission_id: str,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> SubmissionDetailResponse:
    _check_rate_limit(
        f"public-submission-read:{agent.agent_id}",
        limit=_PUBLIC_AGENT_RATE_LIMIT,
    )
    submission = await load_submission_or_404(session, submission_id)
    if submission.submitter_agent_id != agent.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission belongs to another agent.")
    await record_submission_event(
        request.app.state.session_factory,
        event="public_submission_read",
        agent_id=agent.agent_id,
        submission_id=str(submission.id),
    )
    return await _submission_detail(session, submission)


@public_integration_router.post(
    "/{submission_id}/comments",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
)
async def comment_on_public_submission(
    submission_id: str,
    body: SubmissionCommentRequest,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> dict[str, Any]:
    _check_rate_limit(f"public-submission-comment:{agent.agent_id}")
    submission = await load_submission_or_404(session, submission_id)
    if submission.submitter_agent_id != agent.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission belongs to another agent.")
    if submission.status not in OPEN_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submission is closed.")
    _validate_public_payload_size(body.payload)
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
        event="public_submission_commented",
        agent_id=agent.agent_id,
        submission_id=str(submission.id),
    )
    return {"comment": comment_to_dict(comment)}


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
