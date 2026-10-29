"""EspressoLab Attendance API. Rule-based ZKTeco import. No machine learning."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from starlette.middleware.gzip import GZipMiddleware

from app.config import ROOT, cors_origins, is_production, production_problems, scheduler_enabled
from app.routers import attendance, auth, catalog, devices, iclock, reports, system
from app.services.bootstrap import init_db
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("espressolab")
DIST = ROOT / "frontend" / "dist"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; frame-ancestors 'none'"
    ),
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    problems = production_problems()
    if is_production():
        if problems:
            raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    elif problems:
        log.warning("Development settings in use. Before going live: %s", "; ".join(problems))
    from app.database import sqlite_file

    db_file = sqlite_file()
    if db_file and any(part in db_file.lower() for part in ("onedrive", "dropbox", "google drive", "icloud")):
        log.warning(
            "The SQLite database is inside a synced folder (%s). Sync clients lock the file and cause "
            "'database is locked' errors. Set DATABASE_URL to a path outside it.",
            db_file,
        )
    init_db()
    if scheduler_enabled():
        start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="EspressoLab Attendance", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins() or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc: RequestValidationError):
    parts = []
    for err in exc.errors():
        loc = " ".join(str(item) for item in err.get("loc") or () if item != "body")
        parts.append(f"{loc}: {err.get('msg')}".strip())
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts) or "Invalid input"})


@app.get("/api/v1/health")
def health():
    return {"ok": True, "service": "espressolab-attendance", "ai": False}


@app.get("/api/v1/health/ready")
def ready():
    """Used by load balancers and uptime monitors. Fails when the database cannot answer."""
    from sqlalchemy import text

    from app.database import get_session

    db = get_session()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    finally:
        db.close()
    return {"ok": True, "database": "ready"}


app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(devices.router)
app.include_router(attendance.router)
app.include_router(reports.router)
app.include_router(system.router)
app.include_router(iclock.router)


@app.get("/")
def root():
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {"service": "EspressoLab Attendance", "health": "/api/v1/health"}


@app.get("/{full_path:path}")
def frontend(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("iclock/"):
        raise HTTPException(status_code=404, detail="Not found")
    if not DIST.is_dir():
        raise HTTPException(status_code=404, detail="Not found")
    candidate = (DIST / full_path).resolve()
    if not str(candidate).startswith(str(DIST.resolve())):
        raise HTTPException(status_code=404, detail="Not found")
    if candidate.is_file():
        return FileResponse(candidate)
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not found")
