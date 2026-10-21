# SITARA — Migration Plan from Prototype to Modular Starter

## Decision
Use the clean engineering starter as the active application foundation. Keep the legacy prototype as a reference for existing business concepts and UI behavior; do not copy it wholesale because its SQLite-era models and auth assumptions do not match the PostgreSQL target design.

## Legacy concepts identified
- User and role field
- Meeting
- MeetingNote
- Decision
- DecisionBrief
- ActionItem
- AuditLog (present in legacy prototype; needs a dedicated target implementation)

## Target modular layout
```text
backend/app/
  api/routes/       # HTTP endpoints only
  core/             # settings, security, permissions
  db/               # session, base, migrations integration
  models/           # SQLAlchemy models
  schemas/          # Pydantic request/response contracts
  services/         # business workflows
  repositories/     # persistence queries where useful
  tests/            # API/service/model tests
frontend/src/
  app/              # router and app shell
  components/       # shared UI
  features/         # meetings, minutes, decisions, action-items, briefs
  lib/              # API client and utilities
  types/            # shared frontend types
```

## Mapping guide
| Legacy prototype | Target design direction | Notes |
|---|---|---|
| `User.role` | `users` + `roles` + `user_roles` | Enforce permission checks server-side; do not trust role sent by frontend. |
| `Meeting` | `meetings`, `meeting_participants`, `agendas` | Preserve lifecycle and designated notetaker rules. |
| `MeetingNote` | `discussion_notes` or approved minutes tables | Keep one source of truth; clarify edit/version rules. |
| `Decision` | `decisions` | Decisions may or may not create action items. |
| `DecisionBrief` | `decision_briefs` linked to meeting and decisions | Treat as generated/reviewable document, not duplicate free text. |
| `ActionItem` | `action_items`, assignments, progress updates | Keep official status controlled by Secretariat per ADR. |
| `AuditLog` | `audit_logs` | Append-only history, record actor and entity; avoid sensitive payloads. |

## Required migration gates
1. Validate business rules and role matrix with the owner.
2. Review `sitara_schema_v1_draft.sql`; decide UUID strategy, constraints, and indexes.
3. Implement Alembic initial migration; do not execute against production during development setup.
4. Add negative authorization tests before exposing endpoints.
5. Port one vertical slice at a time: meetings -> live notes -> decisions -> action items -> brief -> progress/approval -> documents/notifications/audit.
6. Rebuild UI feature-by-feature; verify API contracts and responsive/accessibility behavior.
7. Only then plan import of existing SQLite/demo data, with backup and dry-run validation.

## Explicitly not done in this workspace
- No prototype frontend pages have been copied because the uploaded ZIP did not contain those prototype source files; the current `SITARA` GitHub repository is a separate source and must be imported selectively in a later verified step.
- No production SQLAlchemy models are registered from `legacy_prototype.py`.
- Authentication/session foundations and the initial identity migration exist; account provisioning and complete RBAC are still missing.
- Rapim metadata models/API cover meetings, agendas, and participants with role- and object-scoped access. Backend minutes revisions are append-only and review attestations point at a specific revision; a first-stage frontend editor uses the revision API without real-time collaboration or structured agenda editing.
- Alembic migrations `0002_meetings_agendas`, `0003_workflow_rate_limit`, `0004_minutes_review`, and `0005_versioned_minutes` add meeting data, transition/rate-limit records, review attestations, and versioned minutes. Production migration rollout has not been verified.
- The ORM identity metadata now matches the existing `0001_identity_sessions` email uniqueness constraint and session-user index; this alignment does not change the database schema.
- Dashboard metrics remain labeled synthetic data and are not connected to the API.

### Meeting lifecycle and login protection baseline

- `POST /api/v1/meetings/{meeting_id}/minutes-revisions` accepts `{ "content": string, "base_revision_id": UUID | null }`, requires an authenticated session, CSRF header, an accessible meeting in `LIVE`, and the designated notetaker. It appends a revision and returns `201` with its stable ID, sequence, content, author, and timestamp. Content must contain non-whitespace text and is limited to 1,000,000 characters. A stale base revision returns `409`; invalid input returns `422`.
- `GET /api/v1/meetings/{meeting_id}/minutes-revisions` returns the ordered revision history, including content, to authorized Secretariat or leadership users in meeting scope. PIC and Super Admin are denied even when they also hold another role. Unknown or inaccessible meetings return `404`.
- `POST /api/v1/meetings/{meeting_id}/minutes-reviews` accepts `{ "minutes_revision_id": UUID, "result": "VALID" | "INVALID", "review_note"?: string }`, requires an authenticated session, CSRF header, an accessible meeting in `LIVE`, the currently active revision, and the `SEKRETARIAT` role without `SUPER_ADMIN`. It returns `201` with the meeting, revision, reviewer, per-meeting review number, result, timestamp, and optional note. A stale or wrong-meeting revision returns `409`; invalid input returns `422`.
- `GET /api/v1/meetings/{meeting_id}/minutes-reviews` returns the ordered review history to an authenticated, authorized Secretariat user. Inaccessible meetings return `404`, and visible meetings return `403` to roles without review authority.
- `POST /api/v1/meetings/{meeting_id}/transition` accepts `{ "to_status": "LIVE" | "FINAL" | "ARCHIVED" }`, requires the session cookie, CSRF header, and Secretariat role, and returns the updated meeting. PIC, leaders, and Super Admin cannot transition meetings; Super Admin remains excluded even if another role is also attached.
- Allowed transitions are `DRAFT → LIVE`, `LIVE → FINAL` after the latest review is `VALID`, and `FINAL → ARCHIVED`. The service locks the meeting row and commits the status change with a `meeting_status_events` row containing actor, previous status, target status, and time. Repeated, illegal, or unreviewed finalizations return `409` without changing status or writing an event.
- Revisions store the exact submitted text as append-only snapshots. The active revision is the greatest per-meeting sequence; no separate hash or mutable active flag is maintained. Migration triggers reject update/delete; PostgreSQL also rejects `TRUNCATE`, which bypasses row-level triggers. These guards do not protect against a database owner or superuser altering the triggers; production should use a migration owner separate from a runtime role without DDL privileges. New writes must include the active `base_revision_id` (or `null` for the first revision), and service row locks serialize revision writes, review writes, and lifecycle transitions. A mismatch returns `409` rather than silently accepting a stale edit.
- `minutes_reviews.minutes_revision_id` references a revision with a composite `(meeting_id, minutes_revision_id)` foreign key, so reviews cannot point across meetings. Migration `0004` reviews are preserved with a null revision reference; they remain historical records but cannot authorize finalization. Every finalization rechecks that the latest review is `VALID` and names the active revision inside the locked transaction. A newer revision makes earlier reviews stale without changing them.
- Login reserves every request, including successful and failed attempts, in a fixed-window bucket keyed by HMAC of the normalized login identity and `request.client.host`. Default configuration is 10 attempts per 300 seconds and a 2-second PostgreSQL statement timeout. These are adjustable starting values, not universal security limits.
- Configure `LOGIN_RATE_LIMIT_HMAC_KEY` with a private random value of at least 32 characters. `429` responses include `Retry-After`; a missing key or limiter database failure returns `503` before password authentication. The limiter reads `request.client.host` and does not inspect forwarding headers. The documented local Uvicorn command disables proxy-header rewriting; behind a deployment proxy, enable it only with an explicit trusted proxy allowlist.
- The limiter stores only a keyed digest, counter, and window timestamps. Expired rows are deleted opportunistically on login and can be cleaned when idle from the repository root with `$env:PYTHONPATH = "backend"` followed by `python -m app.maintenance` in PowerShell. Schedule that command against the intended application database; it requires PostgreSQL and deletes only expired buckets.
- Migration `0005_versioned_minutes` is the current head. On 2026-10-15, upgrade to head, downgrade to `0004`, verification that the revision table/reference column were removed, re-upgrade, and `alembic check` all passed on a disposable PostgreSQL 16 container backed only by tmpfs. The PostgreSQL concurrency/constraint suite passed 9 tests; the full backend suite passed 53 tests at 90.22% coverage with two dependency deprecation warnings. A SQLite migration test also confirmed that a pre-`0005` review remains in history with a null revision reference and cannot be silently assigned. Production rollout remains unverified.
- **Rollback warning:** downgrading `0004_minutes_review` drops the `minutes_reviews` table and all review attestations in it. The downgrade was exercised only on the disposable test database; do not use it after reviews contain records that must be retained. For deployed data, prefer a reviewed forward migration or a verified backup-and-restore plan.
- **Versioned-minutes rollback warning:** downgrading `0005_versioned_minutes` removes every revision and content snapshot and drops review-to-revision associations. Review rows from `0004` remain unattached after a direct downgrade to `0004`; any further downgrade through `0004` removes those review rows as well. Do not downgrade once the data is in use; use a reviewed forward migration or verified backup/restore.

## Rapim metadata API contract

The current backend contract covers meeting metadata and the initial lifecycle transition:

| Method and path | Access and behavior |
|---|---|
| `GET /api/v1/meetings` | Authenticated Sekretariat sees all meetings; Rektor/Warek see meetings where they are creator, chairperson, notetaker, or participant. Supports bounded `limit` and non-negative `offset`. |
| `POST /api/v1/meetings` | Sekretariat, Rektor, and Warek may create a meeting. The server sets status to `DRAFT`; request bodies cannot override status. |
| `GET /api/v1/meetings/{meeting_id}` | Same object scope as the list; inaccessible or unknown meetings return `404`. |
| `POST /api/v1/meetings/{meeting_id}/agendas` | Sekretariat may manage any draft; Rektor/Warek may manage a draft they created. Agenda number is unique within its meeting. |
| `POST /api/v1/meetings/{meeting_id}/participants` | Same draft-management scope; each user can be added once per meeting. |
| `GET /api/v1/meetings/{meeting_id}/minutes-revisions` | Secretariat and authorized leadership within meeting scope; returns ordered full-text revisions. PIC and Super Admin are denied. |
| `POST /api/v1/meetings/{meeting_id}/minutes-revisions` | Designated notetaker only, with session and CSRF, while `LIVE`; appends a revision only when `base_revision_id` matches the active revision. |
| `GET /api/v1/meetings/{meeting_id}/minutes-reviews` | Secretariat only, excluding Super Admin; returns the review history for an accessible meeting. |
| `POST /api/v1/meetings/{meeting_id}/minutes-reviews` | Secretariat only, excluding Super Admin; accessible meetings must be `LIVE`, and `minutes_revision_id` must identify the active revision. Appends an attributable review attestation. |
| `POST /api/v1/meetings/{meeting_id}/transition` | Secretariat only. `DRAFT → LIVE`, `LIVE → FINAL` with latest valid review, and `FINAL → ARCHIVED` are allowed; other transitions or missing/invalid review return `409`. |

All write routes require the authenticated session cookie and `X-CSRF-Token` matching the `sitara_csrf` cookie. PIC has no meeting metadata access and cannot read minutes content. Super Admin is denied even if another role is also attached, preserving its separation from operational Sekretariat access. Meeting responses include lifecycle status (`DRAFT`, `LIVE`, `FINAL`, `ARCHIVED`). Revision history is append-only and ordered by revision number. Review history is also ordered by review number; finalization requires its latest result to be `VALID` and its revision ID to equal the current highest revision. A newer revision invalidates prior reviews. The same Secretariat user may review and finalize. Only Secretariat may start (`DRAFT → LIVE`) or archive (`FINAL → ARCHIVED`) a meeting.

The data path is `Meeting 1:N Agenda`, `Meeting 1:N MinutesRevision`, `MinutesRevision 1:N MinutesReview`, and `Meeting N:M User` through `MeetingParticipant`. The next notes/decisions slice should structure content under agendas and attach decisions to discussions, then action items to decisions with a non-unique decision foreign key, preserving the requirement that one decision can yield zero or multiple tasks. These downstream entities are not part of migrations `0002` through `0005`.
