from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
import hashlib
import hmac
import secrets
import string

PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 310_000
_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def _urlsafe_b64encode(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))


def generate_initial_password(length: int = 20) -> str:
    if length < 20:
        raise ValueError("Initial password length must be at least 20 characters")

    rng = secrets.SystemRandom()
    required = [
        rng.choice(string.ascii_lowercase),
        rng.choice(string.ascii_uppercase),
        rng.choice(string.digits),
    ]
    remaining = [rng.choice(_PASSWORD_ALPHABET) for _ in range(length - len(required))]
    password_chars = required + remaining
    rng.shuffle(password_chars)
    return "".join(password_chars)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(PBKDF2_ALGORITHM, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return (
        f"pbkdf2_{PBKDF2_ALGORITHM}"
        f"${PBKDF2_ITERATIONS}"
        f"${_urlsafe_b64encode(salt)}"
        f"${_urlsafe_b64encode(digest)}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = password_hash.split("$", maxsplit=3)
    except ValueError:
        return False

    if algorithm != f"pbkdf2_{PBKDF2_ALGORITHM}":
        return False

    try:
        derived = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            _urlsafe_b64decode(salt_text),
            int(iterations),
        )
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(_urlsafe_b64encode(derived), digest_text)


def generate_session_id() -> str:
    return secrets.token_urlsafe(32)
