"""Meeting, agenda, and participant API schemas."""

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.meeting import MeetingStatus, MinutesReviewResult


class MeetingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_number: str = Field(min_length=1, max_length=150)
    title: str = Field(min_length=1, max_length=300)
    meeting_type: str = Field(default="RAPIM", min_length=1, max_length=100)
    meeting_date: date
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=300)
    chairperson_id: UUID | None = None
    notetaker_id: UUID | None = None

    @field_validator("meeting_number", "title", "meeting_type")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value

    @field_validator("location")
    @classmethod
    def strip_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_time_order(self) -> "MeetingCreate":
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class AgendaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agenda_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=500)
    agenda_description: str | None = Field(default=None, max_length=10_000)
    lead_user_id: UUID | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=1440)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value


class MeetingParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    participant_title: str | None = Field(default=None, max_length=200)

    @field_validator("participant_title")
    @classmethod
    def strip_participant_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class MeetingTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: MeetingStatus


class MinutesReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes_revision_id: UUID
    result: MinutesReviewResult
    review_note: str | None = Field(default=None, max_length=4_000)

    @field_validator("review_note")
    @classmethod
    def strip_review_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class MinutesRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=1_000_000)
    base_revision_id: UUID | None

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Minutes content cannot be blank")
        return value


class AgendaResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    agenda_number: int
    title: str
    agenda_description: str | None
    lead_user_id: UUID | None
    duration_minutes: int | None
    sort_order: int


class MeetingParticipantResponse(BaseModel):
    user_id: UUID
    participant_name: str
    attendance_status: str
    participant_title: str | None


class MeetingResponse(BaseModel):
    id: UUID
    meeting_number: str
    title: str
    meeting_type: str
    meeting_date: date
    start_time: time | None
    end_time: time | None
    location: str | None
    chairperson_id: UUID | None
    notetaker_id: UUID | None
    created_by_id: UUID
    status: MeetingStatus
    created_at: datetime
    updated_at: datetime
    agendas: list[AgendaResponse]
    participants: list[MeetingParticipantResponse]


class MinutesReviewResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    minutes_revision_id: UUID | None
    reviewer_user_id: UUID
    review_number: int
    result: MinutesReviewResult
    review_note: str | None
    reviewed_at: datetime


class MinutesRevisionResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    revision_number: int
    content: str
    created_by_id: UUID
    created_at: datetime
