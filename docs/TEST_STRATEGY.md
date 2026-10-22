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
- The minutes editor loads only authenticated meeting/revision API data, uses the active revision ID as `base_revision_id`, disables edits for non-notetakers/final meetings, and retains a draft after `409` until the user explicitly loads the newest revision.
- A `SELESAI` transition cannot happen without the required verification record.
- A decision marked `is_action_item = false` must not silently create a task.
- A task update cannot attach a document belonging to another task or meeting.
- A user cannot assign tasks outside their permitted organizational scope.
- Organization authorization rejects inactive users/units, missing or expired memberships, ended reporting lines, unrelated leaders, unassigned PICs, and Super Admin accounts even when mixed with Secretariat.
- Secretariat/PIC assignment checks use current database roles and require the target PIC to be active with a current unit membership. Reporting scope traverses only currently effective lines and active members and fails closed when the manager's reachable reporting graph contains a cycle.
- Unauthenticated and disabled users cannot access protected endpoints.

## Database tests

Use a dedicated disposable PostgreSQL database. Run migrations from an empty database in CI. Never run tests that delete or mutate records against production.

`backend/tests/test_postgres_concurrency.py` is skipped unless `SITARA_TEST_DATABASE_URL` points to a disposable PostgreSQL database at migration head `0011_evidence_scan_quarantine`. It verifies the atomic login bucket upsert, expired-row cleanup, serialization of concurrent meeting transitions, minutes revisions/reviews/finalization, Decision Brief version creation, Action Item constraints, and evidence scan quarantine/append-only guards. Fixtures use synthetic records; the disposable test database can retain append-only rows until it is discarded. Do not point this variable at the development Compose database.

## Test quality review

For each changed test, review:

- Does it assert observable results rather than implementation details only?
- Would it fail if the authorization check were removed?
- Does it include at least one invalid/unauthorized input where relevant?
- Is the fixture representative without containing confidential data?
- Are time, random values, and external dependencies deterministic or controlled?

Coverage percentages are guardrails, not proof of correctness. For critical authorization/business rules, consider mutation testing after the initial feature suite is stable.

## Previous full PostgreSQL verification baseline (2026-10-15)

- Backend full suite with `SITARA_TEST_DATABASE_URL` pointing at the disposable PostgreSQL 16 database: 53 passed, 90.22% coverage, two Starlette/AnyIO deprecation warnings.
- PostgreSQL integration suite: 9 passed. Alembic upgrade to `0005_versioned_minutes`, downgrade to `0004`, re-upgrade, and `alembic check` passed. SQLite migration tests cover historical review preservation and append-only trigger behavior.
- `ruff check .`, feature-file `ruff format --check`, and `mypy app` passed. Repository-wide `ruff format --check .` still flags the pre-existing local `0003_meeting_workflow_login_rate_limit.py`; that migration was not reformatted as part of this feature.
- Frontend coverage tests: 2 passed; lint, format check, TypeScript build/type check, and Vite production build passed.
- `pip check`, `pip-audit --strict --skip-editable .`, and `npm audit --audit-level=high` passed with no dependency vulnerabilities. Gitleaks found no leaks in scanned source, tests, docs, and configuration. Semgrep was unavailable in this environment and was not run.

## Minutes editor verification (2026-10-21)

- Backend full suite using the isolated environment under `backend/.audit-venv-codex-20261015`: 44 passed, 9 PostgreSQL integration tests skipped because `SITARA_TEST_DATABASE_URL` was not set, 89.64% coverage, and two Starlette/AnyIO deprecation warnings. PostgreSQL migration/concurrency checks were not rerun for this frontend change; the 2026-10-15 PostgreSQL results above are the previous verified baseline.
- `ruff check .`, `ruff format --check app/api/routes/auth.py tests/test_auth.py`, `mypy app`, and `pip check` passed. `pip-audit --strict --skip-editable .` found no known vulnerabilities. Repository-wide `ruff format --check .` still reports the pre-existing formatting issue in `migrations/versions/0003_meeting_workflow_login_rate_limit.py`.
- Frontend coverage tests: 13 passed (82.47% statements, 78.13% branches, 86.36% functions, 86.6% lines). ESLint, Prettier check, TypeScript build, Vite production build, and `npm audit --audit-level=high` passed; npm audit found no vulnerabilities.
- Gitleaks scanned the changed source, test, documentation, README, and project context paths with redaction enabled; no leaks were found. Semgrep was not installed in this workspace and was not run.
- `git diff --check` passed. No database schema, endpoint, or request/response schema changes were made. The CSRF cookie scope was broadened to `/` for the root SPA, and login/logout expire any legacy `/api/v1` CSRF cookie.

## Organization scope verification (2026-10-21)

- Backend `pytest -q`: 63 passed, 12 PostgreSQL-only tests skipped without a configured `SITARA_TEST_DATABASE_URL`, 89.94% total coverage, and five deprecation warnings. The PostgreSQL suite was run separately against a disposable PostgreSQL 16 container on `tmpfs`: 12 passed.
- PostgreSQL migration verification upgraded an empty database through `0008_organization_scope`, passed `alembic check`, downgraded the empty organization scope to `0007_decision_brief`, and upgraded to head again. SQLite migration tests verified empty downgrade safety, refusal to downgrade when an organization row exists, and preservation of that row.
- `ruff check .`, `mypy app`, `pip check`, and formatting checks for all changed Python files passed. Repository-wide `ruff format --check .` still fails only on the pre-existing formatting issue in `migrations/versions/0003_meeting_workflow_login_rate_limit.py`.
- `git diff --check` passed. No frontend files or dependencies were changed, so frontend tests/build and dependency audit were not run for this stage. An independent read-only authorization/migration review found no bypass; it identified the need to keep organization provisioning gated on cycle/overlap validation and audit logging.

## Evidence hardening and backend dependency verification (2026-10-22)

- The backend manifest requires FastAPI `>=0.140.8` and pytest `>=9.0.3`; there is no backend lockfile. The system Python had FastAPI 0.115.0, Starlette 0.38.6, and pytest 8.3.3, so it did not satisfy the declared test environment. The previously failing login rate-limit test passed in the existing isolated environment with FastAPI 0.140.8, Starlette 1.3.1, and pytest 9.0.3; no dependency upgrade or test change was needed.
- Backend `pytest -q`: 115 passed, 14 PostgreSQL-only tests skipped because `SITARA_TEST_DATABASE_URL` was not configured, 85.15% coverage, and six warnings. PostgreSQL migration `0011` and trigger behavior were not verified in this run.
- `ruff check .`, `mypy app`, `pip check`, and `ruff format --check app tests` passed. Repository-wide `ruff format --check .` still reports the pre-existing formatting issue in `migrations/versions/0003_meeting_workflow_login_rate_limit.py`.
- No local PostgreSQL service/client was available, and the Docker CLI could not connect to a daemon. The Action Item evidence scan-result service has no configured antivirus engine or worker; files remain quarantined as `PENDING`, and downloads fail closed until a matching trusted `CLEAN` result exists.
