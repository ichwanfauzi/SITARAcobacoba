"""Rapim metadata and agenda endpoints with role and object authorization."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_identity, require_csrf
from app.db.session import get_db
from app.models.auth import User, UserSession
from app.models.meeting import (
    Agenda,
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    MinutesReview,
    MinutesRevision,
)
from app.schemas.meetings import (
    AgendaCreate,
    AgendaResponse,
    MeetingCreate,
    MeetingParticipantCreate,
    MeetingParticipantResponse,
    MeetingResponse,
    MeetingTransitionRequest,
    MinutesReviewCreate,
    MinutesReviewResponse,
    MinutesRevisionCreate,
    MinutesRevisionResponse,
)
from app.services.meetings import (
    DuplicateMeetingRecord,
    InvalidMeetingReference,
    InvalidMeetingTransition,
    MeetingNotLiveForMinutesReview,
    MeetingNotLiveForMinutesRevision,
    MinutesReviewRequired,
    MinutesRevisionConflict,
    MinutesRevisionEditDenied,
    add_meeting_participant,
    can_edit_minutes,
    can_manage_meeting,
    can_read_meeting,
    can_read_meetings,
    can_read_minutes,
    can_review_meeting_minutes,
    can_transition_meeting,
    create_agenda,
    create_meeting,
    create_minutes_revision,
    get_meeting,
    list_meetings,
    list_minutes_reviews,
    list_minutes_revisions,
    record_minutes_review,
    transition_meeting,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])
Identity = tuple[UserSession, User]
CurrentIdentity = Annotated[Identity, Depends(get_current_identity)]
DatabaseSession = Annotated[Session, Depends(get_db)]


def _serialize_agenda(agenda: Agenda) -> AgendaResponse:
    return AgendaResponse(
        id=agenda.id,
        meeting_id=agenda.meeting_id,
        agenda_number=agenda.agenda_number,
        title=agenda.title,
        agenda_description=agenda.agenda_description,
        lead_user_id=agenda.lead_user_id,
        duration_minutes=agenda.duration_minutes,
        sort_order=agenda.sort_order,
    )


def _serialize_participant(participant: MeetingParticipant) -> MeetingParticipantResponse:
    return MeetingParticipantResponse(
        user_id=participant.user_id,
        participant_name=participant.user.full_name,
        attendance_status=participant.attendance_status,
        participant_title=participant.participant_title,
    )


def _serialize_meeting(meeting: Meeting) -> MeetingResponse:
    return MeetingResponse(
        id=meeting.id,
        meeting_number=meeting.meeting_number,
        title=meeting.title,
        meeting_type=meeting.meeting_type,
        meeting_date=meeting.meeting_date,
        start_time=meeting.start_time,
        end_time=meeting.end_time,
        location=meeting.location,
        chairperson_id=meeting.chairperson_id,
        notetaker_id=meeting.notetaker_id,
        created_by_id=meeting.created_by_id,
        status=meeting.status,
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
        agendas=[_serialize_agenda(agenda) for agenda in meeting.agendas],
        participants=[_serialize_participant(item) for item in meeting.participants],
    )


def _serialize_minutes_review(review: MinutesReview) -> MinutesReviewResponse:
    return MinutesReviewResponse(
        id=review.id,
        meeting_id=review.meeting_id,
        minutes_revision_id=review.minutes_revision_id,
        reviewer_user_id=review.reviewer_user_id,
        review_number=review.review_number,
        result=review.result,
        review_note=review.review_note,
        reviewed_at=review.reviewed_at,
    )


def _serialize_minutes_revision(revision: MinutesRevision) -> MinutesRevisionResponse:
    return MinutesRevisionResponse(
        id=revision.id,
        meeting_id=revision.meeting_id,
        revision_number=revision.revision_number,
        content=revision.content,
        created_by_id=revision.created_by_id,
        created_at=revision.created_at,
    )


def _require_manager(user: User) -> None:
    if not can_read_meetings(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Meeting access denied")


def _load_visible_meeting(session: Session, meeting_id: UUID, user: User) -> Meeting:
    meeting = get_meeting(session, meeting_id)
    if meeting is None or not can_read_meeting(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting


def _require_editable_draft(meeting: Meeting, user: User) -> None:
    if not can_manage_meeting(user, meeting):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Meeting update denied")
    if meeting.status is not MeetingStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft meetings can be changed",
        )


def _raise_create_error(error: Exception) -> None:
    if isinstance(error, DuplicateMeetingRecord):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Meeting number, agenda number, or participant already exists",
        ) from error
    if isinstance(error, InvalidMeetingReference):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Referenced user is missing or inactive",
        ) from error
    raise error


@router.get("", response_model=list[MeetingResponse])
def get_meetings(
    identity: CurrentIdentity,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MeetingResponse]:
    user = identity[1]
    _require_manager(user)
    return [
        _serialize_meeting(meeting)
        for meeting in list_meetings(session, user, limit=limit, offset=offset)
    ]


@router.post("", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
def post_meeting(
    data: MeetingCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingResponse:
    user = identity[1]
    _require_manager(user)
    try:
        meeting = create_meeting(session, user, data)
    except (DuplicateMeetingRecord, InvalidMeetingReference) as error:
        _raise_create_error(error)
    return _serialize_meeting(meeting)


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting_detail(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> MeetingResponse:
    meeting = _load_visible_meeting(session, meeting_id, identity[1])
    return _serialize_meeting(meeting)


@router.post(
    "/{meeting_id}/agendas",
    response_model=AgendaResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_agenda(
    meeting_id: UUID,
    data: AgendaCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> AgendaResponse:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    _require_editable_draft(meeting, user)
    try:
        agenda = create_agenda(session, meeting, data)
    except (DuplicateMeetingRecord, InvalidMeetingReference) as error:
        _raise_create_error(error)
    return _serialize_agenda(agenda)


@router.post(
    "/{meeting_id}/participants",
    response_model=MeetingParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_participant(
    meeting_id: UUID,
    data: MeetingParticipantCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingParticipantResponse:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    _require_editable_draft(meeting, user)
    try:
        participant = add_meeting_participant(session, meeting, data)
    except (DuplicateMeetingRecord, InvalidMeetingReference) as error:
        _raise_create_error(error)
    return _serialize_participant(participant)


@router.post("/{meeting_id}/transition", response_model=MeetingResponse)
def post_meeting_transition(
    meeting_id: UUID,
    data: MeetingTransitionRequest,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    if not can_transition_meeting(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Meeting transition denied"
        )
    try:
        meeting = transition_meeting(session, meeting_id, user, data.to_status)
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except MinutesReviewRequired as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Meeting cannot be finalized until the active minutes revision "
                "has a valid minutes review"
            ),
        ) from error
    except InvalidMeetingTransition as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Meeting status transition is not allowed",
        ) from error
    return _serialize_meeting(meeting)


@router.post(
    "/{meeting_id}/minutes-reviews",
    response_model=MinutesReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_minutes_review(
    meeting_id: UUID,
    data: MinutesReviewCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MinutesReviewResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    if not can_review_meeting_minutes(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Minutes review denied")
    try:
        review = record_minutes_review(session, meeting_id, user, data)
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except MeetingNotLiveForMinutesReview as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes can only be reviewed while the meeting is LIVE",
        ) from error
    except MinutesRevisionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes review must reference the active revision",
        ) from error
    return _serialize_minutes_review(review)


@router.get("/{meeting_id}/minutes-reviews", response_model=list[MinutesReviewResponse])
def get_minutes_reviews(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> list[MinutesReviewResponse]:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    if not can_review_meeting_minutes(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Minutes review access denied"
        )
    return [
        _serialize_minutes_review(review) for review in list_minutes_reviews(session, meeting_id)
    ]


@router.post(
    "/{meeting_id}/minutes-revisions",
    response_model=MinutesRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_minutes_revision(
    meeting_id: UUID,
    data: MinutesRevisionCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MinutesRevisionResponse:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    if not can_read_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    if not can_edit_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Minutes edit denied")
    try:
        revision = create_minutes_revision(session, meeting_id, user, data)
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except MinutesRevisionEditDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Minutes edit denied"
        ) from error
    except MeetingNotLiveForMinutesRevision as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes can only be edited while the meeting is LIVE",
        ) from error
    except MinutesRevisionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes changed since the supplied base revision",
        ) from error
    return _serialize_minutes_revision(revision)


@router.get("/{meeting_id}/minutes-revisions", response_model=list[MinutesRevisionResponse])
def get_minutes_revisions(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> list[MinutesRevisionResponse]:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    if not can_read_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return [
        _serialize_minutes_revision(revision)
        for revision in list_minutes_revisions(session, meeting_id)
    ]
