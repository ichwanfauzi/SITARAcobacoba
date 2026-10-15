"""Add attributable review records for meeting minutes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_minutes_review"
down_revision: str | None = "0003_workflow_rate_limit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minutes_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=False),
        sa.Column("review_number", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("review_number > 0", name="ck_minutes_reviews_number_positive"),
        sa.CheckConstraint("result IN ('VALID', 'INVALID')", name="ck_minutes_reviews_result"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id", "review_number", name="uq_minutes_reviews_meeting_number"
        ),
    )


def downgrade() -> None:
    op.drop_table("minutes_reviews")
