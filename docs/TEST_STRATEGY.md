# SITARA Test Strategy

## TDD cycle

1. Write a test from the acceptance criterion before implementing the behavior.
2. Run it and confirm it fails for the expected reason (Red).
3. Implement the smallest correct change (Green).
4. Refactor and rerun focused tests and the full regression suite.
5. Review the test itself: assertions must fail for plausible incorrect implementations.

## Layers

- Unit tests: pure business rules, status transitions, validators, and permission predicates.
- API tests: HTTP status, request/response schema, validation failures, and authorization failures.
- Integration tests: database transactions, constraints, migration application, notifications, and document metadata.
- End-to-end tests: representative journeys for Secretariat, leadership, and PIC.
- Security tests: direct URL/API access, object ID substitution, privilege escalation, upload abuse, and session protections.

## Important negative tests

- PIC cannot fetch full minutes or restricted Decision Briefs, even with a known UUID.
- PIC and leadership cannot directly mutate the official task status.
- Only active, authorized Secretariat accounts can perform an official status transition.
- Only Secretariat can record a minutes review; Super Admin remains denied even when also assigned Secretariat.
- `LIVE → FINAL` requires the latest `VALID` minutes review to name the active revision; a missing, invalid, or stale review must block without changing meeting status or writing a status event.
- Only the designated notetaker can append minutes revisions during `LIVE`; PIC and Super Admin cannot retrieve full revision content.
- A stale `base_revision_id` and a review of a non-active revision are rejected. Composite database constraints prevent binding a review to another meeting's revision.
- Revision creation, review, and finalization serialize on the meeting row in PostgreSQL. Concurrent stale writers, revision/review races, revision/finalization races, and duplicate finalizations must preserve the active-revision review invariant.
- Database triggers reject revision update/delete; PostgreSQL also rejects `TRUNCATE`. Tests verify row mutation guards on SQLite migrations and all three operations on PostgreSQL.
- A `SELESAI` transition cannot happen without the required verification record.
- A decision marked `is_action_item = false` must not silently create a task.
- A task update cannot attach a document belonging to another task or meeting.
- A user cannot assign tasks outside their permitted organizational scope.
- Unauthenticated and disabled users cannot access protected endpoints.

## Database tests

Use a dedicated disposable PostgreSQL database. Run migrations from an empty database in CI. Never run tests that delete or mutate records against production.

`backend/tests/test_postgres_concurrency.py` is skipped unless `SITARA_TEST_DATABASE_URL` points to a disposable PostgreSQL database at migration head `0005_versioned_minutes`. It verifies the atomic login bucket upsert, expired-row cleanup, and serialization of concurrent meeting transitions, revision creation, review, and finalization. Fixtures use synthetic records; the disposable test database can retain append-only revision rows until it is discarded. Do not point this variable at the development Compose database.

## Test quality review

For each changed test, review:

- Does it assert observable results rather than implementation details only?
- Would it fail if the authorization check were removed?
- Does it include at least one invalid/unauthorized input where relevant?
- Is the fixture representative without containing confidential data?
- Are time, random values, and external dependencies deterministic or controlled?

Coverage percentages are guardrails, not proof of correctness. For critical authorization/business rules, consider mutation testing after the initial feature suite is stable.

## Current verification baseline (2026-10-15)

- Backend full suite with `SITARA_TEST_DATABASE_URL` pointing at the disposable PostgreSQL 16 database: 53 passed, 90.22% coverage, two Starlette/AnyIO deprecation warnings.
- PostgreSQL integration suite: 9 passed. Alembic upgrade to `0005_versioned_minutes`, downgrade to `0004`, re-upgrade, and `alembic check` passed. SQLite migration tests cover historical review preservation and append-only trigger behavior.
- `ruff check .`, feature-file `ruff format --check`, and `mypy app` passed. Repository-wide `ruff format --check .` still flags the pre-existing local `0003_meeting_workflow_login_rate_limit.py`; that migration was not reformatted as part of this feature.
- Frontend coverage tests: 2 passed; lint, format check, TypeScript build/type check, and Vite production build passed.
- `pip check`, `pip-audit --strict --skip-editable .`, and `npm audit --audit-level=high` passed with no dependency vulnerabilities. Gitleaks found no leaks in scanned source, tests, docs, and configuration. Semgrep was unavailable in this environment and was not run.
