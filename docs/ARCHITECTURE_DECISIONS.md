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

## 2026-10-14 — Product/UX/architecture documentation baseline

- Added `docs/PRD.md`, `docs/system_design.md`, `docs/architecture.md`, and `docs/agents.md` as draft v1.0 sources for business processes, UI patterns, architecture, and AI-agent governance.
- Root `AGENTS.md` is the tool-discoverable concise instruction entrypoint and links to `docs/agents.md`; a lower-case root `agents.md` is intentionally not created because Windows filesystems are commonly case-insensitive.
- Important schema correction before implementation: product requirements allow one decision to generate multiple action items. The draft SQL currently marks `action_items.decision_id` as unique, so that constraint must be removed in the final ORM/Alembic schema.
- The styling/PDF implementation details remain explicitly provisional where the starter does not yet have the associated dependencies or where official template fidelity needs a proof-of-concept.
