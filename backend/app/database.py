"""SQLAlchemy engine and sessions. SQLite by default, PostgreSQL when DATABASE_URL says so."""

from __future__ import annotations

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import ROOT, database_url

_engine = None
_Session: sessionmaker[Session] | None = None


def normalized_database() -> tuple[str, bool, str]:
    url = database_url()
    if url.startswith("sqlite"):
        from pathlib import Path

        raw = url.split("sqlite:///", 1)[-1]
        file_path = Path(raw)
        if not file_path.is_absolute():
            file_path = ROOT / file_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{file_path.as_posix()}", True, str(file_path)
    return url, False, ""


def get_engine():
    global _engine, _Session
    if _engine is None:
        url, is_sqlite, _file = normalized_database()
        kwargs: dict = {}
        if is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 60}
            kwargs["poolclass"] = NullPool
        else:
            kwargs["pool_pre_ping"] = True
        _engine = create_engine(url, **kwargs)
        if is_sqlite:

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=60000")
                cursor.close()

        _Session = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session() -> Session:
    get_engine()
    assert _Session is not None
    return _Session()


def reset() -> None:
    """Drop the cached engine so tests can point DATABASE_URL at a fresh file."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def ensure_employee_origin() -> None:
    """Add employees.origin on databases created before device enrollment."""
    engine = get_engine()
    if not inspect(engine).has_table("employees"):
        return
    columns = {col["name"] for col in inspect(engine).get_columns("employees")}
    if "origin" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE employees ADD COLUMN origin VARCHAR(20) DEFAULT 'manual'"))


def ensure_session_device() -> None:
    """Add attendance_sessions.device_id on databases created before sessions remembered their terminal."""
    engine = get_engine()
    if not inspect(engine).has_table("attendance_sessions"):
        return
    columns = {col["name"] for col in inspect(engine).get_columns("attendance_sessions")}
    if "device_id" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE attendance_sessions ADD COLUMN device_id INTEGER"))


def ensure_branch_default_shift() -> None:
    """Add branches.default_shift_id on databases created before branches had a default shift."""
    engine = get_engine()
    if not inspect(engine).has_table("branches"):
        return
    columns = {col["name"] for col in inspect(engine).get_columns("branches")}
    wanted = {
        "default_shift_id": "INTEGER",
        "work_start": "VARCHAR(5) DEFAULT ''",
        "work_end": "VARCHAR(5) DEFAULT ''",
    }
    with engine.begin() as conn:
        for name, kind in wanted.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE branches ADD COLUMN {name} {kind}"))


def sqlite_file() -> str:
    _url, is_sqlite, file_path = normalized_database()
    return file_path if is_sqlite else ""
