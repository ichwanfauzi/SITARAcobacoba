# SITARA — Project Context

## Purpose
SITARA manages Rapim meetings, live minutes, decisions, Decision Briefs, action items, PIC assignments, follow-up monitoring, documents, notifications, and audit history.

## Selected foundation
This workspace uses the engineering starter from `sitara_starter1.zip` as the base: React + TypeScript + Vite, FastAPI, SQLAlchemy 2.x, Alembic, and PostgreSQL. The legacy prototype concepts are preserved separately under `backend/app/models/legacy_prototype.py` for migration planning only.

## Important implementation status
This is a migration workspace, not a complete production application. It includes health and authentication APIs, identity/role/session models, and a role-scoped Rapim metadata foundation for meetings, agendas, participants, and versioned minutes. Meeting metadata and lifecycle writes require an authenticated server-side session and a matching CSRF cookie/header pair. Login rate limiting uses PostgreSQL-backed HMAC buckets; meeting transitions are recorded in `meeting_status_events` and restricted to Secretariat. Minutes are append-only snapshots; only the designated notetaker can add one during `LIVE`. Secretariat reviews name an exact revision, and finalization requires the latest valid review to match the active revision. PIC and Super Admin cannot read full minutes. The first-stage frontend editor uses the existing session, meeting, and revision APIs; account provisioning, full RBAC/organizational scope, structured agenda-by-agenda editing, real-time collaboration, decisions, and remaining business workflows are not implemented. Unit/API tests use isolated SQLite; PostgreSQL migration and concurrency checks use a disposable test container. Production migration rollout has not been verified.

## Source-of-truth rules
1. Inspect current source before changing it.
2. `docs/sitara_schema_v1_draft.sql` is a draft reference, not an applied schema.
3. Do not connect legacy models to the production database until the draft schema and migration strategy are reviewed.
4. Never commit `.env`, local databases, `.venv`, `node_modules`, build artifacts, or real documents.
5. Only claim tests pass when actually run.

## Recommended next steps
1. Add a supported account-provisioning path and complete RBAC/organizational-scope policies.
2. Add structured agenda-linked minutes content after its data model and review workflow are agreed.
3. Add decisions and action items from structured meeting data.
4. Add Decision Brief workflow, approvals, progress, documents, notifications, a shared audit log, and reports.
5. Connect the dashboard to authorized APIs after their response contracts are stable.
