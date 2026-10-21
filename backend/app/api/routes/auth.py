"""Login, logout, and current-user endpoints."""

from ipaddress import ip_address
from secrets import compare_digest, token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.auth import User, UserSession
from app.schemas.auth import LoginRequest, UserResponse
from app.services.auth import (
    authenticate_user,
    create_user_session,
    find_active_session,
    revoke_user_session,
)
from app.services.rate_limiting import (
    LoginRateLimitExceeded,
    LoginRateLimitUnavailable,
    enforce_login_rate_limit,
)

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE = "sitara_session"
CSRF_COOKIE = "sitara_csrf"
CSRF_HEADER = "X-CSRF-Token"


def serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=sorted(role.role_code for role in user.roles),
    )


@router.post("/login", response_model=UserResponse)
def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    client = request.client
    client_ip = "unknown"
    try:
        if client is not None:
            client_ip = ip_address(client.host).compressed
    except ValueError:
        # ASGI test clients may use a non-IP sentinel; never fall back to caller headers.
        pass

    try:
        enforce_login_rate_limit(session, credentials.email, client_ip)
    except LoginRateLimitExceeded as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except LoginRateLimitUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login temporarily unavailable",
        ) from error

    user = authenticate_user(session, credentials.email, credentials.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email atau kata sandi tidak valid",
        )

    settings = get_settings()
    ttl_seconds = settings.session_ttl_seconds
    user_session, raw_token = create_user_session(session, user, ttl_seconds)
    csrf_token = token_urlsafe(32)
    secure_cookie = settings.app_env.casefold() != "development"
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=ttl_seconds,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        path="/api/v1",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=ttl_seconds,
        httponly=False,
        secure=secure_cookie,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(CSRF_COOKIE, path="/api/v1", secure=secure_cookie)
    return serialize_user(user)


def get_current_identity(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> tuple[UserSession, User]:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    identity = find_active_session(session, raw_token)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return identity


@router.get("/me", response_model=UserResponse)
def current_user(
    identity: Annotated[tuple[UserSession, User], Depends(get_current_identity)],
) -> UserResponse:
    return serialize_user(identity[1])


def require_csrf(request: Request) -> None:
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf_header = request.headers.get(CSRF_HEADER)
    if csrf_cookie is None or csrf_header is None or not compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    identity: Annotated[tuple[UserSession, User], Depends(get_current_identity)],
    session: Annotated[Session, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    revoke_user_session(session, identity[0])
    settings = get_settings()
    secure_cookie = settings.app_env.casefold() != "development"
    response.delete_cookie(SESSION_COOKIE, path="/api/v1", secure=secure_cookie, httponly=True)
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure_cookie)
    response.delete_cookie(CSRF_COOKIE, path="/api/v1", secure=secure_cookie)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
