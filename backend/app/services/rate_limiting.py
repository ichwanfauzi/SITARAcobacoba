"""PostgreSQL-backed login attempt limiting."""

import hashlib
import hmac
import math
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, delete, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.security import LoginRateLimitBucket


class LoginRateLimitExceeded(Exception):
    """Raised when a composite login identity/IP bucket exceeds its limit."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Login attempt limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class LoginRateLimitUnavailable(Exception):
    """Raised when the limiter cannot safely check or persist its counter."""


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _bucket_hash(email: str, client_ip: str, key: str) -> str:
    material = f"sitara-login-rate-v1\0{email.strip().casefold()}\0{client_ip}"
    return hmac.new(key.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()


def cleanup_expired_login_rate_limit_buckets(
    session: Session, *, now: datetime | None = None
) -> int:
    """Delete expired pseudonymous buckets and return the number of rows removed."""
    current_time = _aware_utc(now or datetime.now(UTC))
    result = session.execute(
        delete(LoginRateLimitBucket).where(LoginRateLimitBucket.expires_at <= current_time)
    )
    return max(getattr(result, "rowcount", 0) or 0, 0)


def enforce_login_rate_limit(
    session: Session,
    email: str,
    client_ip: str,
    *,
    now: datetime | None = None,
) -> None:
    """Atomically reserve one attempt; count successful and failed login requests alike."""
    settings = get_settings()
    secret = settings.login_rate_limit_hmac_key
    if secret is None or len(secret.get_secret_value()) < 32:
        raise LoginRateLimitUnavailable

    current_time = _aware_utc(now or datetime.now(UTC))
    expires_at = current_time + timedelta(seconds=settings.login_rate_limit_window_seconds)
    bucket_hash = _bucket_hash(email, client_ip, secret.get_secret_value())
    bucket = LoginRateLimitBucket.__table__

    try:
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "postgresql":
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{settings.login_rate_limit_statement_timeout_ms}ms"},
            )
            insert: Any = postgresql_insert
        elif dialect_name == "sqlite":
            insert = sqlite_insert
        else:
            raise LoginRateLimitUnavailable

        cleanup_expired_login_rate_limit_buckets(session, now=current_time)
        statement = insert(bucket).values(
            bucket_hash=bucket_hash,
            window_started_at=current_time,
            attempt_count=1,
            expires_at=expires_at,
        )
        reset_window = LoginRateLimitBucket.expires_at <= current_time
        statement = statement.on_conflict_do_update(
            index_elements=[LoginRateLimitBucket.bucket_hash],
            set_={
                "window_started_at": case(
                    (reset_window, current_time), else_=LoginRateLimitBucket.window_started_at
                ),
                "attempt_count": case(
                    (reset_window, 1),
                    (
                        LoginRateLimitBucket.attempt_count
                        >= settings.login_rate_limit_max_attempts,
                        settings.login_rate_limit_max_attempts + 1,
                    ),
                    else_=LoginRateLimitBucket.attempt_count + 1,
                ),
                "expires_at": case(
                    (reset_window, expires_at), else_=LoginRateLimitBucket.expires_at
                ),
            },
        ).returning(LoginRateLimitBucket.attempt_count, LoginRateLimitBucket.expires_at)
        result_row = session.execute(statement).one()
        attempt_count = int(result_row[0])
        bucket_expires_at = cast(datetime, result_row[1])
        session.commit()
    except LoginRateLimitUnavailable:
        session.rollback()
        raise
    except SQLAlchemyError as error:
        session.rollback()
        raise LoginRateLimitUnavailable from error

    bucket_expires_at = _aware_utc(bucket_expires_at)
    if attempt_count > settings.login_rate_limit_max_attempts:
        remaining = math.ceil((bucket_expires_at - current_time).total_seconds())
        raise LoginRateLimitExceeded(max(remaining, 1))
