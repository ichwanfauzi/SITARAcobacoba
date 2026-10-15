"""Small operational maintenance commands for the backend."""

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.rate_limiting import cleanup_expired_login_rate_limit_buckets


def cleanup_login_rate_limits() -> int:
    """Delete expired login limiter rows from the configured PostgreSQL database."""
    settings = get_settings()
    if (
        not settings.database_url
        or make_url(settings.database_url).get_backend_name() != "postgresql"
    ):
        print(
            "A PostgreSQL DATABASE_URL is required for this maintenance command.", file=sys.stderr
        )
        return 1

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{settings.login_rate_limit_statement_timeout_ms}ms"},
            )
            removed = cleanup_expired_login_rate_limit_buckets(session)
            session.commit()
    except SQLAlchemyError:
        print(
            "Login rate-limit cleanup failed; expired rows were not confirmed removed.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()

    print(f"Removed {removed} expired login rate-limit buckets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cleanup_login_rate_limits())
