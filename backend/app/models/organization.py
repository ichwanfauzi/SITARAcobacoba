"""Organization units, effective-dated memberships, and reporting lines."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.auth import User


def utc_now() -> datetime:
    return datetime.now(UTC)


class OrganizationUnit(Base):
    __tablename__ = "organization_units"
    __table_args__ = (
        CheckConstraint(
            "parent_unit_id IS NULL OR parent_unit_id <> id",
            name="ck_organization_units_not_own_parent",
        ),
        UniqueConstraint("unit_code", name="uq_organization_units_unit_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    unit_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_unit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organization_units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    parent: Mapped[OrganizationUnit | None] = relationship(
        "OrganizationUnit", remote_side="OrganizationUnit.id", back_populates="children"
    )
    children: Mapped[list[OrganizationUnit]] = relationship(back_populates="parent")
    memberships: Mapped[list[UserUnitMembership]] = relationship(back_populates="unit")


class UserUnitMembership(Base):
    __tablename__ = "user_unit_memberships"
    __table_args__ = (
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_user_unit_memberships_valid_interval",
        ),
        UniqueConstraint(
            "user_id",
            "unit_id",
            "valid_from",
            name="uq_user_unit_memberships_user_unit_start",
        ),
        Index("ix_user_unit_memberships_user_period", "user_id", "valid_from", "valid_until"),
        Index("ix_user_unit_memberships_unit_period", "unit_id", "valid_from", "valid_until"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization_units.id", ondelete="RESTRICT"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    user: Mapped[User] = relationship()
    unit: Mapped[OrganizationUnit] = relationship(back_populates="memberships")


class ReportingLine(Base):
    __tablename__ = "reporting_lines"
    __table_args__ = (
        CheckConstraint(
            "manager_user_id <> subordinate_user_id",
            name="ck_reporting_lines_not_self_referential",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_reporting_lines_valid_interval",
        ),
        UniqueConstraint(
            "manager_user_id",
            "subordinate_user_id",
            "valid_from",
            name="uq_reporting_lines_pair_start",
        ),
        Index("ix_reporting_lines_manager_period", "manager_user_id", "valid_from", "valid_until"),
        Index(
            "ix_reporting_lines_subordinate_period",
            "subordinate_user_id",
            "valid_from",
            "valid_until",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    manager_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subordinate_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    manager: Mapped[User] = relationship(foreign_keys=[manager_user_id])
    subordinate: Mapped[User] = relationship(foreign_keys=[subordinate_user_id])
