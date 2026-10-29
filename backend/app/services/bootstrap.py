"""Create the first admin, the HQ branch, and the default shifts. No sample attendance."""

from __future__ import annotations

from secrets import token_urlsafe

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import admin_password, admin_username, uses_default_admin_password
from app.models import Branch, Setting, Shift, User
from app.security import hash_password
from app.services.attendance import SETTING_DEFAULTS, set_setting


def seed(db: Session) -> None:
    for key, value in SETTING_DEFAULTS.items():
        if db.get(Setting, key) is None:
            set_setting(db, key, value)
    if db.get(Setting, "agent_token") is None:
        set_setting(db, "agent_token", token_urlsafe(24))
    if db.get(Setting, "using_default_admin_password") is None:
        set_setting(db, "using_default_admin_password", "1" if uses_default_admin_password() else "0")
    if db.scalar(select(func.count()).select_from(Branch)) == 0:
        db.add(
            Branch(
                name="HQ",
                code="HQ",
                timezone="Europe/Istanbul",
                address="",
                working_days="",
            )
        )
    if db.scalar(select(func.count()).select_from(Shift)) == 0:
        db.add_all(
            [
                Shift(name="Day", start_time="08:00", end_time="16:00"),
                Shift(name="Evening", start_time="16:00", end_time="00:00"),
                Shift(name="Night", start_time="20:00", end_time="04:00"),
            ]
        )
    if db.scalar(select(func.count()).select_from(User)) == 0:
        db.add(
            User(
                username=admin_username().strip() or "admin",
                password_hash=hash_password(admin_password()),
                role="admin",
                is_active=True,
            )
        )
    db.flush()


# Bump this whenever the way punches become sessions changes. Existing sessions are then rebuilt
# once at startup from the stored punches, which are never touched.
SESSION_RULES_VERSION = "4"


def recalculate_if_rules_changed(db: Session) -> int:
    import logging

    from app.models import Employee
    from app.services.attendance import rebuild_employees

    if db.get(Setting, "session_rules_version") is not None and db.get(Setting, "session_rules_version").value == SESSION_RULES_VERSION:
        return 0
    count = rebuild_employees(db, set(db.scalars(select(Employee.id)).all()))
    set_setting(db, "session_rules_version", SESSION_RULES_VERSION)
    db.commit()
    logging.getLogger("espressolab").info("Recalculated attendance with session rules v%s: %s sessions", SESSION_RULES_VERSION, count)
    return count


def init_db() -> None:
    from app.database import get_engine, get_session
    from app.models import Base

    Base.metadata.create_all(get_engine())
    from app.database import ensure_branch_default_shift, ensure_employee_origin, ensure_session_device

    ensure_employee_origin()
    ensure_session_device()
    ensure_branch_default_shift()
    db = get_session()
    try:
        seed(db)
        db.commit()
        from app.services.sync import release_stuck_syncs, repair_stored_attendance

        release_stuck_syncs(db)
        repair_stored_attendance(db)
        recalculate_if_rules_changed(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
