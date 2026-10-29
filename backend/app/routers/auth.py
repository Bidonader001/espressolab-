"""Login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.models import User
from app.schemas import LoginIn
from app.security import clear_failures, create_token, record_failure, too_many_attempts, verify_password
from app.serialize import user_out
from app.services.attendance import get_settings
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    username = body.username.strip()
    if too_many_attempts(username):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a minute.")
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        record_failure(username)
        audit(db, username or "unknown", "login_failed", "user", username, "Rejected login")
        db.commit()
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    clear_failures(username)
    audit(db, user, "login", "user", str(user.id), "Signed in")
    db.commit()
    return {"token": create_token(user.username), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings(db)
    return {
        "user": user_out(user),
        "must_change_password": settings.get("using_default_admin_password") == "1" and user.role == "admin",
        "company_name": settings.get("company_name") or "EspressoLab",
    }
