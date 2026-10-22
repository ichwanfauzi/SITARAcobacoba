"""Authorized Action Item endpoints."""

from datetime import date, datetime
from typing import Annotated, NoReturn, TypedDict
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_identity, require_csrf
from app.db.session import get_db
from app.models.action_item import (
    ActionItem,
    ActionItemAssignment,
    ActionItemEvidence,
    ActionItemEvidenceKind,
    ActionItemStatus,
    ActionItemStatusHistory,
    CompletionVerification,
    ProgressUpdate,
)
from app.models.auth import User, UserSession
from app.schemas.action_items import (
    ActionItemAssignmentCreate,
    ActionItemAssignmentEnd,
    ActionItemAssignmentResponse,
    ActionItemCreate,
    ActionItemDetailResponse,
    ActionItemEvidenceLinkCreate,
    ActionItemEvidenceResponse,
    ActionItemEvidenceScanStatus,
    ActionItemResponse,
    ActionItemStatusChange,
    ActionItemStatusHistoryResponse,
    CompletionReviewCreate,
    CompletionVerificationResponse,
    ProgressUpdateCreate,
    ProgressUpdateResponse,
)
from app.services.action_item_evidence_storage import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceFileInvalid,
    EvidenceFileTooLarge,
    EvidenceStorageError,
)
from app.services.action_items import (
    ActionItemAssigneeInvalid,
    ActionItemAssignmentConflict,
    ActionItemConcurrencyConflict,
    ActionItemEvidenceDenied,
    ActionItemEvidenceLimitExceeded,
    ActionItemEvidenceQuarantined,
    ActionItemEvidenceStorageNotConfigured,
    ActionItemNotFound,
    ActionItemPermissionDenied,
    ActionItemProgressDenied,
    ActionItemSourceInvalid,
    ActionItemSourceNotActive,
    ActionItemStatusTransitionInvalid,
    ActionItemVerificationInvalid,
    ActionItemVerificationRequired,
    change_action_item_status,
    create_action_item,
    create_assignment,
    create_file_evidence,
    create_link_evidence,
    create_progress_update,
    end_assignment,
    get_action_item_for_actor,
    get_evidence_file_for_actor,
    list_action_item_assignments,
    list_action_items,
    list_completion_verifications,
    list_progress_updates,
    list_status_history,
    review_completion,
    source_revision_is_stale,
)

router = APIRouter(prefix="/action-items", tags=["action-items"])
Identity = tuple[UserSession, User]
CurrentIdentity = Annotated[Identity, Depends(get_current_identity)]
DatabaseSession = Annotated[Session, Depends(get_db)]


class _ActionItemResponseFields(TypedDict):
    id: UUID
    meeting_id: UUID
    source_minutes_revision_id: UUID
    source_decision_id: UUID
    source_revision_is_stale: bool
    title: str
    description: str
    output_expected: str | None
    due_date: date | None
    priority: str
    official_status: ActionItemStatus
    version: int
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    active_assignments: list[ActionItemAssignmentResponse]


def _serialize_assignment(item: ActionItemAssignment) -> ActionItemAssignmentResponse:
    return ActionItemAssignmentResponse(
        id=item.id,
        action_item_id=item.action_item_id,
        assignee_user_id=item.assignee_user_id,
        assigned_by_user_id=item.assigned_by_user_id,
        assignment_role=item.assignment_role,
        started_at=item.started_at,
        ended_at=item.ended_at,
        ended_by_user_id=item.ended_by_user_id,
        assignment_reason=item.assignment_reason,
        end_reason=item.end_reason,
    )


def _serialize_progress_update(item: ProgressUpdate) -> ProgressUpdateResponse:
    return ProgressUpdateResponse(
        id=item.id,
        action_item_id=item.action_item_id,
        assignment_id=item.assignment_id,
        actor_user_id=item.actor_user_id,
        submitted_as=item.submitted_as,
        report_text=item.report_text,
        blocker_text=item.blocker_text,
        progress_percent=item.progress_percent,
        completion_requested=item.completion_requested,
        submitted_at=item.submitted_at,
        evidence=[_serialize_evidence(item.action_item_id, evidence) for evidence in item.evidence],
    )


def _serialize_evidence(
    action_item_id: UUID, item: ActionItemEvidence
) -> ActionItemEvidenceResponse:
    download_url = (
        f"/api/v1/action-items/{action_item_id}/evidence/{item.id}"
        if item.evidence_kind == ActionItemEvidenceKind.FILE
        else None
    )
    return ActionItemEvidenceResponse(
        id=item.id,
        progress_update_id=item.progress_update_id,
        evidence_kind=item.evidence_kind,
        original_filename=item.original_filename,
        content_type=item.content_type,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
        external_url=item.external_url,
        link_label=item.link_label,
        download_url=download_url,
        scan_status=(
            item.scan_events[-1].scan_status
            if item.evidence_kind == ActionItemEvidenceKind.FILE and item.scan_events
            else (
                ActionItemEvidenceScanStatus.PENDING
                if item.evidence_kind == ActionItemEvidenceKind.FILE
                else None
            )
        ),
        uploaded_by_user_id=item.uploaded_by_user_id,
        created_at=item.created_at,
    )


def _serialize_status_history(item: ActionItemStatusHistory) -> ActionItemStatusHistoryResponse:
    return ActionItemStatusHistoryResponse(
        id=item.id,
        event_number=item.event_number,
        old_status=item.old_status,
        new_status=item.new_status,
        changed_by_id=item.changed_by_id,
        verification_id=item.verification_id,
        change_note=item.change_note,
        changed_at=item.changed_at,
    )


def _serialize_verification(item: CompletionVerification) -> CompletionVerificationResponse:
    return CompletionVerificationResponse(
        id=item.id,
        action_item_id=item.action_item_id,
        progress_update_id=item.progress_update_id,
        reviewer_user_id=item.reviewer_user_id,
        outcome=item.outcome,
        review_note=item.review_note,
        reviewed_at=item.reviewed_at,
    )


def _serialize_action_item(
    session: Session, item: ActionItem, *, include_history: bool
) -> ActionItemResponse | ActionItemDetailResponse:
    assignment_history = list_action_item_assignments(session, item.id)
    data: _ActionItemResponseFields = {
        "id": item.id,
        "meeting_id": item.meeting_id,
        "source_minutes_revision_id": item.source_minutes_revision_id,
        "source_decision_id": item.source_decision_id,
        "source_revision_is_stale": source_revision_is_stale(session, item),
        "title": item.title,
        "description": item.description,
        "output_expected": item.output_expected,
        "due_date": item.due_date,
        "priority": item.priority,
        "official_status": item.official_status,
        "version": item.version,
        "created_by_id": item.created_by_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "completed_at": item.completed_at,
        "active_assignments": [
            _serialize_assignment(assignment)
            for assignment in assignment_history
            if assignment.ended_at is None
        ],
    }
    if not include_history:
        return ActionItemResponse(**data)
    return ActionItemDetailResponse(
        **data,
        assignment_history=[_serialize_assignment(assignment) for assignment in assignment_history],
        progress_updates=[
            _serialize_progress_update(update) for update in list_progress_updates(session, item.id)
        ],
        status_history=[
            _serialize_status_history(entry) for entry in list_status_history(session, item.id)
        ],
        completion_verifications=[
            _serialize_verification(entry)
            for entry in list_completion_verifications(session, item.id)
        ],
    )


def _raise_action_item_error(error: Exception) -> NoReturn:
    if isinstance(error, ActionItemNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action Item not found")
    if isinstance(error, ActionItemPermissionDenied):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Action Item access denied"
        )
    if isinstance(error, ActionItemProgressDenied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Progress update denied")
    if isinstance(error, ActionItemEvidenceDenied):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    if isinstance(error, ActionItemEvidenceLimitExceeded):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A progress update can have at most five evidence items",
        )
    if isinstance(error, ActionItemEvidenceStorageNotConfigured):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private evidence storage is not configured",
        )
    if isinstance(error, ActionItemEvidenceQuarantined):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Evidence is quarantined until a trusted scanner approves it",
        )
    if isinstance(error, EvidenceFileTooLarge):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(error))
    if isinstance(error, EvidenceFileInvalid):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(error))
    if isinstance(error, EvidenceStorageError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Private evidence storage operation failed",
        )
    if isinstance(error, ActionItemAssigneeInvalid):
        raise HTTPException(
            status_code=422,
            detail="PIC must be active, eligible, and have an active unit membership",
        )
    if isinstance(error, ActionItemSourceInvalid):
        raise HTTPException(
            status_code=422,
            detail="Source must be an actionable decision from the specified meeting revision",
        )
    if isinstance(error, ActionItemSourceNotActive):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source minutes revision is no longer active",
        )
    if isinstance(error, ActionItemConcurrencyConflict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action Item has changed; reload it before retrying",
        )
    if isinstance(error, ActionItemAssignmentConflict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assignment conflicts with active PIC history or requires a reason",
        )
    if isinstance(error, ActionItemStatusTransitionInvalid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Action Item already has the requested status",
        )
    if isinstance(error, ActionItemVerificationRequired):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SELESAI can only be set while verifying a completion report",
        )
    if isinstance(error, ActionItemVerificationInvalid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Completion report cannot be reviewed in its current state",
        )
    raise error


@router.get("", response_model=list[ActionItemResponse])
def get_action_items(
    identity: CurrentIdentity,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    meeting_id: UUID | None = None,
    official_status: ActionItemStatus | None = None,
) -> list[ActionItemResponse]:
    items = list_action_items(
        session,
        identity[1],
        limit=limit,
        offset=offset,
        meeting_id=meeting_id,
        official_status=official_status,
    )
    return [
        _serialize_action_item(session, item, include_history=False)  # type: ignore[list-item]
        for item in items
    ]


@router.post("", response_model=ActionItemDetailResponse, status_code=status.HTTP_201_CREATED)
def post_action_item(
    data: ActionItemCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ActionItemDetailResponse:
    try:
        item = create_action_item(session, identity[1], data)
    except (
        ActionItemAssigneeInvalid,
        ActionItemPermissionDenied,
        ActionItemSourceInvalid,
        ActionItemSourceNotActive,
    ) as error:
        _raise_action_item_error(error)
    return _serialize_action_item(session, item, include_history=True)  # type: ignore[return-value]


@router.get("/{action_item_id}", response_model=ActionItemDetailResponse)
def get_action_item_detail(
    action_item_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> ActionItemDetailResponse:
    try:
        item = get_action_item_for_actor(session, identity[1], action_item_id)
    except ActionItemNotFound as error:
        _raise_action_item_error(error)
    return _serialize_action_item(session, item, include_history=True)  # type: ignore[return-value]


@router.post(
    "/{action_item_id}/assignments",
    response_model=ActionItemAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_assignment(
    action_item_id: UUID,
    data: ActionItemAssignmentCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ActionItemAssignmentResponse:
    try:
        assignment = create_assignment(
            session, identity[1], action_item_id, data, data.expected_version
        )
    except (
        ActionItemNotFound,
        ActionItemPermissionDenied,
        ActionItemAssigneeInvalid,
        ActionItemAssignmentConflict,
        ActionItemConcurrencyConflict,
    ) as error:
        _raise_action_item_error(error)
    return _serialize_assignment(assignment)


@router.post(
    "/{action_item_id}/assignments/{assignment_id}/end",
    response_model=ActionItemAssignmentResponse,
)
def post_end_assignment(
    action_item_id: UUID,
    assignment_id: UUID,
    data: ActionItemAssignmentEnd,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ActionItemAssignmentResponse:
    try:
        assignment = end_assignment(session, identity[1], action_item_id, assignment_id, data)
    except (
        ActionItemNotFound,
        ActionItemPermissionDenied,
        ActionItemAssignmentConflict,
        ActionItemConcurrencyConflict,
    ) as error:
        _raise_action_item_error(error)
    return _serialize_assignment(assignment)


@router.post(
    "/{action_item_id}/progress-updates",
    response_model=ProgressUpdateResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_progress_update(
    action_item_id: UUID,
    data: ProgressUpdateCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ProgressUpdateResponse:
    try:
        update = create_progress_update(session, identity[1], action_item_id, data)
    except (ActionItemNotFound, ActionItemProgressDenied) as error:
        _raise_action_item_error(error)
    return _serialize_progress_update(update)


@router.post(
    "/{action_item_id}/progress-updates/{progress_update_id}/evidence/files",
    response_model=ActionItemEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_progress_evidence_file(
    action_item_id: UUID,
    progress_update_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
    file: Annotated[UploadFile, File()],
) -> ActionItemEvidenceResponse:
    if file.size is not None and file.size > MAX_EVIDENCE_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Evidence file exceeds the 10 MiB limit",
        )
    content = file.file.read(MAX_EVIDENCE_FILE_BYTES + 1)
    try:
        evidence = create_file_evidence(
            session,
            identity[1],
            action_item_id,
            progress_update_id,
            file.filename or "",
            content,
        )
    except (
        ActionItemNotFound,
        ActionItemEvidenceDenied,
        ActionItemEvidenceLimitExceeded,
        ActionItemEvidenceStorageNotConfigured,
        EvidenceFileInvalid,
        EvidenceFileTooLarge,
        EvidenceStorageError,
    ) as error:
        _raise_action_item_error(error)
    return _serialize_evidence(action_item_id, evidence)


@router.post(
    "/{action_item_id}/progress-updates/{progress_update_id}/evidence/links",
    response_model=ActionItemEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_progress_evidence_link(
    action_item_id: UUID,
    progress_update_id: UUID,
    data: ActionItemEvidenceLinkCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ActionItemEvidenceResponse:
    try:
        evidence = create_link_evidence(
            session, identity[1], action_item_id, progress_update_id, data
        )
    except (
        ActionItemNotFound,
        ActionItemEvidenceDenied,
        ActionItemEvidenceLimitExceeded,
    ) as error:
        _raise_action_item_error(error)
    return _serialize_evidence(action_item_id, evidence)


@router.get("/{action_item_id}/evidence/{evidence_id}")
def get_progress_evidence_file(
    action_item_id: UUID,
    evidence_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> Response:
    try:
        evidence, content = get_evidence_file_for_actor(
            session, identity[1], action_item_id, evidence_id
        )
    except (
        ActionItemNotFound,
        ActionItemEvidenceStorageNotConfigured,
        ActionItemEvidenceQuarantined,
        EvidenceStorageError,
    ) as error:
        _raise_action_item_error(error)
    filename = evidence.original_filename
    content_type = evidence.content_type
    if filename is None or content_type is None:
        _raise_action_item_error(EvidenceStorageError("Evidence metadata is invalid"))
    encoded_filename = quote(filename)
    content_disposition = (
        f"attachment; filename*=utf-8''{encoded_filename}"
        if encoded_filename != filename
        else f'attachment; filename="{filename}"'
    )
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": content_disposition,
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/{action_item_id}/status", response_model=ActionItemResponse)
def patch_action_item_status(
    action_item_id: UUID,
    data: ActionItemStatusChange,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ActionItemResponse:
    try:
        item = change_action_item_status(session, identity[1], action_item_id, data)
    except (
        ActionItemNotFound,
        ActionItemPermissionDenied,
        ActionItemConcurrencyConflict,
        ActionItemStatusTransitionInvalid,
        ActionItemVerificationRequired,
    ) as error:
        _raise_action_item_error(error)
    return _serialize_action_item(session, item, include_history=False)  # type: ignore[return-value]


@router.post(
    "/{action_item_id}/completion-verifications",
    response_model=ActionItemDetailResponse,
)
def post_completion_verification(
    action_item_id: UUID,
    data: CompletionReviewCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ActionItemDetailResponse:
    try:
        item, _ = review_completion(session, identity[1], action_item_id, data)
    except (
        ActionItemNotFound,
        ActionItemPermissionDenied,
        ActionItemConcurrencyConflict,
        ActionItemVerificationInvalid,
    ) as error:
        _raise_action_item_error(error)
    return _serialize_action_item(session, item, include_history=True)  # type: ignore[return-value]
