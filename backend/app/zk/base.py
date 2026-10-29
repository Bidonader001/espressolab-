"""Normalized attendance logs. Adapters only read devices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NormalizedLog:
    user_id: str
    punched_at: datetime
    punch: int = 0
    status: int = 0
    uid: int = 0


@dataclass(frozen=True)
class NormalizedUser:
    user_id: str
    name: str = ""


@dataclass(frozen=True)
class DeviceInfo:
    ok: bool
    message: str
    firmware: str = ""
    serial: str = ""
    model: str = ""
    simulated: bool = False


@dataclass(frozen=True)
class ConnParams:
    device_id: int
    name: str
    host: str
    port: int
    timeout: int
    protocol: str
    comm_key: int
    serial_number: str = ""


def clean_stamp(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    return value.replace(microsecond=0)
