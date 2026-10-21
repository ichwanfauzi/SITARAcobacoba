# Architecture Decision Records (initial)

## ADR-001: Modular monolith

**Decision:** Start with one FastAPI backend and one React frontend, structured into modules.

**Reason:** Fits a solo developer, reduces deployment complexity, and preserves clear boundaries without premature microservices.

## ADR-002: PostgreSQL

**Decision:** Use PostgreSQL for relational business data and transactional consistency.

**Reason:** SITARA has connected records, access controls, workflow transitions, and audit history.

## ADR-003: One notetaker writes during a live meeting

**Decision:** During a live meeting, only the designated notetaker may edit meeting notes; authorized leaders/viewers are read-only.

**Reason:** Matches the specified workflow and reduces concurrent-edit conflicts in the first release.

## ADR-004: Official status is controlled by Secretariat

**Decision:** Only authorized Secretariat users may change an action item's official status. PIC and leaders submit progress updates; they do not directly change the official status.

**Reason:** Establishes a single accountable workflow for official monitoring status. This must be enforced server-side and tested.

## ADR-005: Meeting lifecycle and login attempt storage

**Decision:** Secretariat alone may transition a meeting. Persist each successful transition in `meeting_status_events` in the same transaction as the meeting update, with a row lock to serialize concurrent transitions. Permit `DRAFT → LIVE`, `LIVE → FINAL` after the latest valid review of the active minutes revision, and `FINAL → ARCHIVED`; reject all other transitions.

**Reason:** Status changes need attributable history. Minutes-review data and its limits are defined in ADR-006.

**Decision:** Store login attempt buckets in PostgreSQL using an HMAC digest of normalized login identity plus the ASGI client address. Use a fixed-window atomic upsert, a configured timeout, and fail closed with `503` if the limiter cannot operate. Delete expired rows during login and provide an operator cleanup command for idle periods. The supported local Uvicorn command disables proxy-header rewriting; deployments behind a proxy must explicitly allowlist trusted proxy addresses before enabling forwarded headers.

**Reason:** PostgreSQL coordinates workers/instances without adding Redis. HMAC prevents the bucket table from exposing raw email/IP pairs; expiry limits their retention. The default 10 attempts per 300 seconds is a configurable starting point that requires operational tuning.

## ADR-006: Minutes review attestation and finalization

**Decision:** Only an active user with the `SEKRETARIAT` role and without `SUPER_ADMIN` may record a minutes review. A reviewer may also finalize the meeting. Store each review as a separate record with the meeting, reviewer, sequence number, result, UTC timestamp, and optional note. The newest review controls finalization; `INVALID` blocks finalization until another review records `VALID`. Review and finalization lock the meeting row. Each review insert commits as one transaction; finalization commits the meeting update and status event together.

**Historical limitation (addressed by ADR-007):** Migration `0004` review records predate versioned minutes and have no revision reference. They remain in history after `0005`, but cannot satisfy finalization.

## ADR-007: Versioned minutes and revision-bound reviews

**Decision:** Store complete minutes snapshots in append-only `minutes_revisions` rows with stable UUID, meeting, per-meeting sequence, raw text content, author, and UTC creation time. The highest sequence is the active revision. No separate content hash or mutable “current revision” flag is used. Migration triggers reject revision updates and deletes; PostgreSQL also rejects `TRUNCATE`, which bypasses row-level triggers. Application writes append only. These guards protect against ordinary table mutations, not a database owner or superuser who can alter the triggers; production should separate the migration owner from a runtime role without DDL privileges.

During `LIVE`, only the designated notetaker may append a revision. Each write supplies `base_revision_id` for the active revision (or `null` for the first revision). The service locks the meeting row, compares that base with the current highest revision, and returns `409` for stale concurrent writes. Content is stored as submitted; the API rejects blank text and limits it to 1,000,000 characters.

Each new review includes `minutes_revision_id`. A composite foreign key binds `(meeting_id, minutes_revision_id)` to a revision of that same meeting. Review creation locks the meeting and accepts only its active revision. Finalization takes the same lock and requires the latest review to be `VALID` and bound to the active revision. A later revision therefore invalidates prior reviews without changing the review history. Final status and its status event remain one transaction. The reviewer may finalize; only Secretariat without `SUPER_ADMIN` may review, start (`DRAFT → LIVE`), finalize, or archive (`FINAL → ARCHIVED`).

Full minutes content is returned only to authorized Secretariat or leadership users within meeting scope. PIC and Super Admin are denied even if they also hold another role. The first-stage editor uses these revision endpoints for plain-text snapshots; it does not add structured agenda editing or real-time collaboration.

**Migration impact:** `0005_versioned_minutes` adds revision rows and a nullable review reference so existing `0004` attestations are preserved without being silently assigned to a revision. Historical unbound reviews cannot finalize a meeting. Downgrade to `0004` drops all revision content and removes review-to-revision associations while preserving review rows; a further downgrade through `0004` removes review history. Production recovery should use a reviewed forward migration or verified backup/restore, never an unreviewed downgrade.

## 2026-10-14 — Product/UX/architecture documentation baseline

- Added `docs/PRD.md`, `docs/system_design.md`, `docs/architecture.md`, and `docs/agents.md` as draft v1.0 sources for business processes, UI patterns, architecture, and AI-agent governance.
- Root `AGENTS.md` is the tool-discoverable concise instruction entrypoint and links to `docs/agents.md`; a lower-case root `agents.md` is intentionally not created because Windows filesystems are commonly case-insensitive.
- Important schema correction before implementation: product requirements allow one decision to generate multiple action items. The draft SQL currently marks `action_items.decision_id` as unique, so that constraint must be removed in the final ORM/Alembic schema.
- The styling/PDF implementation details remain explicitly provisional where the starter does not yet have the associated dependencies or where official template fidelity needs a proof-of-concept.
