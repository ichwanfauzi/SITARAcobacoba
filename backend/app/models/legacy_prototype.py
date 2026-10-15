"""Reference mapping of the legacy SITARA prototype domain.

These models preserve the old prototype concepts for migration planning. They are
not registered in application startup and are not a production schema. Before use,
reconcile them with docs/sitara_schema_v1_draft.sql and create Alembic migrations.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class LegacyBase(DeclarativeBase):
    """Isolated metadata for the legacy prototype mapping."""


class User(LegacyBase):
    __tablename__ = "legacy_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="secretariat", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    meetings: Mapped[list["Meeting"]] = relationship(back_populates="creator")
    notes: Mapped[list["MeetingNote"]] = relationship(back_populates="author")


class Meeting(LegacyBase):
    __tablename__ = "legacy_meetings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str | None] = mapped_column(String(20))
    end_time: Mapped[str | None] = mapped_column(String(20))
    location: Mapped[str | None] = mapped_column(String(150))
    chairperson: Mapped[str | None] = mapped_column(String(100))
    secretary: Mapped[str | None] = mapped_column(String(100))
    agenda: Mapped[str | None] = mapped_column(Text)
    participants: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    minute_status: Mapped[str] = mapped_column(String(30), default="draft")
    summary: Mapped[str | None] = mapped_column(Text)
    creator_id: Mapped[int] = mapped_column(ForeignKey("legacy_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    creator: Mapped["User"] = relationship(back_populates="meetings")
    notes: Mapped[list["MeetingNote"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    action_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    decision_brief: Mapped["DecisionBrief | None"] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan"
    )


class MeetingNote(LegacyBase):
    __tablename__ = "legacy_meeting_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("legacy_meetings.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("legacy_users.id"), nullable=False)
    agenda: Mapped[str | None] = mapped_column(String(200))
    note_type: Mapped[str] = mapped_column(String(30), default="discussion")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    meeting: Mapped["Meeting"] = relationship(back_populates="notes")
    author: Mapped["User"] = relationship(back_populates="notes")


class Decision(LegacyBase):
    __tablename__ = "legacy_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("legacy_meetings.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    meeting: Mapped["Meeting"] = relationship(back_populates="decisions")
    action_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )


class DecisionBrief(LegacyBase):
    __tablename__ = "legacy_decision_briefs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("legacy_meetings.id"), unique=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_decisions: Mapped[str | None] = mapped_column(Text)
    follow_up: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(50), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    meeting: Mapped["Meeting"] = relationship(back_populates="decision_brief")


class ActionItem(LegacyBase):
    __tablename__ = "legacy_action_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("legacy_meetings.id"), nullable=False)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("legacy_decisions.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(100))
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(30), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    progress_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    meeting: Mapped["Meeting"] = relationship(back_populates="action_items")
    decision: Mapped["Decision | None"] = relationship(back_populates="action_items")
