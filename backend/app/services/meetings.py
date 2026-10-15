"""Meeting access policies and database use cases."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models.auth import User
from app.models.meeting import (
    Agenda,
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    MeetingStatusEvent,
    MinutesReview,
    MinutesReviewResult,
    MinutesRevision,
)
from app.schemas.meetings import (
    AgendaCreate,
    MeetingCreate,
    MeetingParticipantCreate,
    MinutesReviewCreate,
    MinutesRevisionCreate,
)

MEETING_MANAGER_ROLES = frozenset({"SEKRETARIAT", "REKTOR", "WAREK"})
MEETING_LEADER_ROLES = frozenset({"REKTOR", "WAREK"})
SUPER_ADMIN_ROLE = "SUPER_ADMIN"


class DuplicateMeetingRecord(Exception):
    """Raised when a unique meeting, agenda, or participant record conflicts."""


class InvalidMeetingReference(Exception):
    """Raised when a meeting references a missing or inactive user."""


class InvalidMeetingTransition(Exception):
    """Raised when the requested status transition is not permitted."""


class MinutesReviewRequired(Exception):
    """Raised when the latest minutes review is missing or invalid."""


class MeetingNotLiveForMinutesReview(Exception):
    """Raised when minutes are submitted for review outside the live state."""


class MeetingNotLiveForMinutesRevision(Exception):
    """Raised when minutes are edited outside the live state."""


class MinutesRevisionConflict(Exception):
    """Raised when a minutes write is based on a revision that is no longer active."""


class MinutesRevisionEditDenied(Exception):
    """Raised when a user is not the eligible designated notetaker."""


def user_role_codes(user: User) -> set[str]:
    return {role.role_code for role in user.roles}


def can_read_meetings(user: User) -> bool:
    roles = user_role_codes(user)
    return SUPER_ADMIN_ROLE not in roles and bool(roles & MEETING_MANAGER_ROLES)


def can_read_meeting(user: User, meeting: Meeting) -> bool:
    roles = user_role_codes(user)
    if SUPER_ADMIN_ROLE in roles:
        return False
    if "SEKRETARIAT" in roles:
        return True
    if not roles & MEETING_LEADER_ROLES:
        return False
    return user.id in {
        meeting.created_by_id,
        meeting.chairperson_id,
        meeting.notetaker_id,
    } or any(participant.user_id == user.id for participant in meeting.participants)


def can_manage_meeting(user: User, meeting: Meeting) -> bool:
    roles = user_role_codes(user)
    if SUPER_ADMIN_ROLE in roles:
        return False
    return "SEKRETARIAT" in roles or (
        bool(roles & MEETING_LEADER_ROLES) and meeting.created_by_id == user.id
    )


def can_transition_meeting(user: User) -> bool:
    roles = user_role_codes(user)
    return SUPER_ADMIN_ROLE not in roles and "SEKRETARIAT" in roles


def can_review_meeting_minutes(user: User) -> bool:
    """Only an operational Secretariat user may record a minutes review."""
    roles = user_role_codes(user)
    return SUPER_ADMIN_ROLE not in roles and "SEKRETARIAT" in roles


def can_read_minutes(user: User, meeting: Meeting) -> bool:
    """PIC and Super Admin never receive full restricted minutes content."""
    roles = user_role_codes(user)
    if roles & {SUPER_ADMIN_ROLE, "PIC"}:
        return False
    return can_read_meeting(user, meeting)


def can_edit_minutes(user: User, meeting: Meeting) -> bool:
    """Only the designated notetaker may append minutes revisions during a live meeting."""
    return meeting.notetaker_id == user.id and can_read_minutes(user, meeting)


def list_meetings(session: Session, user: User, limit: int, offset: int) -> list[Meeting]:
    statement = select(Meeting).options(
        selectinload(Meeting.agendas),
        selectinload(Meeting.participants).selectinload(MeetingParticipant.user),
    )
    roles = user_role_codes(user)
    if "SEKRETARIAT" not in roles:
        statement = statement.where(
            or_(
                Meeting.created_by_id == user.id,
                Meeting.chairperson_id == user.id,
                Meeting.notetaker_id == user.id,
                Meeting.participants.any(MeetingParticipant.user_id == user.id),
            )
        )
    statement = statement.order_by(Meeting.meeting_date.desc(), Meeting.meeting_number)
    statement = statement.offset(offset).limit(limit)
    return list(session.scalars(statement).unique().all())


def get_meeting(session: Session, meeting_id: UUID) -> Meeting | None:
    statement = (
        select(Meeting)
        .options(
            selectinload(Meeting.agendas),
            selectinload(Meeting.participants).selectinload(MeetingParticipant.user),
        )
        .where(Meeting.id == meeting_id)
    )
    return session.scalar(statement)


def _require_active_users(session: Session, user_ids: set[UUID]) -> None:
    if not user_ids:
        return
    active_ids = set(
        session.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True)))
    )
    if active_ids != user_ids:
        raise InvalidMeetingReference


def create_meeting(session: Session, creator: User, data: MeetingCreate) -> Meeting:
    referenced_users = {
        user_id for user_id in (data.chairperson_id, data.notetaker_id) if user_id is not None
    }
    _require_active_users(session, referenced_users)
    meeting = Meeting(
        meeting_number=data.meeting_number,
        title=data.title,
        meeting_type=data.meeting_type,
        meeting_date=data.meeting_date,
        start_time=data.start_time,
        end_time=data.end_time,
        location=data.location,
        chairperson_id=data.chairperson_id,
        notetaker_id=data.notetaker_id,
        created_by_id=creator.id,
        status=MeetingStatus.DRAFT,
    )
    session.add(meeting)
    _commit_or_raise_duplicate(session)
    return get_meeting(session, meeting.id)  # type: ignore[return-value]


def create_agenda(session: Session, meeting: Meeting, data: AgendaCreate) -> Agenda:
    if data.lead_user_id is not None:
        _require_active_users(session, {data.lead_user_id})
    agenda = Agenda(
        meeting_id=meeting.id,
        agenda_number=data.agenda_number,
        title=data.title,
        agenda_description=data.agenda_description,
        lead_user_id=data.lead_user_id,
        duration_minutes=data.duration_minutes,
        sort_order=data.sort_order,
    )
    session.add(agenda)
    _commit_or_raise_duplicate(session)
    return agenda


def add_meeting_participant(
    session: Session, meeting: Meeting, data: MeetingParticipantCreate
) -> MeetingParticipant:
    _require_active_users(session, {data.user_id})
    if session.get(MeetingParticipant, (meeting.id, data.user_id)) is not None:
        raise DuplicateMeetingRecord
    participant = MeetingParticipant(
        meeting_id=meeting.id,
        user_id=data.user_id,
        participant_title=data.participant_title,
    )
    meeting.participants.append(participant)
    session.add(participant)
    _commit_or_raise_duplicate(session)
    session.refresh(participant)
    return participant


def create_minutes_revision(
    session: Session,
    meeting_id: UUID,
    author: User,
    data: MinutesRevisionCreate,
) -> MinutesRevision:
    """Append a revision using a locked meeting row and an optimistic base revision."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if not can_edit_minutes(author, meeting):
        session.rollback()
        raise MinutesRevisionEditDenied
    if meeting.status is not MeetingStatus.LIVE:
        session.rollback()
        raise MeetingNotLiveForMinutesRevision

    latest_revision = _latest_minutes_revision(session, meeting_id)
    latest_id = latest_revision.id if latest_revision is not None else None
    if data.base_revision_id != latest_id:
        session.rollback()
        raise MinutesRevisionConflict

    revision = MinutesRevision(
        meeting_id=meeting_id,
        revision_number=(latest_revision.revision_number if latest_revision else 0) + 1,
        content=data.content,
        created_by_id=author.id,
        created_at=datetime.now(UTC),
    )
    session.add(revision)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(revision)
    return revision


def list_minutes_revisions(session: Session, meeting_id: UUID) -> list[MinutesRevision]:
    """Return immutable snapshots in their per-meeting revision order."""
    statement = (
        select(MinutesRevision)
        .where(MinutesRevision.meeting_id == meeting_id)
        .order_by(MinutesRevision.revision_number)
    )
    return list(session.scalars(statement).all())


def record_minutes_review(
    session: Session,
    meeting_id: UUID,
    reviewer: User,
    data: MinutesReviewCreate,
) -> MinutesReview:
    """Record a review attestation, serialized with the meeting lifecycle."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if meeting.status is not MeetingStatus.LIVE:
        session.rollback()
        raise MeetingNotLiveForMinutesReview

    latest_revision = _latest_minutes_revision(session, meeting_id)
    if latest_revision is None or data.minutes_revision_id != latest_revision.id:
        session.rollback()
        raise MinutesRevisionConflict

    previous_number = session.scalar(
        select(func.coalesce(func.max(MinutesReview.review_number), 0)).where(
            MinutesReview.meeting_id == meeting_id
        )
    )
    review = MinutesReview(
        meeting_id=meeting_id,
        reviewer_user_id=reviewer.id,
        minutes_revision_id=latest_revision.id,
        review_number=(previous_number or 0) + 1,
        result=data.result,
        review_note=data.review_note,
        reviewed_at=datetime.now(UTC),
    )
    session.add(review)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(review)
    return review


def list_minutes_reviews(session: Session, meeting_id: UUID) -> list[MinutesReview]:
    """Return the ordered review history for an already-authorized meeting."""
    statement = (
        select(MinutesReview)
        .where(MinutesReview.meeting_id == meeting_id)
        .order_by(MinutesReview.review_number)
    )
    return list(session.scalars(statement).all())


def transition_meeting(
    session: Session,
    meeting_id: UUID,
    actor: User,
    to_status: MeetingStatus,
) -> Meeting:
    """Apply one allowed transition and write its audit event in the same transaction."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference

    from_status = meeting.status
    if from_status is to_status:
        session.rollback()
        raise InvalidMeetingTransition

    if from_status is MeetingStatus.DRAFT and to_status is MeetingStatus.LIVE:
        meeting.started_at = datetime.now(UTC)
    elif from_status is MeetingStatus.LIVE and to_status is MeetingStatus.FINAL:
        latest_revision = _latest_minutes_revision(session, meeting_id)
        latest_review = session.scalar(
            select(MinutesReview)
            .where(MinutesReview.meeting_id == meeting_id)
            .order_by(MinutesReview.review_number.desc())
            .limit(1)
        )
        if (
            latest_revision is None
            or latest_review is None
            or latest_review.result is not MinutesReviewResult.VALID
            or latest_review.minutes_revision_id != latest_revision.id
        ):
            session.rollback()
            raise MinutesReviewRequired
        meeting.finalized_at = datetime.now(UTC)
        meeting.finalized_by_id = actor.id
    elif from_status is MeetingStatus.FINAL and to_status is MeetingStatus.ARCHIVED:
        pass
    else:
        session.rollback()
        raise InvalidMeetingTransition

    meeting.status = to_status
    session.add(
        MeetingStatusEvent(
            meeting_id=meeting.id,
            actor_user_id=actor.id,
            from_status=from_status.value,
            to_status=to_status.value,
        )
    )
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    return get_meeting(session, meeting_id)  # type: ignore[return-value]


def _commit_or_raise_duplicate(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicateMeetingRecord from error


def _latest_minutes_revision(session: Session, meeting_id: UUID) -> MinutesRevision | None:
    return session.scalar(
        select(MinutesRevision)
        .where(MinutesRevision.meeting_id == meeting_id)
        .order_by(MinutesRevision.revision_number.desc())
        .limit(1)
    )
