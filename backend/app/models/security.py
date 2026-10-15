"""Security-related persistence models."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LoginRateLimitBucket(Base):
    """Hashed composite login identity/IP bucket for one fixed time window."""

    __tablename__ = "login_rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("attempt_count > 0", name="ck_login_rate_limit_attempt_count_positive"),
        CheckConstraint("expires_at > window_started_at", name="ck_login_rate_limit_window_order"),
        Index("ix_login_rate_limit_buckets_expires_at", "expires_at"),
    )

    bucket_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
