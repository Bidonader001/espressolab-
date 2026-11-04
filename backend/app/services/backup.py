"""One restorable backup file, rewritten once per calendar day."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, func, select, text
from sqlalchemy.orm import Session

from app.config import backup_path
from app.models import Base

KIND = "espressolab-backup"


def _encode(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def _coerce(column, value):
    if value is None or not isinstance(column.type, DateTime) or not isinstance(value, str):
        return value
    return datetime.fromisoformat(value)


def build_payload(db: Session) -> dict:
    tables: dict[str, list[dict]] = {}
    for table in Base.metadata.sorted_tables:
        rows = db.execute(select(table)).mappings().all()
        tables[table.name] = [{key: _encode(value) for key, value in row.items()} for row in rows]
    return {
        "kind": KIND,
        "created_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "tables": tables,
    }


def _current(path, today: str) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get("created_at") or "")[:10] == today and payload.get("kind") == KIND


def write_backup(db: Session, force: bool = False):
    """Write the backup file. The same day's file is left in place unless force is set."""
    path = backup_path()
    today = datetime.now().date().isoformat()
    if not force and _current(path, today):
        return path
    payload = build_payload(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)
    return path


def restore_backup(db: Session, raw: bytes) -> dict[str, int]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Upload the back up file. It has to be the JSON backup.") from exc
    if not isinstance(payload, dict) or payload.get("kind") != KIND or not isinstance(payload.get("tables"), dict):
        raise ValueError("This file is not an EspressoLab backup.")
    db.expunge_all()
    incoming: dict = payload["tables"]
    known = {table.name: table for table in Base.metadata.sorted_tables}
    unknown = sorted(name for name in incoming if name not in known)
    if unknown:
        raise ValueError("Backup has unknown data: " + ", ".join(unknown))
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        rows = incoming.get(table.name) or []
        if not isinstance(rows, list):
            raise ValueError(f"Backup table {table.name} is invalid.")
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Backup table {table.name} is invalid.")
            cleaned.append({column.key: _coerce(column, row.get(column.key)) for column in table.columns if column.key in row})
        if cleaned:
            db.execute(table.insert(), cleaned)
        counts[table.name] = len(cleaned)
    _reset_sequences(db)
    db.flush()
    return counts


def _reset_sequences(db: Session) -> None:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    for table in Base.metadata.sorted_tables:
        if "id" not in table.c:
            continue
        sequence = db.scalar(text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table.name})
        if not sequence:
            continue
        top = db.scalar(select(func.max(table.c.id))) or 1
        db.execute(text("SELECT setval(:sequence, :top, true)"), {"sequence": sequence, "top": top})
