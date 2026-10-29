"""Persistence models. Raw device punches stay separate from calculated sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    code: Mapped[str] = mapped_column(String(40), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Istanbul")
    address: Mapped[str] = mapped_column(String(255), default="")
    working_days: Mapped[str] = mapped_column(String(80), default="")
    grace_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Used for this branch's employees who have no shift of their own.
    default_shift_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The branch's own working hours (HH:MM). Both empty means the company hours.
    work_start: Mapped[str] = mapped_column(String(5), default="")
    work_end: Mapped[str] = mapped_column(String(5), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    grace_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    job_title: Mapped[str] = mapped_column(String(120), default="")
    department: Mapped[str] = mapped_column(String(120), default="", index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    employment_status: Mapped[str] = mapped_column(String(20), default="active")
    origin: Mapped[str] = mapped_column(String(20), default="manual")
    joining_date: Mapped[str] = mapped_column(String(10), default="")
    manager: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=4370)
    model: Mapped[str] = mapped_column(String(80), default="")
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    protocol: Mapped[str] = mapped_column(String(20), default="tcp")
    comm_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=8)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    connection_status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_status: Mapped[str] = mapped_column(String(20), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    firmware: Mapped[str] = mapped_column(String(120), default="")
    serial_number: Mapped[str] = mapped_column(String(80), default="", index=True)
    push_allowed_ip: Mapped[str] = mapped_column(String(64), default="")
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DeviceUser(Base):
    __tablename__ = "device_users"
    __table_args__ = (UniqueConstraint("device_id", "device_user_id", name="uq_device_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    device_user_id: Mapped[str] = mapped_column(String(40))
    name_on_device: Mapped[str] = mapped_column(String(160), default="")
    employee_pk: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)


class Punch(Base):
    __tablename__ = "punches"
    __table_args__ = (
        UniqueConstraint("device_id", "device_user_id", "punched_at", "punch", name="uq_punch_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    device_user_id: Mapped[str] = mapped_column(String(40), index=True)
    punched_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    punch: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    record_uid: Mapped[int] = mapped_column(Integer, default=0)
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"), nullable=True)
    device_name_snapshot: Mapped[str] = mapped_column(String(120), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_pk: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    work_date: Mapped[str] = mapped_column(String(10), index=True)
    clock_in: Mapped[datetime] = mapped_column(DateTime)
    clock_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    minutes_late: Mapped[int] = mapped_column(Integer, default=0)
    shift_name: Mapped[str] = mapped_column(String(80), default="")
    device_name: Mapped[str] = mapped_column(String(120), default="")
    # The terminal that recorded the check-in. Reports take the session's branch from this device's branch.
    device_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holiday_date: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(160))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)


class LeaveEntry(Base):
    __tablename__ = "leave_entries"
    __table_args__ = (UniqueConstraint("employee_pk", "work_date", name="uq_leave_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_pk: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    work_date: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(String(255), default="")
    actor: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class ExportAudit(Base):
    __tablename__ = "export_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    report_type: Mapped[str] = mapped_column(String(40))
    format: Mapped[str] = mapped_column(String(10))
    date_from: Mapped[str] = mapped_column(String(10), default="")
    date_to: Mapped[str] = mapped_column(String(10), default="")
    scope: Mapped[str] = mapped_column(String(500), default="")
    outcome: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
