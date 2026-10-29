"""Authentication dependencies."""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import User
from app.security import read_token
from app.services.attendance import get_settings

_bearer = HTTPBearer(auto_error=False)


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    username = read_token(creds.credentials)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_writer(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "supervisor"}:
        raise HTTPException(status_code=403, detail="You do not have permission for this action")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="You do not have permission for this action")
    return user


def require_agent(x_agent_token: str = Header(default=""), db: Session = Depends(get_db)) -> Session:
    expected = get_settings(db).get("agent_token") or ""
    got = (x_agent_token or "").encode()
    exp = expected.encode()
    if not expected or len(got) != len(exp) or not hmac.compare_digest(got, exp):
        raise HTTPException(status_code=401, detail="Agent token rejected")
    return db
