"""Runtime configuration from environment variables and an optional .env file."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"


def load_env_file() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./data/espressolab.db")


def secret_key() -> str:
    return os.environ.get("SECRET_KEY", "espressolab-dev-secret-change-me")


def fernet_key() -> str:
    return os.environ.get("FERNET_KEY", "")


def admin_username() -> str:
    return os.environ.get("ADMIN_USERNAME", "admin")


def admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD", "change-me-now")


def scheduler_enabled() -> bool:
    return os.environ.get("ENABLE_SCHEDULER", "1").strip().lower() in {"1", "true", "yes", "on"}


def allow_simulator() -> bool:
    return os.environ.get("ALLOW_SIMULATOR", "1").strip().lower() in {"1", "true", "yes", "on"}


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [part.strip() for part in raw.split(",") if part.strip()]


KNOWN_DEFAULT_PASSWORDS = {"change-me-now", "ChangeMe-EspressoLab-2026"}
KNOWN_DEFAULT_SECRETS = {"espressolab-dev-secret-change-me", "change-me", ""}


def is_production() -> bool:
    return os.environ.get("ENVIRONMENT", "development").strip().lower() in {"production", "prod"}


def uses_default_admin_password() -> bool:
    return admin_password() in KNOWN_DEFAULT_PASSWORDS


def production_problems() -> list[str]:
    """Settings that must be changed before real people sign in."""
    problems: list[str] = []
    if secret_key() in KNOWN_DEFAULT_SECRETS or len(secret_key()) < 32:
        problems.append("SECRET_KEY must be a random value of at least 32 characters")
    if not fernet_key():
        problems.append("FERNET_KEY must be set so device communication keys stay decryptable after a SECRET_KEY change")
    if uses_default_admin_password():
        problems.append("ADMIN_PASSWORD must not be one of the published default passwords")
    if allow_simulator():
        problems.append("ALLOW_SIMULATOR must be 0 so simulated data cannot appear next to real attendance")
    if "*" in cors_origins():
        problems.append("CORS_ORIGINS must list the real site address, not *")
    return problems


def token_hours() -> int:
    try:
        return max(1, int(os.environ.get("TOKEN_HOURS", "12")))
    except ValueError:
        return 12
