from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.models.auth import User, UserSession
from app.models.meeting import Meeting, MeetingStatus, MinutesRevision
from sqlalchemy import UniqueConstraint, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_initial_migration_creates_identity_schema_and_seed_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            role_codes = set(connection.execute(text("SELECT role_code FROM roles")).scalars())

        assert {
            "users",
            "roles",
            "user_roles",
            "user_sessions",
            "meetings",
            "agendas",
            "meeting_participants",
            "meeting_status_events",
            "minutes_revisions",
            "minutes_reviews",
            "login_rate_limit_buckets",
            "alembic_version",
        } <= tables
        assert role_codes == {"SUPER_ADMIN", "SEKRETARIAT", "REKTOR", "WAREK", "PIC"}
        review_foreign_keys = inspect(engine).get_foreign_keys("minutes_reviews")
        assert any(
            foreign_key["referred_table"] == "minutes_revisions"
            and foreign_key["constrained_columns"] == ["meeting_id", "minutes_revision_id"]
            and foreign_key["referred_columns"] == ["meeting_id", "id"]
            for foreign_key in review_foreign_keys
        )
        with engine.connect() as connection:
            trigger_names = set(
                connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                ).scalars()
            )
        assert {
            "trg_minutes_revisions_no_update",
            "trg_minutes_revisions_no_delete",
        } <= trigger_names

        actor_id = uuid4()
        meeting_id = uuid4()
        revision_id = uuid4()
        with Session(engine) as session:
            session.add_all(
                [
                    User(
                        id=actor_id,
                        email="migration-minutes@example.test",
                        full_name="Synthetic Migration User",
                        password_hash="synthetic-only-not-used",
                        is_active=True,
                    ),
                    Meeting(
                        id=meeting_id,
                        meeting_number="MIGRATION-REVISION-001",
                        title="Synthetic migration test meeting",
                        meeting_date=date.today(),
                        created_by_id=actor_id,
                        status=MeetingStatus.DRAFT,
                    ),
                    MinutesRevision(
                        id=revision_id,
                        meeting_id=meeting_id,
                        revision_number=1,
                        content="Synthetic migration test minutes",
                        created_by_id=actor_id,
                    ),
                ]
            )
            session.commit()

        with engine.connect() as connection:
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(
                    text("UPDATE minutes_revisions SET content = 'silently replaced'")
                )
                connection.commit()
            connection.rollback()
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(text("DELETE FROM minutes_revisions"))
                connection.commit()
            connection.rollback()
        email_unique_constraint = any(
            constraint.name is None and [column.name for column in constraint.columns] == ["email"]
            for constraint in User.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        )
        session_user_index = any(
            index.name == "ix_user_sessions_user_id" for index in UserSession.__table__.indexes
        )
        assert email_unique_constraint
        assert session_user_index

        command.downgrade(config, "base")
        assert "users" not in inspect(engine).get_table_names()
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_versioned_minutes_migration_preserves_unbound_historical_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "historical_reviews.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0004_minutes_review")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        review_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "historical-review@example.test",
                    "full_name": "Synthetic Historical Reviewer",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, :meeting_number, :title, :meeting_date, :created_by_id)"
                ),
                {
                    "id": meeting_id,
                    "meeting_number": "HISTORICAL-REVIEW-001",
                    "title": "Synthetic historical review meeting",
                    "meeting_date": "2026-10-15",
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_reviews "
                    "(id, meeting_id, reviewer_user_id, review_number, result) "
                    "VALUES (:id, :meeting_id, :reviewer_user_id, :review_number, :result)"
                ),
                {
                    "id": review_id,
                    "meeting_id": meeting_id,
                    "reviewer_user_id": actor_id,
                    "review_number": 1,
                    "result": "VALID",
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            historical_review = connection.execute(
                text("SELECT id, minutes_revision_id FROM minutes_reviews WHERE id = :id"),
                {"id": review_id},
            ).one()
        assert historical_review.id == review_id
        assert historical_review.minutes_revision_id is None

        command.downgrade(config, "0004_minutes_review")
        with engine.connect() as connection:
            review_count = connection.execute(
                text("SELECT count(*) FROM minutes_reviews WHERE id = :id"), {"id": review_id}
            ).scalar_one()
            review_columns = {
                column["name"] for column in inspect(connection).get_columns("minutes_reviews")
            }
        assert review_count == 1
        assert "minutes_revision_id" not in review_columns

        command.downgrade(config, "base")
        engine.dispose()
    finally:
        get_settings.cache_clear()
