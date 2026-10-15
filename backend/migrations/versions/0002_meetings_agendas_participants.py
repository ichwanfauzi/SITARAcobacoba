"""Add Rapim meetings, agendas, and participants."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_meetings_agendas"
down_revision: str | None = "0001_identity_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_number", sa.String(length=150), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("meeting_type", sa.String(length=100), server_default="RAPIM", nullable=False),
        sa.Column("meeting_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("chairperson_id", sa.Uuid(), nullable=True),
        sa.Column("notetaker_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="DRAFT", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_meetings_title_not_blank"),
        sa.CheckConstraint(
            "end_time IS NULL OR start_time IS NULL OR end_time >= start_time",
            name="ck_meetings_time_order",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'LIVE', 'FINAL', 'ARCHIVED')",
            name="ck_meetings_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('FINAL', 'ARCHIVED') OR "
            "(finalized_at IS NOT NULL AND finalized_by_id IS NOT NULL)",
            name="ck_meetings_finalized_fields",
        ),
        sa.ForeignKeyConstraint(["chairperson_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["notetaker_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_number", name="uq_meetings_meeting_number"),
    )
    op.create_index("ix_meetings_date_status", "meetings", ["meeting_date", "status"])

    op.create_table(
        "meeting_participants",
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "attendance_status", sa.String(length=20), server_default="INVITED", nullable=False
        ),
        sa.Column("participant_title", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "attendance_status IN ('INVITED', 'PRESENT', 'ABSENT', 'EXCUSED')",
            name="ck_meeting_participant_attendance_status",
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("meeting_id", "user_id"),
    )

    op.create_table(
        "agendas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("agenda_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("agenda_description", sa.Text(), nullable=True),
        sa.Column("lead_user_id", sa.Uuid(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("agenda_number > 0", name="ck_agendas_number_positive"),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_agendas_duration_positive",
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "agenda_number", name="uq_agendas_meeting_number"),
    )
    op.create_index("ix_agendas_meeting_sort", "agendas", ["meeting_id", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_agendas_meeting_sort", table_name="agendas")
    op.drop_table("agendas")
    op.drop_table("meeting_participants")
    op.drop_index("ix_meetings_date_status", table_name="meetings")
    op.drop_table("meetings")
