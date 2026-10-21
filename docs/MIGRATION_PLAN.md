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
- Rapim metadata models/API cover meetings, agendas, and participants with role- and object-scoped access. Minutes revisions are append-only; version 2 stores complete discussion/decision snapshots under agendas. Review attestations remain bound to an exact revision, and the editor uses the existing revision API without real-time collaboration.
- Alembic migrations `0002_meetings_agendas`, `0003_workflow_rate_limit`, `0004_minutes_review`, `0005_versioned_minutes`, `0006_structured_minutes`, `0007_decision_brief`, and `0008_organization_scope` add meeting data, transition/rate-limit records, review attestations, versioned minutes, agenda-structured snapshots, immutable Decision Brief drafts, and empty organization-scope tables. Production migration rollout has not been verified.
- `0008_organization_scope` adds units, effective-dated user memberships, and effective-dated reporting lines. It deliberately inserts no organization data. Provisioning requires an approved unit chart and employee roster; a later controlled workflow must detect overlapping effective periods, validate hierarchy cycles, and audit changes. Downgrade refuses while any organization rows exist.
- The ORM identity metadata now matches the existing `0001_identity_sessions` email uniqueness constraint and session-user index; this alignment does not change the database schema.
- Dashboard metrics remain labeled synthetic data and are not connected to the API.

### Meeting lifecycle and login protection baseline

- `POST /api/v1/meetings/{meeting_id}/minutes-revisions` retains the legacy request `{ "content": string, "base_revision_id": UUID | null }` as version 1 and also accepts `{ "format_version": 2, "content": null, "base_revision_id": UUID | null, "discussions": [...] }`. Each discussion has an `agenda_id`, optional `subject`, nonblank `content`, and nested decisions with text and optional output, date, and action-item marker. PIC assignment, task creation, and task workflow are not implemented in this phase; unexpected assignment fields return `422`. The endpoint requires an authenticated session, CSRF header, an accessible meeting in `LIVE`, and the designated notetaker. It appends one complete snapshot and returns `201`. Version 1 text and version 2 aggregate text are capped at 1,000,000 characters; structured field lengths and list counts are bounded. A stale base returns `409`; invalid input or out-of-meeting references return `422`.
- `GET /api/v1/meetings/{meeting_id}/minutes-revisions` returns ordered history to authorized Secretariat or leadership users in meeting scope. Responses add `format_version` and `discussions`; legacy revisions retain their original `content` and have an empty discussion list, while version 2 has `content: null` and full nested data. PIC and Super Admin are denied even when they also hold another role. Unknown or inaccessible meetings return `404`.
- `POST /api/v1/meetings/{meeting_id}/minutes-reviews` accepts `{ "minutes_revision_id": UUID, "result": "VALID" | "INVALID", "review_note"?: string }`, requires an authenticated session, CSRF header, an accessible meeting in `LIVE`, the currently active revision, and the `SEKRETARIAT` role without `SUPER_ADMIN`. It returns `201` with the meeting, revision, reviewer, per-meeting review number, result, timestamp, and optional note. A stale or wrong-meeting revision returns `409`; invalid input returns `422`.
- `GET /api/v1/meetings/{meeting_id}/minutes-reviews` returns the ordered review history to an authenticated, authorized Secretariat user. Inaccessible meetings return `404`, and visible meetings return `403` to roles without review authority.
- `POST /api/v1/meetings/{meeting_id}/transition` accepts `{ "to_status": "LIVE" | "FINAL" | "ARCHIVED" }`, requires the session cookie, CSRF header, and Secretariat role, and returns the updated meeting. PIC, leaders, and Super Admin cannot transition meetings; Super Admin remains excluded even if another role is also attached.
- Allowed transitions are `DRAFT → LIVE`, `LIVE → FINAL` after the latest review is `VALID`, and `FINAL → ARCHIVED`. The service locks the meeting row and commits the status change with a `meeting_status_events` row containing actor, previous status, target status, and time. Repeated, illegal, or unreviewed finalizations return `409` without changing status or writing an event.
- Revisions are full append-only snapshots. Version 1 stores the exact submitted text; version 2 stores no duplicate text and owns child discussion/decision rows. The active revision is the greatest per-meeting sequence; no separate hash or mutable active flag is maintained. Composite foreign keys keep discussions on agendas within the same meeting and decisions within the same revision. The service validates all child references, then commits root and children atomically. Migration triggers reject update/delete; PostgreSQL also rejects `TRUNCATE`, which bypasses row-level triggers. These guards do not protect against a database owner or superuser altering the triggers; production should use a migration owner separate from a runtime role without DDL privileges. New writes must include the active `base_revision_id` (or `null` for the first revision), and service row locks serialize revision writes, review writes, and lifecycle transitions. A mismatch returns `409` rather than silently accepting a stale edit.
- `minutes_reviews.minutes_revision_id` references a revision with a composite `(meeting_id, minutes_revision_id)` foreign key, so reviews cannot point across meetings. Migration `0004` reviews are preserved with a null revision reference; they remain historical records but cannot authorize finalization. Every finalization rechecks that the latest review is `VALID` and names the active revision inside the locked transaction. A newer revision makes earlier reviews stale without changing them.
- Login reserves every request, including successful and failed attempts, in a fixed-window bucket keyed by HMAC of the normalized login identity and `request.client.host`. Default configuration is 10 attempts per 300 seconds and a 2-second PostgreSQL statement timeout. These are adjustable starting values, not universal security limits.
- Configure `LOGIN_RATE_LIMIT_HMAC_KEY` with a private random value of at least 32 characters. `429` responses include `Retry-After`; a missing key or limiter database failure returns `503` before password authentication. The limiter reads `request.client.host` and does not inspect forwarding headers. The documented local Uvicorn command disables proxy-header rewriting; behind a deployment proxy, enable it only with an explicit trusted proxy allowlist.
- The limiter stores only a keyed digest, counter, and window timestamps. Expired rows are deleted opportunistically on login and can be cleaned when idle from the repository root with `$env:PYTHONPATH = "backend"` followed by `python -m app.maintenance` in PowerShell. Schedule that command against the intended application database; it requires PostgreSQL and deletes only expired buckets.
- **Historical baseline (2026-10-15):** At that time `0005_versioned_minutes` was head. Upgrade/downgrade/re-upgrade and `alembic check` passed on a disposable PostgreSQL 16 tmpfs container; 9 PostgreSQL concurrency/constraint tests passed. Production rollout remains unverified.
- **Rollback warning:** downgrading `0004_minutes_review` drops the `minutes_reviews` table and all review attestations in it. The downgrade was exercised only on the disposable test database; do not use it after reviews contain records that must be retained. For deployed data, prefer a reviewed forward migration or a verified backup-and-restore plan.
- **Versioned-minutes rollback warning:** downgrading `0005_versioned_minutes` removes every revision and content snapshot and drops review-to-revision associations. Review rows from `0004` remain unattached after a direct downgrade to `0004`; any further downgrade through `0004` removes those review rows as well. Do not downgrade once the data is in use; use a reviewed forward migration or verified backup/restore.
- **Structured-minutes rollback warning:** `0006_structured_minutes` refuses downgrade if any `format_version=2` revision exists, so it will not silently drop structured discussions or decisions. With only version 1 rows it restores the version 1 schema while preserving legacy text and review bindings. Deployed rollback still requires a reviewed backup/restore or forward recovery plan.
- **Decision Brief rollback warning:** `0007_decision_brief` adds the composite source-decision constraint and two append-only tables. It refuses downgrade while any brief version exists. New source decisions must belong to the same meeting and exact source revision; `is_stale` is derived at read time by comparing the source revision ID to the active minutes revision. Test the migration and downgrade only in a disposable database.
- **Organization scope rollback warning:** `0008_organization_scope` creates empty organization tables without seeds. Its downgrade refuses while any unit, membership, or reporting line exists. Do not delete provisioned organization records merely to downgrade; use a reviewed forward recovery plan.

## Rapim metadata API contract

The current backend contract covers meeting metadata and the initial lifecycle transition:

| Method and path | Access and behavior |
|---|---|
| `GET /api/v1/meetings` | Authenticated Sekretariat sees all meetings; Rektor/Warek see meetings where they are creator, chairperson, notetaker, or participant. Supports bounded `limit` and non-negative `offset`. |
| `POST /api/v1/meetings` | Sekretariat, Rektor, and Warek may create a meeting. The server sets status to `DRAFT`; request bodies cannot override status. |
| `GET /api/v1/meetings/{meeting_id}` | Same object scope as the list; inaccessible or unknown meetings return `404`. |
| `POST /api/v1/meetings/{meeting_id}/agendas` | Sekretariat may manage any draft; Rektor/Warek may manage a draft they created. Agenda number is unique within its meeting. |
| `POST /api/v1/meetings/{meeting_id}/participants` | Same draft-management scope; each user can be added once per meeting. |
| `GET /api/v1/meetings/{meeting_id}/minutes-revisions` | Secretariat and authorized leadership within meeting scope; returns ordered text or structured revisions. PIC and Super Admin are denied. |
| `POST /api/v1/meetings/{meeting_id}/minutes-revisions` | Designated notetaker only, with session and CSRF, while `LIVE`; appends a revision only when `base_revision_id` matches the active revision. |
| `GET /api/v1/meetings/{meeting_id}/minutes-reviews` | Secretariat only, excluding Super Admin; returns the review history for an accessible meeting. |
| `POST /api/v1/meetings/{meeting_id}/minutes-reviews` | Secretariat only, excluding Super Admin; accessible meetings must be `LIVE`, and `minutes_revision_id` must identify the active revision. Appends an attributable review attestation. |
| `POST /api/v1/meetings/{meeting_id}/transition` | Secretariat only. `DRAFT → LIVE`, `LIVE → FINAL` with latest valid review, and `FINAL → ARCHIVED` are allowed; other transitions or missing/invalid review return `409`. |

All write routes require the authenticated session cookie and `X-CSRF-Token` matching the `sitara_csrf` cookie. PIC has no meeting metadata access and cannot read minutes content. Super Admin is denied even if another role is also attached, preserving its separation from operational Sekretariat access. Meeting responses include lifecycle status (`DRAFT`, `LIVE`, `FINAL`, `ARCHIVED`). Revision history is append-only and ordered by revision number. Review history is also ordered by review number; finalization requires its latest result to be `VALID` and its revision ID to equal the current highest revision. A newer revision invalidates prior reviews. The same Secretariat user may review and finalize. Only Secretariat may start (`DRAFT → LIVE`) or archive (`FINAL → ARCHIVED`) a meeting.

The data path is `Meeting 1:N Agenda`, `Meeting 1:N MinutesRevision`, `MinutesRevision 1:N MinutesDiscussion`, `Agenda 1:N MinutesDiscussion`, `MinutesDiscussion 1:N MinutesDecision`, `MinutesRevision 1:N MinutesReview`, `Meeting 1:N DecisionBriefVersion`, and `DecisionBriefVersion 1:N DecisionBriefDecision`. Brief entries reference the exact source decision in the brief's source revision; their editorial priority and notes do not duplicate decision text. Action items remain a future module and must reference decisions through a non-unique foreign key because one decision may yield zero or multiple tasks.
