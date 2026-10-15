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
- A `SELESAI` transition cannot happen without the required verification record.
- A decision marked `is_action_item = false` must not silently create a task.
- A task update cannot attach a document belonging to another task or meeting.
- A user cannot assign tasks outside their permitted organizational scope.
- Unauthenticated and disabled users cannot access protected endpoints.

## Database tests

Use a dedicated disposable PostgreSQL database. Run migrations from an empty database in CI. Never run tests that delete or mutate records against production.

## Test quality review

For each changed test, review:

- Does it assert observable results rather than implementation details only?
- Would it fail if the authorization check were removed?
- Does it include at least one invalid/unauthorized input where relevant?
- Is the fixture representative without containing confidential data?
- Are time, random values, and external dependencies deterministic or controlled?

Coverage percentages are guardrails, not proof of correctness. For critical authorization/business rules, consider mutation testing after the initial feature suite is stable.
