"""Shared audit helper."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(db: Session, actor: User | str, action: str, entity: str, entity_id: str = "", detail: str = "") -> None:
    name = actor.username if isinstance(actor, User) else actor
    db.add(
        AuditLog(
            actor=name,
            action=action,
            entity=entity,
            entity_id=str(entity_id)[:80],
            detail=(detail or "")[:500],
        )
    )
