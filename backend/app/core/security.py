"""Password and session-token primitives for authentication."""

from hashlib import sha256
from secrets import token_urlsafe

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return an Argon2id hash suitable for persistence."""
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password without exposing hash parser or mismatch errors."""
    try:
        return password_hasher.verify(password, password_hash)
    except UnknownHashError:
        return False


def generate_session_token() -> str:
    """Generate a high-entropy opaque token for a server-side session cookie."""
    return token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Return a deterministic digest so raw session tokens need not be stored."""
    return sha256(token.encode("utf-8")).hexdigest()
