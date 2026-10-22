"""Organization-aware authorization helpers for future task workflows."""

from collections import defaultdict, deque
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.core.roles import (
    MEETING_LEADER_ROLES,
    PIC_ROLE,
    SECRETARIAT_ROLE,
    SUPER_ADMIN_ROLE,
)
from app.models.auth import Role, User, user_roles
from app.models.organization import OrganizationUnit, ReportingLine, UserUnitMembership


def _effective_at(at: datetime | None) -> datetime:
    value = at or datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Authorization time must include a timezone")
    return value.astimezone(UTC)


def _active_user(session: Session, user_id: UUID) -> bool:
    return session.scalar(select(User.is_active).where(User.id == user_id)) is True


def _role_codes(session: Session, user_id: UUID) -> set[str]:
    return set(
        session.scalars(
            select(Role.role_code)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
        )
    )


def is_active_secretariat(session: Session, user: User) -> bool:
    """Return true only for an active operational Secretariat account."""
    if not _active_user(session, user.id):
        return False
    roles = _role_codes(session, user.id)
    return SECRETARIAT_ROLE in roles and SUPER_ADMIN_ROLE not in roles


def has_active_unit_membership(
    session: Session,
    user_id: UUID,
    unit_id: UUID | None = None,
    *,
    at: datetime | None = None,
) -> bool:
    """Check an effective membership, active account, and active unit at one instant."""
    instant = _effective_at(at)
    statement = (
        select(UserUnitMembership.id)
        .join(User, User.id == UserUnitMembership.user_id)
        .join(OrganizationUnit, OrganizationUnit.id == UserUnitMembership.unit_id)
        .where(
            UserUnitMembership.user_id == user_id,
            User.is_active.is_(True),
            OrganizationUnit.is_active.is_(True),
            UserUnitMembership.valid_from <= instant,
            (UserUnitMembership.valid_until.is_(None)) | (UserUnitMembership.valid_until > instant),
        )
        .limit(1)
    )
    if unit_id is not None:
        statement = statement.where(UserUnitMembership.unit_id == unit_id)
    return session.scalar(statement) is not None


def is_in_reporting_scope(
    session: Session,
    manager_user_id: UUID,
    subordinate_user_id: UUID,
    *,
    at: datetime | None = None,
) -> bool:
    """Check for a current transitive reporting path through active organization members."""
    if manager_user_id == subordinate_user_id:
        return False
    instant = _effective_at(at)
    manager_alias = aliased(User)
    subordinate_alias = aliased(User)
    active_members = set(
        session.scalars(
            select(UserUnitMembership.user_id)
            .join(User, User.id == UserUnitMembership.user_id)
            .join(OrganizationUnit, OrganizationUnit.id == UserUnitMembership.unit_id)
            .where(
                User.is_active.is_(True),
                OrganizationUnit.is_active.is_(True),
                UserUnitMembership.valid_from <= instant,
                (UserUnitMembership.valid_until.is_(None))
                | (UserUnitMembership.valid_until > instant),
            )
            .distinct()
        )
    )
    if manager_user_id not in active_members or subordinate_user_id not in active_members:
        return False

    edges = session.execute(
        select(ReportingLine.manager_user_id, ReportingLine.subordinate_user_id)
        .join(manager_alias, manager_alias.id == ReportingLine.manager_user_id)
        .join(subordinate_alias, subordinate_alias.id == ReportingLine.subordinate_user_id)
        .where(
            manager_alias.is_active.is_(True),
            subordinate_alias.is_active.is_(True),
            ReportingLine.valid_from <= instant,
            (ReportingLine.valid_until.is_(None)) | (ReportingLine.valid_until > instant),
        )
    ).all()
    children: dict[UUID, set[UUID]] = defaultdict(set)
    for manager_id, subordinate_id in edges:
        if manager_id in active_members and subordinate_id in active_members:
            children[manager_id].add(subordinate_id)

    reachable = {manager_user_id}
    pending = deque([manager_user_id])
    while pending:
        manager_id = pending.popleft()
        for child_id in children[manager_id]:
            if child_id not in reachable:
                reachable.add(child_id)
                pending.append(child_id)
    if subordinate_user_id not in reachable:
        return False

    # A malformed cycle must not turn reciprocal reporting links into mutual access.
    in_degree = dict.fromkeys(reachable, 0)
    for manager_id in reachable:
        for child_id in children[manager_id]:
            if child_id in reachable:
                in_degree[child_id] += 1
    roots = deque(user_id for user_id, degree in in_degree.items() if degree == 0)
    acyclic_count = 0
    while roots:
        manager_id = roots.popleft()
        acyclic_count += 1
        for child_id in children[manager_id]:
            if child_id in in_degree:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    roots.append(child_id)
    return acyclic_count == len(reachable)


def can_access_task_scope(
    session: Session,
    actor: User,
    *,
    main_pic_user_id: UUID,
    supporting_pic_user_ids: set[UUID],
    at: datetime | None = None,
) -> bool:
    """Authorize a task using server-loaded assignees, roles, membership, and reporting scope.

    Callers must obtain the current active main/support PIC IDs from persisted assignment records,
    never from historical assignments or request payloads.
    """
    if not _active_user(session, actor.id):
        return False
    roles = _role_codes(session, actor.id)
    if SUPER_ADMIN_ROLE in roles:
        return False
    if SECRETARIAT_ROLE in roles:
        return True
    if not has_active_unit_membership(session, actor.id, at=at):
        return False

    assigned_pic_ids = {main_pic_user_id, *supporting_pic_user_ids}
    if PIC_ROLE in roles:
        return actor.id in assigned_pic_ids
    if not roles.intersection(MEETING_LEADER_ROLES):
        return False
    return any(
        is_in_reporting_scope(session, actor.id, pic_user_id, at=at)
        for pic_user_id in assigned_pic_ids
    )


def can_assign_pic(
    session: Session,
    assigner: User,
    assignee_user_id: UUID,
    *,
    at: datetime | None = None,
) -> bool:
    """Allow operational Secretariat to assign only an active, scoped PIC account."""
    if not is_active_secretariat(session, assigner):
        return False
    assignee_roles = _role_codes(session, assignee_user_id)
    if (
        not _active_user(session, assignee_user_id)
        or PIC_ROLE not in assignee_roles
        or SUPER_ADMIN_ROLE in assignee_roles
    ):
        return False
    return has_active_unit_membership(session, assignee_user_id, at=at)
