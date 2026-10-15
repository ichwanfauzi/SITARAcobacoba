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
- No Alembic migration has been generated or applied.
- No authentication, RBAC, business API, or feature UI is claimed complete.
