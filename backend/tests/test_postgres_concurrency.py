"""PostgreSQL integration checks; run only against an isolated test database."""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from app.core.config import get_settings
from app.models.auth import Role, User
from app.models.meeting import (
    Agenda,
    DecisionBriefDecision,
    DecisionBriefVersion,
    Meeting,
    MeetingStatus,
    MeetingStatusEvent,
    MinutesDecision,
    MinutesDiscussion,
    MinutesReview,
    MinutesReviewResult,
    MinutesRevision,
)
from app.models.security import LoginRateLimitBucket
from app.schemas.meetings import (
    DecisionBriefDecisionCreate,
    DecisionBriefVersionCreate,
    MinutesDiscussionCreate,
    MinutesReviewCreate,
    MinutesRevisionCreate,
)
from app.services.meetings import (
    InvalidMeetingTransition,
    MeetingNotLiveForMinutesReview,
    MeetingNotLiveForMinutesRevision,
    MinutesReviewRequired,
    MinutesRevisionConflict,
    create_decision_brief_version,
    create_minutes_revision,
    record_minutes_review,
    transition_meeting,
)
from app.services.rate_limiting import (
    LoginRateLimitExceeded,
    _bucket_hash,
    cleanup_expired_login_rate_limit_buckets,
    enforce_login_rate_limit,
)
from sqlalchemy import create_engine, delete, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.getenv("SITARA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="SITARA_TEST_DATABASE_URL must point to a disposable PostgreSQL database",
)


@pytest.fixture(scope="module")
def postgres_sessions() -> Iterator[sessionmaker[Session]]:
    assert TEST_DATABASE_URL is not None
    engine: Engine = create_engine(
        TEST_DATABASE_URL, pool_pre_ping=True, pool_size=16, max_overflow=0
    )
    table_names = set(inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "meeting_status_events",
        "minutes_revisions",
        "minutes_discussions",
        "minutes_decisions",
        "minutes_reviews",
        "decision_brief_versions",
        "decision_brief_decisions",
        "login_rate_limit_buckets",
    } <= table_names
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == "0008_organization_scope"
        )
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def test_postgres_upsert_enforces_limit_under_parallel_requests(
    postgres_sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    email = f"parallel-{uuid4()}@example.test"
    client_ip = "198.51.100.17"

    def reserve_attempt(_: int) -> bool:
        with postgres_sessions() as session:
            try:
                enforce_login_rate_limit(session, email, client_ip)
            except LoginRateLimitExceeded:
                return False
            return True

    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            allowed = list(executor.map(reserve_attempt, range(64)))

        assert sum(allowed) == 7
        settings = get_settings()
        assert settings.login_rate_limit_hmac_key is not None
        expected_hash = _bucket_hash(
            email, client_ip, settings.login_rate_limit_hmac_key.get_secret_value()
        )
        with postgres_sessions() as session:
            bucket = session.get(LoginRateLimitBucket, expected_hash)
            assert bucket is not None
            assert bucket.attempt_count == 8
            assert email not in bucket.bucket_hash
            assert "198.51.100.17" not in bucket.bucket_hash
    finally:
        get_settings.cache_clear()


def test_postgres_expiration_cleanup_removes_only_expired_buckets(
    postgres_sessions: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    expired_hash = uuid4().hex + uuid4().hex
    active_hash = uuid4().hex + uuid4().hex
    with postgres_sessions() as session:
        session.add_all(
            [
                LoginRateLimitBucket(
                    bucket_hash=expired_hash,
                    window_started_at=now - timedelta(hours=2),
                    attempt_count=3,
                    expires_at=now - timedelta(hours=1),
                ),
                LoginRateLimitBucket(
                    bucket_hash=active_hash,
                    window_started_at=now,
                    attempt_count=1,
                    expires_at=now + timedelta(minutes=5),
                ),
            ]
        )
        session.commit()

        removed = cleanup_expired_login_rate_limit_buckets(session, now=now)
        session.commit()

        assert removed == 1
        assert session.get(LoginRateLimitBucket, expired_hash) is None
        assert session.get(LoginRateLimitBucket, active_hash) is not None
        session.delete(session.get(LoginRateLimitBucket, active_hash))
        session.commit()


def test_postgres_row_lock_serializes_concurrent_meeting_transitions(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    meeting_number = f"TEST-{uuid4()}"
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"transition-{uuid4()}@example.test",
            full_name="Synthetic Secretariat",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=meeting_number,
            title="Synthetic concurrency verification",
            meeting_date=date.today(),
            created_by_id=actor_id,
            status=MeetingStatus.DRAFT,
        )
        session.add_all([actor, meeting])
        session.commit()

    def start_meeting(_: int) -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            try:
                transition_meeting(session, meeting_id, actor, MeetingStatus.LIVE)
                return "changed"
            except InvalidMeetingTransition:
                return "stale"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(start_meeting, range(2)))

        assert sorted(outcomes) == ["changed", "stale"]
        with postgres_sessions() as session:
            meeting = session.get(Meeting, meeting_id)
            events = list(
                session.scalars(
                    select(MeetingStatusEvent).where(MeetingStatusEvent.meeting_id == meeting_id)
                )
            )
            assert meeting is not None
            assert meeting.status is MeetingStatus.LIVE
            assert len(events) == 1
    finally:
        with postgres_sessions() as session:
            session.execute(
                delete(MeetingStatusEvent).where(MeetingStatusEvent.meeting_id == meeting_id)
            )
            session.execute(delete(Meeting).where(Meeting.id == meeting_id))
            session.execute(delete(User).where(User.id == actor_id))
            session.commit()


def test_postgres_review_and_finalization_serialize_on_meeting_row(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    meeting_number = f"REVIEW-TEST-{uuid4()}"
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"review-{uuid4()}@example.test",
            full_name="Synthetic Minutes Reviewer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=meeting_number,
            title="Synthetic minutes review concurrency",
            meeting_date=date.today(),
            created_by_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
            notetaker_id=actor_id,
        )
        revision = MinutesRevision(
            id=uuid4(),
            meeting_id=meeting_id,
            revision_number=1,
            content="Synthetic live minutes for concurrency verification",
            created_by_id=actor_id,
            created_at=now,
        )
        session.add_all([actor, meeting, revision])
        session.commit()

    barrier = Barrier(2)

    def submit_review(_: int) -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                record_minutes_review(
                    session,
                    meeting_id,
                    actor,
                    MinutesReviewCreate(
                        minutes_revision_id=revision.id,
                        result=MinutesReviewResult.VALID,
                    ),
                )
                return "recorded"
            except MeetingNotLiveForMinutesReview:
                return "meeting-not-live"

    def finalize(_: int) -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                transition_meeting(session, meeting_id, actor, MeetingStatus.FINAL)
                return "finalized"
            except MinutesReviewRequired:
                return "review-required"

    with ThreadPoolExecutor(max_workers=2) as executor:
        review_future = executor.submit(submit_review, 0)
        finalization_future = executor.submit(finalize, 0)
        review_outcome = review_future.result()
        finalization_outcome = finalization_future.result()

    assert review_outcome == "recorded"
    assert finalization_outcome in {"finalized", "review-required"}
    with postgres_sessions() as session:
        meeting = session.get(Meeting, meeting_id)
        reviews = list(
            session.scalars(select(MinutesReview).where(MinutesReview.meeting_id == meeting_id))
        )
        events = list(
            session.scalars(
                select(MeetingStatusEvent).where(MeetingStatusEvent.meeting_id == meeting_id)
            )
        )
        assert meeting is not None
        assert len(reviews) == 1
        assert reviews[0].result is MinutesReviewResult.VALID
        assert reviews[0].minutes_revision_id == revision.id
        if finalization_outcome == "finalized":
            assert meeting.status is MeetingStatus.FINAL
            assert meeting.finalized_by_id == actor_id
            assert len(events) == 1
            assert events[0].to_status == "FINAL"
        else:
            assert meeting.status is MeetingStatus.LIVE
            assert meeting.finalized_at is None
            assert events == []


def test_postgres_stale_concurrent_minutes_writer_is_rejected(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"minutes-writer-{uuid4()}@example.test",
            full_name="Synthetic Minutes Writer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"REVISION-RACE-{uuid4()}",
            title="Synthetic revision race",
            meeting_date=date.today(),
            created_by_id=actor_id,
            notetaker_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
        )
        session.add_all([actor, meeting])
        session.commit()

    barrier = Barrier(2)

    def append_revision(sequence: int) -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                revision = create_minutes_revision(
                    session,
                    meeting_id,
                    actor,
                    MinutesRevisionCreate(
                        content=f"Synthetic concurrent revision {sequence}",
                        base_revision_id=None,
                    ),
                )
                return str(revision.id)
            except MinutesRevisionConflict:
                return "stale-base"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append_revision, (1, 2)))

    assert outcomes.count("stale-base") == 1
    with postgres_sessions() as session:
        revisions = list(
            session.scalars(select(MinutesRevision).where(MinutesRevision.meeting_id == meeting_id))
        )
        assert len(revisions) == 1
        assert revisions[0].revision_number == 1


def test_postgres_stale_concurrent_structured_writer_commits_one_complete_snapshot(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    agenda_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"structured-writer-{uuid4()}@example.test",
            full_name="Synthetic Structured Minutes Writer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"STRUCTURED-RACE-{uuid4()}",
            title="Synthetic structured revision race",
            meeting_date=date.today(),
            created_by_id=actor_id,
            notetaker_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
        )
        agenda = Agenda(
            id=agenda_id,
            meeting_id=meeting_id,
            agenda_number=1,
            title="Synthetic agenda",
        )
        session.add_all([actor, meeting, agenda])
        session.commit()

    barrier = Barrier(2)

    def append_structured_revision(sequence: int) -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                create_minutes_revision(
                    session,
                    meeting_id,
                    actor,
                    MinutesRevisionCreate(
                        format_version=2,
                        content=None,
                        base_revision_id=None,
                        discussions=[
                            MinutesDiscussionCreate(
                                agenda_id=agenda_id,
                                content=f"Synthetic concurrent discussion {sequence}",
                                decisions=[],
                            )
                        ],
                    ),
                )
                return "created"
            except MinutesRevisionConflict:
                return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append_structured_revision, (1, 2)))

    assert sorted(outcomes) == ["created", "stale"]
    with postgres_sessions() as session:
        revisions = list(
            session.scalars(select(MinutesRevision).where(MinutesRevision.meeting_id == meeting_id))
        )
        discussions = list(
            session.scalars(
                select(MinutesDiscussion).where(MinutesDiscussion.meeting_id == meeting_id)
            )
        )
        decisions = list(
            session.scalars(select(MinutesDecision).where(MinutesDecision.meeting_id == meeting_id))
        )
        assert len(revisions) == len(discussions) == 1
        assert revisions[0].format_version == 2 and revisions[0].content is None
        assert discussions[0].minutes_revision_id == revisions[0].id
        assert decisions == []


def test_postgres_revision_change_racing_finalization_cannot_finalize_stale_review(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"minutes-finalize-race-{uuid4()}@example.test",
            full_name="Synthetic Minutes Writer and Reviewer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"FINALIZE-RACE-{uuid4()}",
            title="Synthetic revision/finalization race",
            meeting_date=date.today(),
            created_by_id=actor_id,
            notetaker_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
        )
        revision = MinutesRevision(
            id=revision_id,
            meeting_id=meeting_id,
            revision_number=1,
            content="Synthetic reviewed revision",
            created_by_id=actor_id,
            created_at=now,
        )
        review = MinutesReview(
            id=uuid4(),
            meeting_id=meeting_id,
            minutes_revision_id=revision_id,
            reviewer_user_id=actor_id,
            review_number=1,
            result=MinutesReviewResult.VALID,
            reviewed_at=now,
        )
        session.add_all([actor, meeting, revision, review])
        session.commit()

    barrier = Barrier(2)

    def append_revision() -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                create_minutes_revision(
                    session,
                    meeting_id,
                    actor,
                    MinutesRevisionCreate(
                        content="Synthetic newer revision",
                        base_revision_id=revision_id,
                    ),
                )
                return "revision-created"
            except MeetingNotLiveForMinutesRevision:
                return "meeting-not-live"
            except MinutesRevisionConflict:
                return "stale-base"

    def finalize() -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                transition_meeting(session, meeting_id, actor, MeetingStatus.FINAL)
                return "finalized"
            except MinutesReviewRequired:
                return "review-required"

    with ThreadPoolExecutor(max_workers=2) as executor:
        revision_future = executor.submit(append_revision)
        finalization_future = executor.submit(finalize)
        outcomes = {revision_future.result(), finalization_future.result()}

    with postgres_sessions() as session:
        meeting = session.get(Meeting, meeting_id)
        revisions = list(
            session.scalars(
                select(MinutesRevision)
                .where(MinutesRevision.meeting_id == meeting_id)
                .order_by(MinutesRevision.revision_number)
            )
        )
        reviews = list(
            session.scalars(select(MinutesReview).where(MinutesReview.meeting_id == meeting_id))
        )
        events = list(
            session.scalars(
                select(MeetingStatusEvent).where(MeetingStatusEvent.meeting_id == meeting_id)
            )
        )
        assert meeting is not None
        assert len(reviews) == 1
        if meeting.status is MeetingStatus.FINAL:
            assert outcomes == {"meeting-not-live", "finalized"}
            assert len(revisions) == 1
            assert reviews[0].minutes_revision_id == revisions[-1].id
            assert len(events) == 1
        else:
            assert outcomes == {"revision-created", "review-required"}
            assert meeting.status is MeetingStatus.LIVE
            assert len(revisions) == 2
            assert reviews[0].minutes_revision_id != revisions[-1].id
            assert events == []


def test_postgres_revision_change_racing_review_never_reviews_the_wrong_active_revision(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"minutes-review-race-{uuid4()}@example.test",
            full_name="Synthetic Minutes Writer and Reviewer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"REVIEW-REVISION-RACE-{uuid4()}",
            title="Synthetic review/revision race",
            meeting_date=date.today(),
            created_by_id=actor_id,
            notetaker_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
        )
        revision = MinutesRevision(
            id=revision_id,
            meeting_id=meeting_id,
            revision_number=1,
            content="Synthetic revision to review",
            created_by_id=actor_id,
            created_at=now,
        )
        session.add_all([actor, meeting, revision])
        session.commit()

    barrier = Barrier(2)

    def append_revision() -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            create_minutes_revision(
                session,
                meeting_id,
                actor,
                MinutesRevisionCreate(
                    content="Synthetic revision added during review",
                    base_revision_id=revision_id,
                ),
            )
            return "revision-created"

    def review_revision() -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                record_minutes_review(
                    session,
                    meeting_id,
                    actor,
                    MinutesReviewCreate(
                        minutes_revision_id=revision_id,
                        result=MinutesReviewResult.VALID,
                    ),
                )
                return "review-recorded"
            except MinutesRevisionConflict:
                return "review-stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        revision_future = executor.submit(append_revision)
        review_future = executor.submit(review_revision)
        outcomes = {revision_future.result(), review_future.result()}

    with postgres_sessions() as session:
        actor = session.get(User, actor_id)
        assert actor is not None
        latest_revision = session.scalar(
            select(MinutesRevision)
            .where(MinutesRevision.meeting_id == meeting_id)
            .order_by(MinutesRevision.revision_number.desc())
            .limit(1)
        )
        reviews = list(
            session.scalars(select(MinutesReview).where(MinutesReview.meeting_id == meeting_id))
        )
        assert outcomes in (
            {"revision-created", "review-recorded"},
            {"revision-created", "review-stale"},
        )
        assert latest_revision is not None and latest_revision.revision_number == 2
        assert all(review.minutes_revision_id == revision_id for review in reviews)
        with pytest.raises(MinutesReviewRequired):
            transition_meeting(session, meeting_id, actor, MeetingStatus.FINAL)
        meeting = session.get(Meeting, meeting_id)
        events = list(
            session.scalars(
                select(MeetingStatusEvent).where(MeetingStatusEvent.meeting_id == meeting_id)
            )
        )
        assert meeting is not None and meeting.status is MeetingStatus.LIVE
        assert events == []


def test_postgres_two_concurrent_finalizations_write_only_one_event(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"double-finalize-{uuid4()}@example.test",
            full_name="Synthetic Finalizer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"DOUBLE-FINALIZE-{uuid4()}",
            title="Synthetic simultaneous finalizations",
            meeting_date=date.today(),
            created_by_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
        )
        revision = MinutesRevision(
            id=revision_id,
            meeting_id=meeting_id,
            revision_number=1,
            content="Synthetic valid minutes",
            created_by_id=actor_id,
            created_at=now,
        )
        review = MinutesReview(
            id=uuid4(),
            meeting_id=meeting_id,
            minutes_revision_id=revision_id,
            reviewer_user_id=actor_id,
            review_number=1,
            result=MinutesReviewResult.VALID,
            reviewed_at=now,
        )
        session.add_all([actor, meeting, revision, review])
        session.commit()

    barrier = Barrier(2)

    def finalize() -> str:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            try:
                transition_meeting(session, meeting_id, actor, MeetingStatus.FINAL)
                return "finalized"
            except InvalidMeetingTransition:
                return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: finalize(), range(2)))

    assert sorted(outcomes) == ["finalized", "stale"]
    with postgres_sessions() as session:
        meeting = session.get(Meeting, meeting_id)
        events = list(
            session.scalars(
                select(MeetingStatusEvent).where(MeetingStatusEvent.meeting_id == meeting_id)
            )
        )
        assert meeting is not None and meeting.status is MeetingStatus.FINAL
        assert len(events) == 1


def test_postgres_revision_foreign_key_and_append_only_trigger(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    other_meeting_id = uuid4()
    actor_id = uuid4()
    revision_id = uuid4()
    structured_revision_id = uuid4()
    agenda_id = uuid4()
    discussion_id = uuid4()
    decision_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"minutes-constraint-{uuid4()}@example.test",
            full_name="Synthetic Minutes Reviewer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"REVISION-CONSTRAINT-{uuid4()}",
            title="Synthetic owning meeting",
            meeting_date=date.today(),
            created_by_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
        )
        other_meeting = Meeting(
            id=other_meeting_id,
            meeting_number=f"REVISION-OTHER-{uuid4()}",
            title="Synthetic other meeting",
            meeting_date=date.today(),
            created_by_id=actor_id,
            status=MeetingStatus.LIVE,
            started_at=now,
        )
        agenda = Agenda(
            id=agenda_id,
            meeting_id=meeting_id,
            agenda_number=1,
            title="Synthetic immutable agenda",
        )
        revision = MinutesRevision(
            id=revision_id,
            meeting_id=meeting_id,
            revision_number=1,
            content="Synthetic immutable minutes",
            created_by_id=actor_id,
            created_at=now,
        )
        structured_revision = MinutesRevision(
            id=structured_revision_id,
            meeting_id=meeting_id,
            revision_number=2,
            format_version=2,
            content=None,
            created_by_id=actor_id,
            created_at=now,
        )
        discussion = MinutesDiscussion(
            id=discussion_id,
            meeting_id=meeting_id,
            minutes_revision_id=structured_revision_id,
            agenda_id=agenda_id,
            discussion_number=1,
            subject="Synthetic topic",
            content="Synthetic immutable discussion",
        )
        decision = MinutesDecision(
            id=decision_id,
            meeting_id=meeting_id,
            minutes_revision_id=structured_revision_id,
            discussion_id=discussion_id,
            decision_number=1,
            decision_text="Synthetic immutable decision",
        )
        session.add_all([actor, meeting, other_meeting, agenda, revision, structured_revision])
        session.flush()
        session.add(discussion)
        session.flush()
        session.add(decision)
        session.commit()

        session.add(
            MinutesReview(
                id=uuid4(),
                meeting_id=other_meeting_id,
                minutes_revision_id=revision_id,
                reviewer_user_id=actor_id,
                review_number=1,
                result=MinutesReviewResult.VALID,
                reviewed_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            MinutesDecision(
                id=uuid4(),
                meeting_id=meeting_id,
                minutes_revision_id=revision_id,
                discussion_id=discussion_id,
                decision_number=1,
                decision_text="Cross-revision link must be rejected",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            MinutesDiscussion(
                id=uuid4(),
                meeting_id=meeting_id,
                minutes_revision_id=structured_revision_id,
                agenda_id=uuid4(),
                discussion_number=2,
                content="Unknown agenda must be rejected",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                update(MinutesRevision)
                .where(MinutesRevision.id == revision_id)
                .values(content="silently replaced")
            )
            session.commit()
        session.rollback()

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(delete(MinutesRevision).where(MinutesRevision.id == revision_id))
            session.commit()
        session.rollback()
        revision = session.get(MinutesRevision, revision_id)
        assert revision is not None
        assert revision.content == "Synthetic immutable minutes"

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                update(MinutesDiscussion)
                .where(MinutesDiscussion.id == discussion_id)
                .values(content="silently replaced")
            )
            session.commit()
        session.rollback()

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(delete(MinutesDiscussion).where(MinutesDiscussion.id == discussion_id))
            session.commit()
        session.rollback()
        discussion = session.get(MinutesDiscussion, discussion_id)
        assert discussion is not None
        assert discussion.content == "Synthetic immutable discussion"

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                update(MinutesDecision)
                .where(MinutesDecision.id == decision_id)
                .values(decision_text="silently replaced")
            )
            session.commit()
        session.rollback()

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(delete(MinutesDecision).where(MinutesDecision.id == decision_id))
            session.commit()
        session.rollback()
        decision = session.get(MinutesDecision, decision_id)
        assert decision is not None
        assert decision.decision_text == "Synthetic immutable decision"

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                text(
                    "TRUNCATE TABLE decision_brief_decisions, "
                    "minutes_discussions, minutes_decisions"
                )
            )
            session.commit()
        session.rollback()

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(text("TRUNCATE TABLE minutes_revisions CASCADE"))
            session.commit()
        session.rollback()
        revision = session.get(MinutesRevision, revision_id)
        assert revision is not None
        assert revision.content == "Synthetic immutable minutes"


def test_postgres_concurrent_decision_brief_writers_append_distinct_versions(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    actor_id = uuid4()
    agenda_id = uuid4()
    revision_id = uuid4()
    discussion_id = uuid4()
    decision_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"brief-writer-{uuid4()}@example.test",
            full_name="Synthetic Decision Brief Writer",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"BRIEF-RACE-{uuid4()}",
            title="Synthetic Decision Brief race",
            meeting_date=date.today(),
            created_by_id=actor_id,
        )
        agenda = Agenda(
            id=agenda_id,
            meeting_id=meeting_id,
            agenda_number=1,
            title="Synthetic source agenda",
        )
        revision = MinutesRevision(
            id=revision_id,
            meeting_id=meeting_id,
            revision_number=1,
            format_version=2,
            content=None,
            created_by_id=actor_id,
            created_at=now,
        )
        discussion = MinutesDiscussion(
            id=discussion_id,
            meeting_id=meeting_id,
            minutes_revision_id=revision_id,
            agenda_id=agenda_id,
            discussion_number=1,
            content="Synthetic source discussion",
        )
        decision = MinutesDecision(
            id=decision_id,
            meeting_id=meeting_id,
            minutes_revision_id=revision_id,
            discussion_id=discussion_id,
            decision_number=1,
            decision_text="Synthetic source decision",
        )
        session.add_all([actor, meeting, agenda, revision])
        session.flush()
        session.add(discussion)
        session.flush()
        session.add(decision)
        session.commit()

    barrier = Barrier(2)
    brief_input = DecisionBriefVersionCreate(
        source_minutes_revision_id=revision_id,
        summary="Synthetic editorial summary",
        decisions=[DecisionBriefDecisionCreate(decision_id=decision_id, priority="Utama")],
    )

    def append_version(_: int) -> int:
        with postgres_sessions() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait()
            return create_decision_brief_version(
                session, meeting_id, actor, brief_input
            ).version_number

    with ThreadPoolExecutor(max_workers=2) as executor:
        versions = list(executor.map(append_version, (1, 2)))

    assert sorted(versions) == [1, 2]
    with postgres_sessions() as session:
        stored_versions = list(
            session.scalars(
                select(DecisionBriefVersion).where(DecisionBriefVersion.meeting_id == meeting_id)
            )
        )
        stored_decisions = list(
            session.scalars(
                select(DecisionBriefDecision).where(DecisionBriefDecision.meeting_id == meeting_id)
            )
        )
        assert len(stored_versions) == 2
        assert len(stored_decisions) == 2
        assert {item.source_decision_id for item in stored_decisions} == {decision_id}

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                update(DecisionBriefVersion)
                .where(DecisionBriefVersion.meeting_id == meeting_id)
                .values(summary="silently replaced")
            )
            session.commit()
        session.rollback()

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                delete(DecisionBriefVersion).where(DecisionBriefVersion.meeting_id == meeting_id)
            )
            session.commit()
        session.rollback()

    with postgres_sessions() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                text("TRUNCATE TABLE decision_brief_decisions, decision_brief_versions")
            )
            session.commit()
        session.rollback()


def test_postgres_decision_brief_source_fk_rejects_cross_meeting_decision(
    postgres_sessions: sessionmaker[Session],
) -> None:
    meeting_id = uuid4()
    other_meeting_id = uuid4()
    actor_id = uuid4()
    source_revision_id = uuid4()
    other_revision_id = uuid4()
    source_agenda_id = uuid4()
    other_agenda_id = uuid4()
    source_discussion_id = uuid4()
    other_discussion_id = uuid4()
    source_decision_id = uuid4()
    other_decision_id = uuid4()
    now = datetime.now(UTC)
    with postgres_sessions() as session:
        role = session.scalar(select(Role).where(Role.role_code == "SEKRETARIAT"))
        assert role is not None
        actor = User(
            id=actor_id,
            email=f"brief-fk-{uuid4()}@example.test",
            full_name="Synthetic Brief FK User",
            password_hash="synthetic-only-not-used",
            is_active=True,
        )
        actor.roles.append(role)
        meeting = Meeting(
            id=meeting_id,
            meeting_number=f"BRIEF-FK-{uuid4()}",
            title="Synthetic source meeting",
            meeting_date=date.today(),
            created_by_id=actor_id,
        )
        other_meeting = Meeting(
            id=other_meeting_id,
            meeting_number=f"BRIEF-FK-OTHER-{uuid4()}",
            title="Synthetic other source meeting",
            meeting_date=date.today(),
            created_by_id=actor_id,
        )
        source_agenda = Agenda(
            id=source_agenda_id,
            meeting_id=meeting_id,
            agenda_number=1,
            title="Synthetic source agenda",
        )
        other_agenda = Agenda(
            id=other_agenda_id,
            meeting_id=other_meeting_id,
            agenda_number=1,
            title="Synthetic other agenda",
        )
        source_revision = MinutesRevision(
            id=source_revision_id,
            meeting_id=meeting_id,
            revision_number=1,
            format_version=2,
            content=None,
            created_by_id=actor_id,
            created_at=now,
        )
        other_revision = MinutesRevision(
            id=other_revision_id,
            meeting_id=other_meeting_id,
            revision_number=1,
            format_version=2,
            content=None,
            created_by_id=actor_id,
            created_at=now,
        )
        source_discussion = MinutesDiscussion(
            id=source_discussion_id,
            meeting_id=meeting_id,
            minutes_revision_id=source_revision_id,
            agenda_id=source_agenda_id,
            discussion_number=1,
            content="Synthetic source discussion",
        )
        other_discussion = MinutesDiscussion(
            id=other_discussion_id,
            meeting_id=other_meeting_id,
            minutes_revision_id=other_revision_id,
            agenda_id=other_agenda_id,
            discussion_number=1,
            content="Synthetic other discussion",
        )
        session.add_all(
            [
                actor,
                meeting,
                other_meeting,
                source_agenda,
                other_agenda,
                source_revision,
                other_revision,
            ]
        )
        session.flush()
        session.add_all([source_discussion, other_discussion])
        session.flush()
        session.add_all(
            [
                MinutesDecision(
                    id=source_decision_id,
                    meeting_id=meeting_id,
                    minutes_revision_id=source_revision_id,
                    discussion_id=source_discussion_id,
                    decision_number=1,
                    decision_text="Synthetic source decision",
                ),
                MinutesDecision(
                    id=other_decision_id,
                    meeting_id=other_meeting_id,
                    minutes_revision_id=other_revision_id,
                    discussion_id=other_discussion_id,
                    decision_number=1,
                    decision_text="Synthetic other decision",
                ),
            ]
        )
        version = DecisionBriefVersion(
            id=uuid4(),
            meeting_id=meeting_id,
            source_minutes_revision_id=source_revision_id,
            version_number=1,
            summary="Synthetic editorial summary",
            created_by_id=actor_id,
        )
        session.add(version)
        session.commit()

        session.add(
            DecisionBriefDecision(
                brief_version_id=version.id,
                source_decision_id=other_decision_id,
                meeting_id=meeting_id,
                source_minutes_revision_id=source_revision_id,
                position=1,
                priority="Utama",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    with postgres_sessions() as session:
        assert (
            session.scalar(
                select(DecisionBriefDecision).where(
                    DecisionBriefDecision.source_decision_id == other_decision_id
                )
            )
            is None
        )
