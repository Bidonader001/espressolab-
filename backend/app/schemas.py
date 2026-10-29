"""Request bodies."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}[A-Za-z0-9]$|^[A-Za-z0-9]$")
PROTOCOLS = {"tcp", "udp", "push", "agent", "simulator"}
ROLES = {"admin", "supervisor", "viewer"}


def clean_host(value: str) -> str:
    host = (value or "").strip()
    if not host or ".." in host or not HOST_RE.match(host):
        raise ValueError("Enter an IP address or hostname")
    return host


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class BranchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = ""
    timezone: str = "Europe/Istanbul"
    address: str = ""
    working_days: str = ""
    grace_minutes: int | None = Field(default=None, ge=0, le=180)
    default_shift_id: int | None = None
    work_start: str = ""
    work_end: str = ""

    @field_validator("work_start", "work_end")
    @classmethod
    def valid_hours(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        parts = text.split(":")
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit() or int(parts[0]) > 23 or int(parts[1]) > 59:
            raise ValueError("Use HH:MM")
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"

    @model_validator(mode="after")
    def both_or_neither(self):
        if bool(self.work_start) != bool(self.work_end):
            raise ValueError("Enter both the start and the end of the working hours, or leave both empty")
        if self.work_start and self.work_start == self.work_end:
            raise ValueError("The working hours must start and end at different times")
        return self

    @field_validator("working_days")
    @classmethod
    def valid_working_days(cls, value: str) -> str:
        """Empty means the company default. Anything else must be days we can read, never silently ignored."""
        text = (value or "").strip()
        if not text:
            return ""
        names = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        parts = [text.split("-", 1)[0], text.split("-", 1)[1]] if "-" in text and "," not in text else text.replace(";", ",").split(",")
        if not parts or any(part.strip()[:3].lower() not in names for part in parts):
            raise ValueError("Working days must look like Sun-Thu or Sun,Mon,Tue,Wed,Thu")
        return text


class ShiftIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start_time: str
    end_time: str
    grace_minutes: int | None = Field(default=None, ge=0, le=180)
    branch_id: int | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def hhmm(cls, value: str) -> str:
        text = value.strip()
        parts = text.split(":")
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError("Use HH:MM")
        hour, minute = int(parts[0]), int(parts[1])
        if hour > 23 or minute > 59:
            raise ValueError("Use HH:MM")
        return f"{hour:02d}:{minute:02d}"


class EmployeeMatch(BaseModel):
    """The same filters the employee list uses, so "everyone matching this search" can be changed in one go."""

    q: str = ""
    branch_id: int | None = None
    department: str = ""
    status: str = ""


class EmployeeBulkStatusIn(BaseModel):
    status: str
    employee_ids: list[str] = Field(default_factory=list, max_length=5000)
    match: EmployeeMatch | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        text = (value or "").strip().lower()
        if text not in {"active", "inactive"}:
            raise ValueError("Status must be active or inactive")
        return text


class EmployeeIn(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)
    full_name: str = Field(min_length=1, max_length=160)
    email: str = ""
    phone: str = ""
    job_title: str = ""
    department: str = ""
    branch_id: int | None = None
    shift_id: int | None = None
    employment_status: str = "active"
    joining_date: str = ""
    manager: str = ""

    @field_validator("employee_id", "full_name")
    @classmethod
    def required(cls, value: str) -> str:
        text = value.strip()
        if not text or any(ord(ch) < 32 for ch in text):
            raise ValueError("This field is required")
        return text

    @field_validator("email")
    @classmethod
    def email_ok(cls, value: str) -> str:
        text = (value or "").strip()
        if text and "@" not in text:
            raise ValueError("Email must contain @")
        return text

    @field_validator("employment_status")
    @classmethod
    def status_ok(cls, value: str) -> str:
        text = (value or "active").strip().lower()
        if text not in {"active", "inactive"}:
            raise ValueError("Status must be active or inactive")
        return text

    @field_validator("joining_date")
    @classmethod
    def date_ok(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        if len(text) != 10 or text[4] != "-" or text[7] != "-":
            raise ValueError("Joining date must be YYYY-MM-DD")
        return text


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host: str
    port: int = Field(default=4370, ge=1, le=65535)
    model: str = ""
    branch_id: int | None = None
    protocol: str = "tcp"
    comm_key: str | None = None
    timeout_seconds: int = Field(default=8, ge=1, le=120)
    sync_interval_minutes: int = Field(default=15, ge=1, le=1440)
    sync_enabled: bool = True
    serial_number: str = ""
    push_allowed_ip: str = ""

    @field_validator("host")
    @classmethod
    def host_ok(cls, value: str) -> str:
        return clean_host(value)

    @field_validator("protocol")
    @classmethod
    def protocol_ok(cls, value: str) -> str:
        text = (value or "tcp").strip().lower()
        if text not in PROTOCOLS:
            raise ValueError("Protocol must be tcp, udp, push, agent, or simulator")
        return text

    @field_validator("comm_key")
    @classmethod
    def key_ok(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if not str(value).strip().isdigit():
            raise ValueError("Communication key must be a number")
        return str(value).strip()


class DeviceUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    model: str | None = None
    branch_id: int | None = None
    protocol: str | None = None
    comm_key: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    sync_enabled: bool | None = None
    status: str | None = None
    serial_number: str | None = None
    push_allowed_ip: str | None = None

    @field_validator("host")
    @classmethod
    def host_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_host(value)

    @field_validator("protocol")
    @classmethod
    def protocol_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if text not in PROTOCOLS:
            raise ValueError("Protocol must be tcp, udp, push, agent, or simulator")
        return text

    @field_validator("status")
    @classmethod
    def status_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if text not in {"active", "disabled"}:
            raise ValueError("Status must be active or disabled")
        return text

    @field_validator("comm_key")
    @classmethod
    def key_ok(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if not str(value).strip().isdigit():
            raise ValueError("Communication key must be a number")
        return str(value).strip()


class MapIn(BaseModel):
    device_user_id: str = Field(min_length=1, max_length=40)
    employee_id: str | None = None


class HolidayIn(BaseModel):
    holiday_date: str
    name: str = Field(min_length=1, max_length=160)
    branch_id: int | None = None

    @field_validator("holiday_date")
    @classmethod
    def date_ok(cls, value: str) -> str:
        text = value.strip()
        if len(text) != 10:
            raise ValueError("Date must be YYYY-MM-DD")
        return text


class LeaveIn(BaseModel):
    employee_id: str
    work_date: str
    note: str = ""


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def role_ok(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in ROLES:
            raise ValueError("Role must be admin, supervisor, or viewer")
        return text


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def role_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if text not in ROLES:
            raise ValueError("Role must be admin, supervisor, or viewer")
        return text


class SettingsIn(BaseModel):
    company_name: str | None = None
    grace_minutes: int | None = Field(default=None, ge=0, le=180)
    working_days: str | None = None
    timezone: str | None = None
    sync_retries: int | None = Field(default=None, ge=1, le=5)
    dormant_after_days: int | None = Field(default=None, ge=0, le=3650)
    punch_debounce_minutes: float | None = Field(default=None, ge=0, le=30)
    max_session_hours: float | None = Field(default=None, ge=1, le=24)
    retap_window_minutes: float | None = Field(default=None, ge=0, le=240)
    default_start: str | None = None
    default_end: str | None = None


class SimLogIn(BaseModel):
    user_id: str
    punched_at: str
    punch: int = 0
    status: int = 0
    uid: int = 0


class SimUserIn(BaseModel):
    user_id: str
    name: str = ""


class SimulatorIn(BaseModel):
    logs: list[SimLogIn]
    users: list[SimUserIn] = []


class AgentIngest(BaseModel):
    device_id: int
    logs: list[SimLogIn]
    users: list[SimUserIn] = []
