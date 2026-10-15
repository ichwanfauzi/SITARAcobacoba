"""Add append-only minutes revisions and link reviews to exact revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_versioned_minutes"
down_revision: str | None = "0004_minutes_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minutes_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_minutes_revisions_number_positive"),
        sa.CheckConstraint(
            "length(trim(content)) > 0", name="ck_minutes_revisions_content_not_blank"
        ),
        sa.CheckConstraint("length(content) <= 1000000", name="ck_minutes_revisions_content_size"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id", "revision_number", name="uq_minutes_revisions_meeting_number"
        ),
        sa.UniqueConstraint("meeting_id", "id", name="uq_minutes_revisions_meeting_id"),
    )

    with op.batch_alter_table("minutes_reviews") as batch_op:
        batch_op.add_column(sa.Column("minutes_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_minutes_reviews_revision_same_meeting",
            "minutes_revisions",
            ["meeting_id", "minutes_revision_id"],
            ["meeting_id", "id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_minutes_reviews_revision", ["meeting_id", "minutes_revision_id"])

    _create_immutability_guards()


def downgrade() -> None:
    _drop_immutability_guards()

    with op.batch_alter_table("minutes_reviews") as batch_op:
        batch_op.drop_index("ix_minutes_reviews_revision")
        batch_op.drop_constraint("fk_minutes_reviews_revision_same_meeting", type_="foreignkey")
        batch_op.drop_column("minutes_revision_id")

    op.drop_table("minutes_revisions")


def _create_immutability_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_minutes_revision_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'minutes revisions are append-only';
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_minutes_revisions_append_only
            BEFORE UPDATE OR DELETE ON minutes_revisions
            FOR EACH ROW EXECUTE FUNCTION reject_minutes_revision_mutation()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_minutes_revisions_no_truncate
            BEFORE TRUNCATE ON minutes_revisions
            FOR EACH STATEMENT EXECUTE FUNCTION reject_minutes_revision_mutation()
            """
        )
    elif dialect_name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_minutes_revisions_no_update
            BEFORE UPDATE ON minutes_revisions
            BEGIN
                SELECT RAISE(ABORT, 'minutes revisions are append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_minutes_revisions_no_delete
            BEFORE DELETE ON minutes_revisions
            BEGIN
                SELECT RAISE(ABORT, 'minutes revisions are append-only');
            END
            """
        )
    else:
        raise RuntimeError(f"Unsupported database dialect for minutes revisions: {dialect_name}")


def _drop_immutability_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute("DROP TRIGGER trg_minutes_revisions_no_truncate ON minutes_revisions")
        op.execute("DROP TRIGGER trg_minutes_revisions_append_only ON minutes_revisions")
        op.execute("DROP FUNCTION reject_minutes_revision_mutation()")
    elif dialect_name == "sqlite":
        op.execute("DROP TRIGGER trg_minutes_revisions_no_update")
        op.execute("DROP TRIGGER trg_minutes_revisions_no_delete")
