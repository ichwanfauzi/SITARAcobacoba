from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.core.security import hash_password, hash_session_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.auth import Role, User, UserSession
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def auth_context() -> Iterator[tuple[TestClient, Session, User]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    role = Role(role_code="PIC", role_name="PIC")
    user = User(
        email="pic@example.test",
        full_name="Test PIC",
        password_hash=hash_password("synthetic-password"),
        is_active=True,
    )
    user.roles.append(role)
    session.add(user)
    session.commit()
    app.dependency_overrides[get_db] = lambda: session

    try:
        yield TestClient(app), session, user
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_login_sets_hardened_session_cookie_and_returns_role(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email.upper(), "password": "synthetic-password"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "roles": ["PIC"],
    }
    session_token = client.cookies.get("sitara_session")
    csrf_token = client.cookies.get("sitara_csrf")
    assert session_token
    assert csrf_token
    assert any(
        "sitara_session=" in cookie.lower()
        and "httponly" in cookie.lower()
        and "samesite=lax" in cookie.lower()
        for cookie in response.headers.get_list("set-cookie")
    )
    stored_session = session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(session_token))
    )
    assert stored_session is not None
    assert stored_session.token_hash != session_token


def test_login_rejects_wrong_password_and_inactive_user(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong-password"},
    )
    assert wrong_password.status_code == 401
    assert not client.cookies.get("sitara_session")

    user.is_active = False
    session.commit()
    inactive_user = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "synthetic-password"},
    )
    assert inactive_user.status_code == 401
    assert inactive_user.json() == wrong_password.json()


def test_current_user_requires_a_session_and_logout_checks_csrf(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context

    assert client.get("/api/v1/auth/me").status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "synthetic-password"},
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me").json() == login.json()

    missing_csrf = client.post("/api/v1/auth/logout")
    assert missing_csrf.status_code == 403

    csrf_token = client.cookies.get("sitara_csrf")
    assert csrf_token
    logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    stored_session = session.scalar(select(UserSession))
    assert stored_session is not None
    assert stored_session.revoked_at is not None


def test_expired_session_is_rejected(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context
    raw_token = "synthetic-expired-session-token"
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(raw_token),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    session.commit()
    client.cookies.set("sitara_session", raw_token)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
