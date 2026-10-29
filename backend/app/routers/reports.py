"""Excel, CSV, and PDF exports, plus the older session-log report."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.exports import (
    DETAIL_ALL,
    DETAIL_DEFAULT,
    DIRECTORY_ALL,
    DIRECTORY_DEFAULT,
    FORMATS,
    REPORT_TYPES,
    ExportError,
    build_payload,
    collect,
    preview_payload,
)
from app.models import Branch, Employee, ExportAudit, User
from app.period_reports import build_excel, build_pdf, file_tag, prepare_rows, resolve_period, summarize
from app.services.attendance import load_bundle

router = APIRouter(prefix="/api/v1", tags=["reports"])


def _bundle_for(db: Session, employee_id: str, start: str, end: str):
    return load_bundle(db, employee_id=employee_id, date_from=start, date_to=end)


def _params(
    report: str,
    fmt: str,
    start_date: str,
    end_date: str,
    branch: str,
    department: str,
    employee_id: str,
    status: str,
    columns: str,
    include_inactive: str,
    branch_id: str,
    source: str = "",
    device_id: str = "",
) -> dict:
    branch_name = branch
    return {
        "report": report,
        "format": fmt,
        "start_date": start_date,
        "end_date": end_date,
        "branch": branch_name,
        "branch_id": branch_id,
        "department": department,
        "employee_id": employee_id,
        "status": status,
        "columns": columns,
        "include_inactive": include_inactive,
        "source": source,
        "device_id": device_id,
    }


def _resolve_branch(db: Session, branch: str, branch_id: str) -> str:
    if branch.strip():
        return branch.strip()
    if branch_id.strip().isdigit():
        row = db.get(Branch, int(branch_id))
        if row:
            return row.name
    return ""


def _log(db: Session, user: User, report: str, fmt: str, start: str, end: str, scope: str, outcome: str) -> None:
    db.add(
        ExportAudit(
            actor=user.username,
            report_type=report,
            format=fmt,
            date_from=start,
            date_to=end,
            scope=scope[:500],
            outcome=outcome,
        )
    )
    db.commit()


@router.get("/exports/meta")
def export_meta(db: Session = Depends(get_db), _: User = Depends(current_user)):
    people = db.query(Employee).order_by(Employee.full_name).all()
    branches = sorted({row.name for row in db.query(Branch).all()})
    departments = sorted({row.department for row in people if row.department})
    return {
        "reports": list(REPORT_TYPES),
        "formats": list(FORMATS),
        "detail_columns": DETAIL_ALL,
        "detail_default": DETAIL_DEFAULT,
        "directory_columns": DIRECTORY_ALL,
        "directory_default": DIRECTORY_DEFAULT,
        "branches": branches,
        "departments": departments,
        "employees": [
            {"employee_id": row.employee_id, "name": row.full_name}
            for row in people
            if (row.employment_status or "active") != "inactive"
        ],
        "max_days": 366,
        "hours_note": "Elapsed check-in to check-out time. Payroll is not included.",
        "omitted": ["Base salary", "Net pay", "Face enrollment"],
    }


@router.get("/exports/count")
def export_count(
    report: str = "monthly",
    start_date: str = "",
    end_date: str = "",
    branch: str = "",
    department: str = "",
    branch_id: str = "",
    employee_id: str = "",
    status: str = "",
    include_inactive: str = "",
    source: str = "",
    device_id: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    branch_name = _resolve_branch(db, branch, branch_id)
    bundle = _bundle_for(db, employee_id, start_date, end_date)
    try:
        data = collect(
            _params(report, "xlsx", start_date, end_date, branch_name, department, employee_id, status, "", include_inactive, "", source, device_id),
            bundle,
        )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": data["count"], "hours_note": data["hours_note"]}


@router.get("/exports/preview")
def export_preview(
    report: str = "monthly",
    start_date: str = "",
    end_date: str = "",
    branch: str = "",
    department: str = "",
    branch_id: str = "",
    employee_id: str = "",
    status: str = "",
    columns: str = "",
    include_inactive: str = "",
    source: str = "",
    device_id: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """The rows a download with the same filters would contain, for checking before downloading."""
    branch_name = _resolve_branch(db, branch, branch_id)
    bundle = _bundle_for(db, employee_id, start_date, end_date)
    try:
        data = collect(
            _params(report, "xlsx", start_date, end_date, branch_name, department, employee_id, status, columns, include_inactive, "", source, device_id),
            bundle,
        )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preview_payload(data, columns, page, page_size)


def _send(params: dict, db: Session, user: User) -> Response:
    report = params.get("report") or "monthly"
    fmt = params.get("format") or "xlsx"
    try:
        bundle = _bundle_for(db, params.get("employee_id") or "", params.get("start_date") or "", params.get("end_date") or "")
        data = collect(params, bundle)
        payload, name, media = build_payload(data, fmt, params.get("columns") or "")
    except ExportError as exc:
        _log(db, user, report, fmt, params.get("start_date") or "", params.get("end_date") or "", "", "rejected")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        _log(db, user, report, fmt, "", "", "", "error")
        raise
    scope = f"branch={data['branch']};dept={data['department']};rows={data['count']}"
    _log(db, user, data["report"], fmt, data["start"].isoformat(), data["end"].isoformat(), scope, "ok")
    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.get("/exports")
def download_export(
    report: str = Query(default="monthly"),
    format: str = Query(default="xlsx", alias="format"),
    start_date: str = "",
    end_date: str = "",
    branch: str = "",
    department: str = "",
    branch_id: str = "",
    employee_id: str = "",
    status: str = "",
    columns: str = "",
    include_inactive: str = "",
    source: str = "",
    device_id: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    branch_name = _resolve_branch(db, branch, branch_id)
    return _send(
        _params(
            report,
            format,
            start_date,
            end_date,
            branch_name,
            department,
            employee_id,
            status,
            columns,
            include_inactive,
            "",
            source,
            device_id,
        ),
        db,
        user,
    )


@router.get("/exports/employees")
def download_employees(
    format: str = Query(default="csv", alias="format"),
    branch: str = "",
    department: str = "",
    branch_id: str = "",
    include_inactive: str = "",
    columns: str = "",
    source: str = "",
    device_id: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    branch_name = _resolve_branch(db, branch, branch_id)
    return _send(
        _params("employees", format, "", "", branch_name, department, "", "", columns, include_inactive, "", source, device_id),
        db,
        user,
    )


def _period_rows(db: Session, period: str, work_date: str, employee_id: str):
    start, end, kind = resolve_period(period, work_date)
    bundle = load_bundle(db, employee_id=employee_id, date_from=start, date_to=end)
    sessions = bundle["sessions"]
    if employee_id:
        sessions = [row for row in sessions if row.get("employee_id") == employee_id]
    rows = prepare_rows(sessions)
    return rows, summarize(rows), start, end, kind


@router.get("/reports")
def period_report(
    work_date: str = "",
    period: str = "daily",
    employee_id: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    rows, summary, start, end, kind = _period_rows(db, period, work_date, employee_id)
    return {"period": kind, "date_from": start, "date_to": end, "employee_id": employee_id, "rows": rows, "summary": summary}


@router.get("/reports/excel")
def period_excel(
    work_date: str = "",
    period: str = "daily",
    employee_id: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    rows, summary, start, end, kind = _period_rows(db, period, work_date, employee_id)
    payload = build_excel(rows, summary, start, end, kind)
    name = f"EspressoLabAttendance-{kind}{file_tag(employee_id)}-{start}-to-{end}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/reports/pdf")
def period_pdf(
    work_date: str = "",
    period: str = "daily",
    employee_id: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    rows, summary, start, end, kind = _period_rows(db, period, work_date, employee_id)
    payload = build_pdf(rows, summary, start, end, kind)
    name = f"EspressoLabAttendance-{kind}{file_tag(employee_id)}-{start}-to-{end}.pdf"
    return Response(content=payload, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
