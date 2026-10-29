"""JSON shapes. Device communication keys and password hashes never leave the server."""

from __future__ import annotations

from datetime import datetime

from app.models import AuditLog, Branch, Device, DeviceUser, Employee, Holiday, LeaveEntry, Shift, SyncRun, User


def stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat(sep=" ")


def user_out(row: User) -> dict:
    return {
        "id": row.id,
        "username": row.username,
        "role": row.role,
        "is_active": bool(row.is_active),
        "created_at": stamp(row.created_at),
    }


def branch_out(row: Branch) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "code": row.code or "",
        "timezone": row.timezone,
        "address": row.address or "",
        "working_days": row.working_days or "",
        "grace_minutes": row.grace_minutes,
        "default_shift_id": row.default_shift_id,
        "work_start": row.work_start or "",
        "work_end": row.work_end or "",
        "created_at": stamp(row.created_at),
    }


def shift_out(row: Shift, branch_name: str = "") -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "grace_minutes": row.grace_minutes,
        "branch_id": row.branch_id,
        "branch": branch_name,
    }


def employee_out(row: Employee, branch_name: str = "", shift_name: str = "") -> dict:
    return {
        "id": row.id,
        "employee_id": row.employee_id,
        "full_name": row.full_name,
        "email": row.email or "",
        "phone": row.phone or "",
        "job_title": row.job_title or "",
        "department": row.department or "",
        "branch_id": row.branch_id,
        "branch": branch_name or "HQ",
        "shift_id": row.shift_id,
        "shift": shift_name,
        "employment_status": row.employment_status or "active",
        "origin": row.origin or "manual",
        "joining_date": row.joining_date or "",
        "manager": row.manager or "",
        "created_at": stamp(row.created_at),
    }


def device_out(row: Device, branch_name: str = "") -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "host": row.host,
        "port": row.port,
        "model": row.model or "",
        "branch_id": row.branch_id,
        "branch": branch_name,
        "protocol": row.protocol,
        "timeout_seconds": row.timeout_seconds,
        "sync_interval_minutes": row.sync_interval_minutes,
        "sync_enabled": bool(row.sync_enabled),
        "status": row.status,
        "connection_status": row.connection_status or "unknown",
        "last_sync_at": stamp(row.last_sync_at),
        "last_sync_status": row.last_sync_status or "",
        "last_error": row.last_error or "",
        "last_test_at": stamp(row.last_test_at),
        "firmware": row.firmware or "",
        "serial_number": row.serial_number or "",
        "push_allowed_ip": row.push_allowed_ip or "",
        "last_push_at": stamp(row.last_push_at),
        "has_comm_key": bool(row.comm_key_encrypted),
        "simulated": row.protocol == "simulator",
        "created_at": stamp(row.created_at),
    }


def device_user_out(row: DeviceUser, employee_id: str = "", employee_name: str = "") -> dict:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "device_user_id": row.device_user_id,
        "name_on_device": row.name_on_device or "",
        "employee_id": employee_id,
        "employee_name": employee_name,
        "mapped": row.employee_pk is not None,
    }


def sync_out(row: SyncRun, device_name: str = "") -> dict:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "device_name": device_name,
        "trigger": row.trigger,
        "status": row.status,
        "message": row.message or "",
        "started_at": stamp(row.started_at),
        "finished_at": stamp(row.finished_at),
        "records_fetched": row.records_fetched,
        "records_inserted": row.records_inserted,
        "records_skipped": row.records_skipped,
        "error_message": row.error_message or "",
    }


def audit_out(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "actor": row.actor,
        "action": row.action,
        "entity": row.entity,
        "entity_id": row.entity_id,
        "detail": row.detail,
        "created_at": stamp(row.created_at),
    }


def holiday_out(row: Holiday, branch_name: str = "") -> dict:
    return {
        "id": row.id,
        "holiday_date": row.holiday_date,
        "name": row.name,
        "branch_id": row.branch_id,
        "branch": branch_name,
    }


def leave_out(row: LeaveEntry, employee_id: str, employee_name: str) -> dict:
    return {
        "id": row.id,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "work_date": row.work_date,
        "note": row.note or "",
        "actor": row.actor,
        "created_at": stamp(row.created_at),
    }
