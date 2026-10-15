from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)


def test_password_hash_can_be_verified_without_storing_plaintext() -> None:
    password = "synthetic-test-password"

    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash)
    assert not verify_password("different-password", password_hash)
    assert not verify_password(password, "malformed-password-hash")


def test_session_token_is_random_and_only_its_digest_is_persisted() -> None:
    first_token = generate_session_token()
    second_token = generate_session_token()

    first_digest = hash_session_token(first_token)

    assert first_token != second_token
    assert len(first_token) >= 40
    assert first_digest != first_token
    assert len(first_digest) == 64
    assert hash_session_token(first_token) == first_digest
