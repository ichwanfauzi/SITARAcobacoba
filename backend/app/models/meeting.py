"""Rapim meetings, agendas, and participants."""

from datetime import date, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.auth import User


class MeetingStatus(StrEnum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    FINAL = "FINAL"
    ARCHIVED = "ARCHIVED"


class MinutesReviewResult(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


MEETING_STATUS_TYPE = SqlEnum(
    MeetingStatus,
    name="meeting_status",
    native_enum=False,
    create_constraint=False,
    values_callable=lambda enum_values: [value.value for value in enum_values],
    length=20,
)


MINUTES_REVIEW_RESULT_TYPE = SqlEnum(
    MinutesReviewResult,
    name="minutes_review_result",
    native_enum=False,
    create_constraint=False,
    values_callable=lambda enum_values: [value.value for value in enum_values],
    length=20,
)


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_meetings_title_not_blank"),
        CheckConstraint(
            "end_time IS NULL OR start_time IS NULL OR end_time >= start_time",
            name="ck_meetings_time_order",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'LIVE', 'FINAL', 'ARCHIVED')",
            name="ck_meetings_status",
        ),
        CheckConstraint(
            "status NOT IN ('FINAL', 'ARCHIVED') OR "
            "(finalized_at IS NOT NULL AND finalized_by_id IS NOT NULL)",
            name="ck_meetings_finalized_fields",
        ),
        Index("ix_meetings_date_status", "meeting_date", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_number: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(100), default="RAPIM", nullable=False)
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    location: Mapped[str | None] = mapped_column(String(300))
    chairperson_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    notetaker_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[MeetingStatus] = mapped_column(
        MEETING_STATUS_TYPE,
        default=MeetingStatus.DRAFT,
        server_default=MeetingStatus.DRAFT.value,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    creator: Mapped["User"] = relationship(
        back_populates="meetings_created", foreign_keys=[created_by_id]
    )
    chairperson: Mapped["User | None"] = relationship(
        back_populates="meetings_chairperson", foreign_keys=[chairperson_id]
    )
    notetaker: Mapped["User | None"] = relationship(
        back_populates="meetings_notetaker", foreign_keys=[notetaker_id]
    )
    finalized_by: Mapped["User | None"] = relationship(foreign_keys=[finalized_by_id])
    agendas: Mapped[list["Agenda"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="Agenda.sort_order"
    )
    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    minutes_reviews: Mapped[list["MinutesReview"]] = relationship(
        back_populates="meeting", order_by="MinutesReview.review_number"
    )
    minutes_revisions: Mapped[list["MinutesRevision"]] = relationship(
        back_populates="meeting", order_by="MinutesRevision.revision_number"
    )


class MeetingStatusEvent(Base):
    """Append-only record of an authorized meeting lifecycle transition."""

    __tablename__ = "meeting_status_events"
    __table_args__ = (
        CheckConstraint(
            "(from_status = 'DRAFT' AND to_status = 'LIVE') OR "
            "(from_status = 'LIVE' AND to_status = 'FINAL') OR "
            "(from_status = 'FINAL' AND to_status = 'ARCHIVED')",
            name="ck_meeting_status_events_transition",
        ),
        Index("ix_meeting_status_events_meeting_time", "meeting_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("meetings.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class MinutesRevision(Base):
    """Append-only text or agenda-structured snapshots of meeting minutes."""

    __tablename__ = "minutes_revisions"
    __table_args__ = (
        CheckConstraint("revision_number > 0", name="ck_minutes_revisions_number_positive"),
        CheckConstraint("format_version IN (1, 2)", name="ck_minutes_revisions_format_version"),
        CheckConstraint(
            "(format_version = 1 AND content IS NOT NULL AND length(trim(content)) > 0 "
            "AND length(content) <= 1000000) OR "
            "(format_version = 2 AND content IS NULL)",
            name="ck_minutes_revisions_content_by_format",
        ),
        UniqueConstraint(
            "meeting_id", "revision_number", name="uq_minutes_revisions_meeting_number"
        ),
        UniqueConstraint("meeting_id", "id", name="uq_minutes_revisions_meeting_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("meetings.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    format_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    meeting: Mapped[Meeting] = relationship(back_populates="minutes_revisions")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by_id])


class MinutesDiscussion(Base):
    """Immutable discussion text scoped to an agenda and one revision snapshot."""

    __tablename__ = "minutes_discussions"
    __table_args__ = (
        CheckConstraint("discussion_number > 0", name="ck_minutes_discussions_number_positive"),
        CheckConstraint(
            "length(trim(content)) > 0 AND length(content) <= 100000",
            name="ck_minutes_discussions_content",
        ),
        ForeignKeyConstraint(
            ["meeting_id", "minutes_revision_id"],
            ["minutes_revisions.meeting_id", "minutes_revisions.id"],
            name="fk_minutes_discussions_revision_same_meeting",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["meeting_id", "agenda_id"],
            ["agendas.meeting_id", "agendas.id"],
            name="fk_minutes_discussions_agenda_same_meeting",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "minutes_revision_id",
            "agenda_id",
            "discussion_number",
            name="uq_minutes_discussions_revision_agenda_number",
        ),
        UniqueConstraint(
            "meeting_id",
            "minutes_revision_id",
            "id",
            name="uq_minutes_discussions_revision_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    minutes_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agenda_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    discussion_number: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)


class MinutesDecision(Base):
    """Immutable decision text belonging to one discussion in one revision."""

    __tablename__ = "minutes_decisions"
    __table_args__ = (
        CheckConstraint("decision_number > 0", name="ck_minutes_decisions_number_positive"),
        CheckConstraint(
            "length(trim(decision_text)) > 0 AND length(decision_text) <= 20000",
            name="ck_minutes_decisions_text",
        ),
        CheckConstraint(
            "output_expected IS NULL OR length(output_expected) <= 20000",
            name="ck_minutes_decisions_output_expected",
        ),
        ForeignKeyConstraint(
            ["meeting_id", "minutes_revision_id", "discussion_id"],
            [
                "minutes_discussions.meeting_id",
                "minutes_discussions.minutes_revision_id",
                "minutes_discussions.id",
            ],
            name="fk_minutes_decisions_discussion_same_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "minutes_revision_id",
            "discussion_id",
            "decision_number",
            name="uq_minutes_decisions_discussion_number",
        ),
        UniqueConstraint(
            "meeting_id",
            "minutes_revision_id",
            "id",
            name="uq_minutes_decisions_revision_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    minutes_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    discussion_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_expected: Mapped[str | None] = mapped_column(Text)
    target_date: Mapped[date | None] = mapped_column(Date)
    is_action_item: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )


class DecisionBriefVersion(Base):
    """Immutable editorial brief snapshot tied to one exact minutes revision."""

    __tablename__ = "decision_brief_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_decision_brief_versions_number_positive"),
        CheckConstraint(
            "length(trim(summary)) > 0 AND length(summary) <= 100000",
            name="ck_decision_brief_versions_summary",
        ),
        CheckConstraint(
            "notes IS NULL OR length(notes) <= 20000",
            name="ck_decision_brief_versions_notes",
        ),
        ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id"],
            ["minutes_revisions.meeting_id", "minutes_revisions.id"],
            name="fk_decision_brief_versions_source_revision_same_meeting",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "meeting_id", "version_number", name="uq_decision_brief_versions_meeting_number"
        ),
        UniqueConstraint(
            "meeting_id",
            "id",
            "source_minutes_revision_id",
            name="uq_decision_brief_versions_meeting_id_source",
        ),
        Index("ix_decision_brief_versions_meeting_created", "meeting_id", "version_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_minutes_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "users.id",
            name="fk_decision_brief_versions_created_by_id_users",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class DecisionBriefDecision(Base):
    """Editorial framing for a source decision without copying its authoritative text."""

    __tablename__ = "decision_brief_decisions"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_decision_brief_decisions_position_positive"),
        CheckConstraint(
            "length(trim(priority)) > 0 AND length(priority) <= 100",
            name="ck_decision_brief_decisions_priority",
        ),
        CheckConstraint(
            "editorial_note IS NULL OR length(editorial_note) <= 4000",
            name="ck_decision_brief_decisions_editorial_note",
        ),
        ForeignKeyConstraint(
            ["meeting_id", "brief_version_id", "source_minutes_revision_id"],
            [
                "decision_brief_versions.meeting_id",
                "decision_brief_versions.id",
                "decision_brief_versions.source_minutes_revision_id",
            ],
            name="fk_decision_brief_decisions_version_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id", "source_decision_id"],
            [
                "minutes_decisions.meeting_id",
                "minutes_decisions.minutes_revision_id",
                "minutes_decisions.id",
            ],
            name="fk_decision_brief_decisions_exact_source_decision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "brief_version_id", "position", name="uq_decision_brief_decisions_position"
        ),
    )

    brief_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    meeting_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_minutes_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[str] = mapped_column(String(100), nullable=False)
    editorial_note: Mapped[str | None] = mapped_column(Text)


class MinutesReview(Base):
    """Attributable Secretariat review attestations for one exact minutes revision."""

    __tablename__ = "minutes_reviews"
    __table_args__ = (
        CheckConstraint("review_number > 0", name="ck_minutes_reviews_number_positive"),
        CheckConstraint("result IN ('VALID', 'INVALID')", name="ck_minutes_reviews_result"),
        ForeignKeyConstraint(
            ["meeting_id", "minutes_revision_id"],
            ["minutes_revisions.meeting_id", "minutes_revisions.id"],
            name="fk_minutes_reviews_revision_same_meeting",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("meeting_id", "review_number", name="uq_minutes_reviews_meeting_number"),
        Index("ix_minutes_reviews_revision", "meeting_id", "minutes_revision_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("meetings.id", ondelete="RESTRICT"), nullable=False
    )
    minutes_revision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewer_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    review_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[MinutesReviewResult] = mapped_column(MINUTES_REVIEW_RESULT_TYPE, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    meeting: Mapped[Meeting] = relationship(back_populates="minutes_reviews")
    minutes_revision: Mapped[MinutesRevision | None] = relationship(
        foreign_keys=[minutes_revision_id],
        primaryjoin="MinutesReview.minutes_revision_id == MinutesRevision.id",
    )


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"
    __table_args__ = (
        CheckConstraint(
            "attendance_status IN ('INVITED', 'PRESENT', 'ABSENT', 'EXCUSED')",
            name="ck_meeting_participant_attendance_status",
        ),
    )

    meeting_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    attendance_status: Mapped[str] = mapped_column(
        String(20), default="INVITED", server_default="INVITED", nullable=False
    )
    participant_title: Mapped[str | None] = mapped_column(String(200))

    meeting: Mapped[Meeting] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship(back_populates="meeting_participations")


class Agenda(Base):
    __tablename__ = "agendas"
    __table_args__ = (
        CheckConstraint("agenda_number > 0", name="ck_agendas_number_positive"),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_agendas_duration_positive",
        ),
        UniqueConstraint("meeting_id", "agenda_number", name="uq_agendas_meeting_number"),
        UniqueConstraint("meeting_id", "id", name="uq_agendas_meeting_id"),
        Index("ix_agendas_meeting_sort", "meeting_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    agenda_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    agenda_description: Mapped[str | None] = mapped_column(Text)
    lead_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    meeting: Mapped[Meeting] = relationship(back_populates="agendas")
    lead_user: Mapped["User | None"] = relationship(back_populates="led_agendas")
