"""Password hashing, session tokens, and encryption for device communication keys."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

from app.config import fernet_key, secret_key, token_hours

_FAILS: dict[str, list[float]] = {}
_LOCK_WINDOW = 60.0
_LOCK_MAX = 8


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(username: str) -> str:
    payload = {"u": username, "exp": int(time.time()) + token_hours() * 3600}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(secret_key().encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(token: str) -> str | None:
    try:
        body, sig = token.split(".", 1)
        expect = hmac.new(secret_key().encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if int(payload.get("exp") or 0) < time.time():
            return None
        username = str(payload.get("u") or "")
        return username or None
    except (ValueError, json.JSONDecodeError, TypeError):
        return None


def too_many_attempts(username: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in _FAILS.get(username, []) if now - stamp < _LOCK_WINDOW]
    _FAILS[username] = recent
    return len(recent) >= _LOCK_MAX


def record_failure(username: str) -> None:
    _FAILS.setdefault(username, []).append(time.time())


def clear_failures(username: str) -> None:
    _FAILS.pop(username, None)


def _cipher() -> Fernet:
    raw = fernet_key().strip()
    if raw:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    digest = hashlib.sha256(secret_key().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    text = (value or "").strip()
    if not text or text == "0":
        return ""
    return _cipher().encrypt(text.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def safe_error(exc: BaseException, secret: str = "") -> str:
    text = str(exc).strip() or exc.__class__.__name__
    if secret and secret not in {"", "0"} and secret in text:
        text = text.replace(secret, "***")
    return text[:2000]
