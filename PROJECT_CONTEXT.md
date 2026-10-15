# SITARA — Project Context

## Purpose
SITARA manages Rapim meetings, live minutes, decisions, Decision Briefs, action items, PIC assignments, follow-up monitoring, documents, notifications, and audit history.

## Selected foundation
This workspace uses the engineering starter from `sitara_starter1.zip` as the base: React + TypeScript + Vite, FastAPI, SQLAlchemy 2.x, Alembic, and PostgreSQL. The legacy prototype concepts are preserved separately under `backend/app/models/legacy_prototype.py` for migration planning only.

## Important implementation status
This is a migration workspace, not a complete production application. It now includes a health endpoint, an authentication API foundation, identity/role/session models, an initial Alembic migration, and a placeholder frontend. Account provisioning, complete RBAC, business workflows, PostgreSQL migration verification, and frontend feature pages still require implementation and tests. Local auth tests currently use isolated SQLite because the Docker daemon is unavailable in the development environment.

## Source-of-truth rules
1. Inspect current source before changing it.
2. `docs/sitara_schema_v1_draft.sql` is a draft reference, not an applied schema.
3. Do not connect legacy models to the production database until the draft schema and migration strategy are reviewed.
4. Never commit `.env`, local databases, `.venv`, `node_modules`, build artifacts, or real documents.
5. Only claim tests pass when actually run.

## Recommended next steps
1. Run the initial migration against an isolated PostgreSQL test database and add a supported account-provisioning path.
2. Implement and test server-side RBAC, object-level permissions, and session security hardening.
3. Implement meetings and live notes.
4. Build decisions and action items from structured meeting data.
5. Add Decision Brief workflow, approvals, progress, documents, notifications, audit log, and reports.
6. Build React pages and API integration in feature slices with tests.
