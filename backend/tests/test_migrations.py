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
            "minutes_discussions",
            "minutes_decisions",
            "minutes_reviews",
            "decision_brief_versions",
            "decision_brief_decisions",
            "organization_units",
            "user_unit_memberships",
            "reporting_lines",
            "login_rate_limit_buckets",
            "action_items",
            "assignments",
            "progress_updates",
            "action_item_evidence",
            "action_item_evidence_scans",
            "completion_verifications",
            "status_histories",
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
            "trg_decision_brief_versions_no_update",
            "trg_decision_brief_versions_no_delete",
            "trg_progress_updates_no_update",
            "trg_progress_updates_no_delete",
            "trg_completion_verifications_no_update",
            "trg_completion_verifications_no_delete",
            "trg_status_histories_no_update",
            "trg_status_histories_no_delete",
            "trg_action_items_insert_guard",
            "trg_assignments_update_guard",
            "trg_progress_updates_assignment",
            "trg_action_item_evidence_limit",
            "trg_action_item_evidence_no_update",
            "trg_action_item_evidence_no_delete",
            "trg_action_item_evidence_scans_guard",
            "trg_action_item_evidence_scans_no_update",
            "trg_action_item_evidence_scans_no_delete",
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


def test_evidence_quarantine_migration_backfills_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "evidence-backfill.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)

    try:
        command.upgrade(config, "0010_action_item_evidence")
        evidence_id = uuid4().hex
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, storage_key, "
                    "original_filename, content_type, size_bytes, sha256, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'FILE', :key, 'existing.pdf', "
                    "'application/pdf', 1, :sha, :actor)"
                ),
                {
                    "id": evidence_id,
                    "item": uuid4().hex,
                    "progress": uuid4().hex,
                    "key": uuid4().hex,
                    "sha": "a" * 64,
                    "actor": uuid4().hex,
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            scan_event = connection.execute(
                text(
                    "SELECT event_number, scan_status FROM action_item_evidence_scans "
                    "WHERE evidence_id = :evidence"
                ),
                {"evidence": evidence_id},
            ).one()
            migration_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

        assert scan_event == (1, "PENDING")
        assert migration_head == "0011_evidence_scan_quarantine"
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_organization_scope_migration_has_no_seeds_and_protects_provisioned_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "organization_scope.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0007_decision_brief")
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        with engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
            for table_name in (
                "organization_units",
                "user_unit_memberships",
                "reporting_lines",
            ):
                count = connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
                assert count == 0
        assert {"meetings", "minutes_revisions", "decision_brief_versions"} <= table_names

        command.downgrade(config, "0007_decision_brief")
        assert "organization_units" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")

        unit_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organization_units (id, unit_code, name, is_active) "
                    "VALUES (:id, 'SYNTHETIC-UNIT', 'Unit sintetis', 1)"
                ),
                {"id": unit_id},
            )

        with pytest.raises(RuntimeError, match="organization scope contains records"):
            command.downgrade(config, "0007_decision_brief")

        with engine.connect() as connection:
            unit_count = connection.execute(
                text("SELECT count(*) FROM organization_units WHERE id = :id"), {"id": unit_id}
            ).scalar_one()
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0008_organization_scope"
        assert unit_count == 1
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_action_item_migration_preserves_minutes_and_protects_task_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "action_items.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0008_organization_scope")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        old_meeting_id, old_revision_id, old_review_id = map(str, (uuid4(), uuid4(), uuid4()))
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, 'legacy-minutes@example.test', 'Historical User', 'synthetic', 1)"
                ),
                {"id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, 'ACTION-HISTORY-001', 'Historical meeting', '2026-10-15', :actor)"
                ),
                {"id": old_meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting, 1, 1, 'Original historical minutes', :actor)"
                ),
                {"id": old_revision_id, "meeting": old_meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_reviews "
                    "(id, meeting_id, minutes_revision_id, reviewer_user_id, "
                    "review_number, result) "
                    "VALUES (:id, :meeting, :revision, :actor, 1, 'VALID')"
                ),
                {
                    "id": old_review_id,
                    "meeting": old_meeting_id,
                    "revision": old_revision_id,
                    "actor": actor_id,
                },
            )

        command.upgrade(config, "head")
        meeting_id, revision_id, agenda_id, discussion_id = map(
            str, (uuid4(), uuid4(), uuid4(), uuid4())
        )
        decision_id, no_action_decision_id, item_id = map(str, (uuid4(), uuid4(), uuid4()))
        assignment_id, progress_id, status_id = map(str, (uuid4(), uuid4(), uuid4()))
        with engine.begin() as connection:
            content, review_count = connection.execute(
                text(
                    "SELECT r.content, (SELECT count(*) FROM minutes_reviews WHERE id = :review) "
                    "FROM minutes_revisions r WHERE r.id = :revision"
                ),
                {"review": old_review_id, "revision": old_revision_id},
            ).one()
            assert content == "Original historical minutes"
            assert review_count == 1
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, 'ACTION-SOURCE-001', 'Task source', '2026-10-15', :actor)"
                ),
                {"id": meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting, 1, 2, NULL, :actor)"
                ),
                {"id": revision_id, "meeting": meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO agendas (id, meeting_id, agenda_number, title) "
                    "VALUES (:id, :meeting, 1, 'Synthetic agenda')"
                ),
                {"id": agenda_id, "meeting": meeting_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_discussions "
                    "(id, meeting_id, minutes_revision_id, agenda_id, discussion_number, content) "
                    "VALUES (:id, :meeting, :revision, :agenda, 1, 'Synthetic discussion')"
                ),
                {
                    "id": discussion_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "agenda": agenda_id,
                },
            )
            for source_id, is_action in ((decision_id, 1), (no_action_decision_id, 0)):
                connection.execute(
                    text(
                        "INSERT INTO minutes_decisions "
                        "(id, meeting_id, minutes_revision_id, discussion_id, decision_number, "
                        "decision_text, is_action_item) "
                        "VALUES (:id, :meeting, :revision, :discussion, :number, "
                        "'Synthetic decision', :is_action)"
                    ),
                    {
                        "id": source_id,
                        "meeting": meeting_id,
                        "revision": revision_id,
                        "discussion": discussion_id,
                        "number": 1 if is_action else 2,
                        "is_action": is_action,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO action_items "
                    "(id, meeting_id, source_minutes_revision_id, source_decision_id, "
                    "title, description, "
                    "priority, official_status, created_by_id) "
                    "VALUES (:id, :meeting, :revision, :decision, 'Synthetic task', "
                    "'Task description', "
                    "'Penting', 'BELUM_DIMULAI', :actor)"
                ),
                {
                    "id": item_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "decision": decision_id,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO assignments "
                    "(id, action_item_id, assignee_user_id, assigned_by_user_id, assignment_role) "
                    "VALUES (:id, :item, :actor, :actor, 'MAIN')"
                ),
                {"id": assignment_id, "item": item_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO status_histories "
                    "(id, action_item_id, event_number, old_status, new_status, changed_by_id) "
                    "VALUES (:id, :item, 1, NULL, 'BELUM_DIMULAI', :actor)"
                ),
                {"id": status_id, "item": item_id, "actor": actor_id},
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="not actionable"):
            connection.execute(
                text(
                    "INSERT INTO action_items "
                    "(id, meeting_id, source_minutes_revision_id, source_decision_id, "
                    "title, description, "
                    "priority, official_status, created_by_id) "
                    "VALUES (:id, :meeting, :revision, :decision, 'Invalid task', "
                    "'Task description', "
                    "'Penting', 'BELUM_DIMULAI', :actor)"
                ),
                {
                    "id": str(uuid4()),
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "decision": no_action_decision_id,
                    "actor": actor_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "INSERT INTO progress_updates "
                    "(id, action_item_id, assignment_id, actor_user_id, report_text, "
                    "completion_requested) "
                    "VALUES (:id, :item, :assignment, :actor, 'Synthetic progress', 0)"
                ),
                {
                    "id": progress_id,
                    "item": item_id,
                    "assignment": assignment_id,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "UPDATE progress_updates SET report_text = 'Rewritten history' WHERE id = :id"
                ),
                {"id": progress_id},
            )

        with pytest.raises(RuntimeError, match="Action Item history contains records"):
            command.downgrade(config, "0008_organization_scope")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM action_items")).scalar_one() == 1
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0009_action_items"
            )

        command.upgrade(config, "head")
        leadership_progress_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO progress_updates "
                    "(id, action_item_id, assignment_id, actor_user_id, submitted_as, "
                    "report_text, completion_requested) "
                    "VALUES (:id, :item, NULL, :actor, 'LEADERSHIP', "
                    "'Leadership report', 0)"
                ),
                {"id": leadership_progress_id, "item": item_id, "actor": actor_id},
            )
            for index in range(5):
                connection.execute(
                    text(
                        "INSERT INTO action_item_evidence "
                        "(id, action_item_id, progress_update_id, evidence_kind, "
                        "external_url, uploaded_by_user_id) "
                        "VALUES (:id, :item, :progress, 'LINK', :url, :actor)"
                    ),
                    {
                        "id": str(uuid4()),
                        "item": item_id,
                        "progress": leadership_progress_id,
                        "url": f"https://example.test/evidence/{index}",
                        "actor": actor_id,
                    },
                )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="five evidence"):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, "
                    "external_url, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'LINK', "
                    "'https://example.test/evidence/overflow', :actor)"
                ),
                {
                    "id": str(uuid4()),
                    "item": item_id,
                    "progress": leadership_progress_id,
                    "actor": actor_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, "
                    "external_url, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'LINK', 'http://example.test', :actor)"
                ),
                {
                    "id": str(uuid4()),
                    "item": item_id,
                    "progress": leadership_progress_id,
                    "actor": actor_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE action_item_evidence SET link_label = 'rewritten' "
                    "WHERE progress_update_id = :progress"
                ),
                {"progress": leadership_progress_id},
            )

        scan_progress_id, file_evidence_id = map(str, (uuid4(), uuid4()))
        file_sha256 = "a" * 64
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO progress_updates "
                    "(id, action_item_id, assignment_id, actor_user_id, report_text, "
                    "completion_requested) "
                    "VALUES (:id, :item, :assignment, :actor, 'File evidence test', 0)"
                ),
                {
                    "id": scan_progress_id,
                    "item": item_id,
                    "assignment": assignment_id,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, storage_key, "
                    "original_filename, content_type, size_bytes, sha256, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'FILE', :key, 'proof.pdf', "
                    "'application/pdf', 14, :sha, :actor)"
                ),
                {
                    "id": file_evidence_id,
                    "item": item_id,
                    "progress": scan_progress_id,
                    "key": uuid4().hex,
                    "sha": file_sha256,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status) "
                    "VALUES (:id, :evidence, 1, 'PENDING')"
                ),
                {"id": str(uuid4()), "evidence": file_evidence_id},
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="does not match"):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status, scanner_name, "
                    "scanner_version, scanned_sha256) "
                    "VALUES (:id, :evidence, 2, 'CLEAN', 'synthetic', '1', :sha)"
                ),
                {
                    "id": str(uuid4()),
                    "evidence": file_evidence_id,
                    "sha": "b" * 64,
                },
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status, scanner_name, "
                    "scanner_version, scanned_sha256) "
                    "VALUES (:id, :evidence, 2, 'CLEAN', 'synthetic', '1', :sha)"
                ),
                {
                    "id": str(uuid4()),
                    "evidence": file_evidence_id,
                    "sha": file_sha256,
                },
            )

        with (
            engine.begin() as connection,
            pytest.raises(IntegrityError, match="transition is invalid"),
        ):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status, scanner_name, "
                    "scanner_version, scanned_sha256) "
                    "VALUES (:id, :evidence, 3, 'REJECTED', 'synthetic', '1', :sha)"
                ),
                {
                    "id": str(uuid4()),
                    "evidence": file_evidence_id,
                    "sha": file_sha256,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE action_item_evidence_scans SET scan_status = 'REJECTED' "
                    "WHERE evidence_id = :evidence"
                ),
                {"evidence": file_evidence_id},
            )

        with pytest.raises(RuntimeError, match="scan history"):
            command.downgrade(config, "0009_action_items")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0011_evidence_scan_quarantine"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM action_item_evidence "
                        "WHERE progress_update_id = :progress"
                    ),
                    {"progress": leadership_progress_id},
                ).scalar_one()
                == 5
            )
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


def test_structured_minutes_migration_preserves_legacy_text_and_bound_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "structured_minutes_upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0005_versioned_minutes")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        revision_id = str(uuid4())
        review_id = str(uuid4())
        original_text = "Synthetic legacy minutes must remain byte-for-byte readable"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "structured-migration@example.test",
                    "full_name": "Synthetic Migration User",
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
                    "meeting_number": "STRUCTURED-MIGRATION-001",
                    "title": "Synthetic legacy meeting",
                    "meeting_date": "2026-10-21",
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 1, :content, :created_by_id)"
                ),
                {
                    "id": revision_id,
                    "meeting_id": meeting_id,
                    "content": original_text,
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_reviews "
                    "(id, meeting_id, minutes_revision_id, reviewer_user_id, "
                    "review_number, result) "
                    "VALUES (:id, :meeting_id, :revision_id, :reviewer_id, 1, 'VALID')"
                ),
                {
                    "id": review_id,
                    "meeting_id": meeting_id,
                    "revision_id": revision_id,
                    "reviewer_id": actor_id,
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT format_version, content FROM minutes_revisions WHERE id = :id"),
                {"id": revision_id},
            ).one()
            review = connection.execute(
                text("SELECT minutes_revision_id, result FROM minutes_reviews WHERE id = :id"),
                {"id": review_id},
            ).one()
            migration_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

        assert migration_head == "0011_evidence_scan_quarantine"
        assert (revision.format_version, revision.content) == (1, original_text)
        assert (review.minutes_revision_id, review.result) == (revision_id, "VALID")
        assert {
            "minutes_discussions",
            "minutes_decisions",
        } <= set(inspect(engine).get_table_names())
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 2, 2, 'invalid structured content', "
                    ":created_by_id)"
                ),
                {
                    "id": str(uuid4()),
                    "meeting_id": meeting_id,
                    "created_by_id": actor_id,
                },
            )
        command.downgrade(config, "0005_versioned_minutes")
        with engine.connect() as connection:
            restored_text = connection.execute(
                text("SELECT content FROM minutes_revisions WHERE id = :id"),
                {"id": revision_id},
            ).scalar_one()
            restored_review = connection.execute(
                text("SELECT minutes_revision_id FROM minutes_reviews WHERE id = :id"),
                {"id": review_id},
            ).scalar_one()
        assert restored_text == original_text
        assert restored_review == revision_id
        command.downgrade(config, "base")
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_structured_minutes_downgrade_refuses_to_drop_structured_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "structured_minutes_downgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        agenda_id = str(uuid4())
        revision_id = str(uuid4())
        discussion_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "structured-downgrade@example.test",
                    "full_name": "Synthetic Structured Author",
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
                    "meeting_number": "STRUCTURED-DOWNGRADE-001",
                    "title": "Synthetic structured meeting",
                    "meeting_date": "2026-10-21",
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agendas (id, meeting_id, agenda_number, title) "
                    "VALUES (:id, :meeting_id, 1, 'Synthetic agenda')"
                ),
                {"id": agenda_id, "meeting_id": meeting_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 1, 2, NULL, :created_by_id)"
                ),
                {"id": revision_id, "meeting_id": meeting_id, "created_by_id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_discussions "
                    "(id, meeting_id, minutes_revision_id, agenda_id, discussion_number, content) "
                    "VALUES (:id, :meeting_id, :revision_id, :agenda_id, 1, 'Synthetic discussion')"
                ),
                {
                    "id": discussion_id,
                    "meeting_id": meeting_id,
                    "revision_id": revision_id,
                    "agenda_id": agenda_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text("UPDATE minutes_discussions SET content = 'silently replaced' WHERE id = :id"),
                {"id": discussion_id},
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text("DELETE FROM minutes_discussions WHERE id = :id"),
                {"id": discussion_id},
            )

        with pytest.raises(RuntimeError, match="structured minutes"):
            command.downgrade(config, "0005_versioned_minutes")
        with engine.connect() as connection:
            migration_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            text_content = connection.execute(
                text("SELECT content FROM minutes_revisions WHERE id = :id"),
                {"id": revision_id},
            ).scalar_one()
            discussion_count = connection.execute(
                text("SELECT count(*) FROM minutes_discussions WHERE id = :id"),
                {"id": discussion_id},
            ).scalar_one()
        assert migration_head == "0006_structured_minutes"
        assert text_content is None
        assert discussion_count == 1
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_decision_brief_migration_preserves_minutes_and_guards_brief_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "decision_brief_upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0006_structured_minutes")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        revision_id = str(uuid4())
        structured_revision_id = str(uuid4())
        agenda_id = str(uuid4())
        discussion_id = str(uuid4())
        decision_id = str(uuid4())
        original_text = "Synthetic legacy minutes for Decision Brief migration"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :name, :password_hash, :active)"
                ),
                {
                    "id": actor_id,
                    "email": "brief-migration@example.test",
                    "name": "Synthetic Brief User",
                    "password_hash": "synthetic-only-not-used",
                    "active": True,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, :number, :title, :meeting_date, :actor_id)"
                ),
                {
                    "id": meeting_id,
                    "number": "BRIEF-MIGRATION-001",
                    "title": "Synthetic migration meeting",
                    "meeting_date": date(2026, 10, 21),
                    "actor_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 1, 1, :content, :actor_id)"
                ),
                {
                    "id": revision_id,
                    "meeting_id": meeting_id,
                    "content": original_text,
                    "actor_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agendas (id, meeting_id, agenda_number, title) "
                    "VALUES (:id, :meeting_id, 1, 'Synthetic structured agenda')"
                ),
                {"id": agenda_id, "meeting_id": meeting_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 2, 2, NULL, :actor_id)"
                ),
                {"id": structured_revision_id, "meeting_id": meeting_id, "actor_id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_discussions "
                    "(id, meeting_id, minutes_revision_id, agenda_id, discussion_number, content) "
                    "VALUES (:id, :meeting_id, :revision_id, :agenda_id, 1, 'Synthetic discussion')"
                ),
                {
                    "id": discussion_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                    "agenda_id": agenda_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_decisions "
                    "(id, meeting_id, minutes_revision_id, discussion_id, "
                    "decision_number, decision_text) "
                    "VALUES (:id, :meeting_id, :revision_id, :discussion_id, "
                    "1, 'Synthetic decision')"
                ),
                {
                    "id": decision_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                    "discussion_id": discussion_id,
                },
            )

        command.upgrade(config, "head")
        with engine.begin() as connection:
            version_id = str(uuid4())
            version_row = connection.execute(
                text(
                    "INSERT INTO decision_brief_versions "
                    "(id, meeting_id, source_minutes_revision_id, version_number, summary, "
                    "created_by_id) VALUES (:id, :meeting_id, :revision_id, 1, :summary, :actor_id)"
                ),
                {
                    "id": version_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                    "summary": "Synthetic editorial brief",
                    "actor_id": actor_id,
                },
            )
            entry_row = connection.execute(
                text(
                    "INSERT INTO decision_brief_decisions "
                    "(brief_version_id, source_decision_id, meeting_id, "
                    "source_minutes_revision_id, position, priority) "
                    "VALUES (:version_id, :decision_id, :meeting_id, :revision_id, 1, 'Utama')"
                ),
                {
                    "version_id": version_id,
                    "decision_id": decision_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                },
            )
            stored_text = connection.execute(
                text("SELECT content FROM minutes_revisions WHERE id = :revision_id"),
                {"revision_id": revision_id},
            ).scalar_one()
            assert stored_text == original_text

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE decision_brief_versions SET summary = 'changed' WHERE meeting_id = :id"
                ),
                {"id": meeting_id},
            )
        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE decision_brief_decisions SET priority = 'changed' "
                    "WHERE meeting_id = :id"
                ),
                {"id": meeting_id},
            )

        with pytest.raises(RuntimeError, match="Decision Brief version history"):
            command.downgrade(config, "0006_structured_minutes")

        assert version_row.rowcount == 1
        assert entry_row.rowcount == 1
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0007_decision_brief"
            )
        engine.dispose()
    finally:
        get_settings.cache_clear()
