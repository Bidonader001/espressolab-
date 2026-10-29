"""Employees, branches, shifts, holidays, and leave."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.deps import current_user, get_db, require_writer
from app.models import Branch, Employee, Holiday, LeaveEntry, Shift, User
from app.schemas import BranchIn, EmployeeBulkStatusIn, EmployeeIn, HolidayIn, LeaveIn, ShiftIn
from app.serialize import branch_out, employee_out, holiday_out, leave_out, shift_out
from app.services.attendance import load_bundle, rebuild_employees
from app.services.audit import audit
from app.exports import ExportError, collect

router = APIRouter(prefix="/api/v1", tags=["directory"])


def _maps(db: Session):
    branches = {row.id: row for row in db.scalars(select(Branch)).all()}
    shifts = {row.id: row for row in db.scalars(select(Shift)).all()}
    return branches, shifts


def _employee_dict(row: Employee, branches, shifts) -> dict:
    branch = branches.get(row.branch_id)
    shift = shifts.get(row.shift_id)
    return employee_out(row, branch.name if branch else "", shift.name if shift else "")


@router.get("/branches")
def list_branches(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"items": [branch_out(row) for row in db.scalars(select(Branch).order_by(Branch.name)).all()]}


@router.post("/branches")
def create_branch(body: BranchIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    if db.scalar(select(Branch).where(Branch.name == body.name.strip())):
        raise HTTPException(status_code=400, detail="A branch with that name already exists")
    row = Branch(
        name=body.name.strip(),
        code=body.code.strip(),
        timezone=body.timezone.strip() or "Europe/Istanbul",
        address=body.address.strip(),
        working_days=body.working_days.strip(),
        grace_minutes=body.grace_minutes,
        work_start=body.work_start,
        work_end=body.work_end,
    )
    db.add(row)
    db.flush()
    # A new branch has no shifts yet, so it cannot have a default one. Add shifts first, then choose.
    audit(db, user, "create", "branch", str(row.id), row.name)
    db.commit()
    return branch_out(row)


def _check_default_shift(db: Session, branch_id: int, shift_id: int | None) -> None:
    if shift_id is None:
        return
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise HTTPException(status_code=400, detail="That shift does not exist")
    if shift.branch_id not in (None, branch_id):
        raise HTTPException(status_code=400, detail="The default shift must belong to this branch or to all branches")


def _employees_on_default(db: Session, branch_id: int) -> set[int]:
    """Employees of this branch who have no shift of their own, so the branch default decides their shift."""
    return set(db.scalars(select(Employee.id).where(Employee.branch_id == branch_id, Employee.shift_id.is_(None))).all())


@router.patch("/branches/{branch_id}")
def update_branch(branch_id: int, body: BranchIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = db.get(Branch, branch_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    clash = db.scalar(select(Branch).where(Branch.name == body.name.strip(), Branch.id != branch_id))
    if clash:
        raise HTTPException(status_code=400, detail="A branch with that name already exists")
    row.name = body.name.strip()
    row.code = body.code.strip()
    row.timezone = body.timezone.strip() or row.timezone
    row.address = body.address.strip()
    row.working_days = body.working_days.strip()
    row.grace_minutes = body.grace_minutes
    _check_default_shift(db, branch_id, body.default_shift_id)
    default_changed = (
        row.default_shift_id != body.default_shift_id
        or (row.work_start or "") != body.work_start
        or (row.work_end or "") != body.work_end
    )
    row.default_shift_id = body.default_shift_id
    row.work_start = body.work_start
    row.work_end = body.work_end
    if default_changed:
        # Lateness and the work date depend on the shift, so recalculate the people it applies to.
        rebuild_employees(db, _employees_on_default(db, branch_id))
    audit(db, user, "update", "branch", str(row.id), row.name)
    db.commit()
    return branch_out(row)


@router.delete("/branches/{branch_id}")
def delete_branch(branch_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = db.get(Branch, branch_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    used = db.scalar(select(func.count()).select_from(Employee).where(Employee.branch_id == branch_id)) or 0
    if used:
        raise HTTPException(status_code=409, detail="Move employees off this branch before deleting it")
    if db.scalar(select(func.count()).select_from(Shift).where(Shift.branch_id == branch_id)):
        raise HTTPException(status_code=409, detail="Delete this branch's shifts before deleting the branch")
    audit(db, user, "delete", "branch", str(row.id), row.name)
    db.delete(row)
    db.commit()
    return {"ok": True}


def _employees_using_shift(db: Session, shift_id: int) -> set[int]:
    """Everyone whose lateness depends on this shift: assigned to it, or on a branch that defaults to it."""
    pks = set(db.scalars(select(Employee.id).where(Employee.shift_id == shift_id)).all())
    for branch in db.scalars(select(Branch).where(Branch.default_shift_id == shift_id)).all():
        pks |= _employees_on_default(db, branch.id)
    return pks


@router.get("/shifts")
def list_shifts(db: Session = Depends(get_db), _: User = Depends(current_user)):
    branches, _shifts = _maps(db)
    rows = db.scalars(select(Shift).order_by(Shift.start_time, Shift.name)).all()
    return {
        "items": [
            shift_out(row, branches[row.branch_id].name if row.branch_id in branches else "")
            for row in rows
        ]
    }


@router.post("/shifts")
def create_shift(body: ShiftIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = Shift(
        name=body.name.strip(),
        start_time=body.start_time,
        end_time=body.end_time,
        grace_minutes=body.grace_minutes,
        branch_id=body.branch_id,
    )
    db.add(row)
    db.flush()
    audit(db, user, "create", "shift", str(row.id), row.name)
    db.commit()
    return shift_out(row)


@router.patch("/shifts/{shift_id}")
def update_shift(shift_id: int, body: ShiftIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = db.get(Shift, shift_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    row.name = body.name.strip()
    row.start_time = body.start_time
    row.end_time = body.end_time
    row.grace_minutes = body.grace_minutes
    row.branch_id = body.branch_id
    pks = _employees_using_shift(db, shift_id)
    # A branch cannot keep a shift of another branch as its default.
    for branch in db.scalars(select(Branch).where(Branch.default_shift_id == shift_id)).all():
        if row.branch_id not in (None, branch.id):
            branch.default_shift_id = None
    rebuild_employees(db, pks)
    audit(db, user, "update", "shift", str(row.id), "Shift saved and attendance recalculated")
    db.commit()
    return shift_out(row)


@router.delete("/shifts/{shift_id}")
def delete_shift(shift_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = db.get(Shift, shift_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    pks = _employees_using_shift(db, shift_id)
    for emp in db.scalars(select(Employee).where(Employee.shift_id == shift_id)).all():
        emp.shift_id = None
    for branch in db.scalars(select(Branch).where(Branch.default_shift_id == shift_id)).all():
        branch.default_shift_id = None
    db.flush()
    rebuild_employees(db, pks)
    audit(db, user, "delete", "shift", str(row.id), row.name)
    db.delete(row)
    db.commit()
    return {"ok": True}


def _employee_filter(stmt, q: str, branch_id: int | None, department: str, status: str):
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Employee.full_name.like(like), Employee.employee_id.like(like), Employee.department.like(like)))
    if branch_id:
        stmt = stmt.where(Employee.branch_id == branch_id)
    if department.strip():
        stmt = stmt.where(Employee.department == department.strip())
    if status.strip():
        stmt = stmt.where(Employee.employment_status == status.strip().lower())
    return stmt


@router.post("/employees/bulk-status")
def bulk_employee_status(body: EmployeeBulkStatusIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    """Make many employees active or inactive at once. Attendance history is never touched."""
    if body.match is not None:
        stmt = _employee_filter(select(Employee), body.match.q, body.match.branch_id, body.match.department, body.match.status)
        rows = db.scalars(stmt).all()
    elif body.employee_ids:
        wanted = {value.strip() for value in body.employee_ids if value.strip()}
        rows = db.scalars(select(Employee).where(Employee.employee_id.in_(wanted))).all()
        if len(rows) != len(wanted):
            missing = sorted(wanted - {row.employee_id for row in rows})
            raise HTTPException(status_code=404, detail=f"Employee not found: {', '.join(missing[:5])}")
    else:
        raise HTTPException(status_code=400, detail="Select at least one employee")
    changed = 0
    for row in rows:
        if (row.employment_status or "active") != body.status:
            row.employment_status = body.status
            changed += 1
    audit(db, user, "update", "employee", "bulk", f"{len(rows)} selected, {changed} set to {body.status}")
    db.commit()
    return {"selected": len(rows), "changed": changed, "status": body.status}


@router.get("/employees")
def list_employees(
    q: str = "",
    branch_id: int | None = None,
    department: str = "",
    status: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    stmt = _employee_filter(select(Employee), q, branch_id, department, status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Employee.full_name).offset((page - 1) * page_size).limit(page_size)).all()
    branches, shifts = _maps(db)
    return {
        "items": [_employee_dict(row, branches, shifts) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/employees")
def create_employee(body: EmployeeIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    if db.scalar(select(Employee).where(Employee.employee_id == body.employee_id)):
        raise HTTPException(status_code=400, detail="That employee ID already exists")
    row = Employee(
        employee_id=body.employee_id,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone.strip(),
        job_title=body.job_title.strip(),
        department=body.department.strip(),
        branch_id=body.branch_id,
        shift_id=body.shift_id,
        employment_status=body.employment_status,
        joining_date=body.joining_date,
        manager=body.manager.strip(),
    )
    db.add(row)
    db.flush()
    audit(db, user, "create", "employee", row.employee_id, row.full_name)
    db.commit()
    branches, shifts = _maps(db)
    return _employee_dict(row, branches, shifts)


def _get_employee(db: Session, employee_id: str) -> Employee:
    row = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return row


@router.get("/employees/{employee_id}")
def get_employee(employee_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    row = _get_employee(db, employee_id)
    branches, shifts = _maps(db)
    return _employee_dict(row, branches, shifts)


@router.patch("/employees/{employee_id}")
def update_employee(
    employee_id: str,
    body: EmployeeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_writer),
):
    row = _get_employee(db, employee_id)
    if body.employee_id != row.employee_id:
        taken = db.scalar(select(Employee).where(Employee.employee_id == body.employee_id))
        if taken is not None:
            raise HTTPException(status_code=400, detail="That employee ID already exists")
    # With no shift of their own, a change of branch can change the shift that applies (the branch default).
    shift_changed = row.shift_id != body.shift_id or (body.shift_id is None and row.branch_id != body.branch_id)
    row.employee_id = body.employee_id
    row.full_name = body.full_name
    row.email = body.email
    row.phone = body.phone.strip()
    row.job_title = body.job_title.strip()
    row.department = body.department.strip()
    row.branch_id = body.branch_id
    row.shift_id = body.shift_id
    row.employment_status = body.employment_status
    row.joining_date = body.joining_date
    row.manager = body.manager.strip()
    if shift_changed:
        rebuild_employees(db, {row.id})
    audit(db, user, "update", "employee", row.employee_id, row.full_name)
    db.commit()
    branches, shifts = _maps(db)
    return _employee_dict(row, branches, shifts)


@router.delete("/employees/{employee_id}")
def delete_employee(employee_id: str, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = _get_employee(db, employee_id)
    from app.models import AttendanceSession, Punch, DeviceUser

    punches = db.scalar(
        select(func.count())
        .select_from(Punch)
        .join(DeviceUser, (DeviceUser.device_id == Punch.device_id) & (DeviceUser.device_user_id == Punch.device_user_id))
        .where(DeviceUser.employee_pk == row.id)
    ) or 0
    sessions = db.scalar(select(func.count()).select_from(AttendanceSession).where(AttendanceSession.employee_pk == row.id)) or 0
    if punches or sessions:
        row.employment_status = "inactive"
        audit(db, user, "deactivate", "employee", row.employee_id, "History kept")
        db.commit()
        return {"ok": True, "deactivated": True, "detail": "Employee was deactivated. Attendance history is kept."}
    audit(db, user, "delete", "employee", row.employee_id, row.full_name)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/employees/{employee_id}/attendance")
def employee_attendance(
    employee_id: str,
    start_date: str = "",
    end_date: str = "",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    _get_employee(db, employee_id)
    bundle = load_bundle(db, employee_id=employee_id, date_from=start_date, date_to=end_date)
    try:
        data = collect(
            {
                "report": "daily",
                "start_date": start_date,
                "end_date": end_date,
                "employee_id": employee_id,
                "include_inactive": "1",
            },
            bundle,
        )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"details": data["details"], "summary": data["summary"], "hours_note": data["hours_note"]}


@router.get("/holidays")
def list_holidays(db: Session = Depends(get_db), _: User = Depends(current_user)):
    branches, _shifts = _maps(db)
    rows = db.scalars(select(Holiday).order_by(Holiday.holiday_date)).all()
    return {
        "items": [holiday_out(row, branches[row.branch_id].name if row.branch_id in branches else "") for row in rows]
    }


@router.post("/holidays")
def create_holiday(body: HolidayIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = Holiday(holiday_date=body.holiday_date, name=body.name.strip(), branch_id=body.branch_id)
    db.add(row)
    db.flush()
    audit(db, user, "create", "holiday", str(row.id), f"{row.holiday_date} {row.name}")
    db.commit()
    return holiday_out(row)


@router.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = db.get(Holiday, holiday_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Holiday not found")
    audit(db, user, "delete", "holiday", str(row.id), row.name)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/leave")
def list_leave(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.execute(select(LeaveEntry, Employee).join(Employee, LeaveEntry.employee_pk == Employee.id).order_by(LeaveEntry.work_date.desc())).all()
    return {"items": [leave_out(leave, emp.employee_id, emp.full_name) for leave, emp in rows]}


@router.post("/leave")
def create_leave(body: LeaveIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    emp = _get_employee(db, body.employee_id.strip())
    existing = db.scalar(select(LeaveEntry).where(LeaveEntry.employee_pk == emp.id, LeaveEntry.work_date == body.work_date.strip()))
    if existing:
        existing.note = body.note.strip()
        existing.actor = user.username
        row = existing
    else:
        row = LeaveEntry(employee_pk=emp.id, work_date=body.work_date.strip(), note=body.note.strip(), actor=user.username)
        db.add(row)
    audit(db, user, "leave", "employee", emp.employee_id, body.work_date)
    db.commit()
    return leave_out(row, emp.employee_id, emp.full_name)


@router.delete("/leave/{leave_id}")
def delete_leave(leave_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    row = db.get(LeaveEntry, leave_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Leave not found")
    audit(db, user, "delete", "leave", str(row.id), row.work_date)
    db.delete(row)
    db.commit()
    return {"ok": True}
