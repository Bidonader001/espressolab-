"""Session-log workbook and PDF from the older BunkerAtt period report, without salary columns."""

from __future__ import annotations

import re
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.branding import add_excel_logo, pdf_logo
from app.time_utils import format_hours, hours_status, period_range

ORANGE = PatternFill("solid", fgColor="3B82F6")
INK = PatternFill("solid", fgColor="1C1C1C")
RED = PatternFill("solid", fgColor="FFC7C7")
GREEN = PatternFill("solid", fgColor="C6F4D6")
PURPLE = PatternFill("solid", fgColor="E3D0F2")
PDF_ORANGE = colors.HexColor("#3B82F6")
PDF_INK = colors.HexColor("#1C1C1C")
PDF_RED = colors.HexColor("#FFC7C7")
PDF_GREEN = colors.HexColor("#C6F4D6")
PDF_PURPLE = colors.HexColor("#E3D0F2")
HEADERS = ["Name", "ID", "Shift", "Clock in", "Clock out", "Total hours", "Late"]
AVG_HEADERS = ["Name", "ID", "Days worked", "Sessions", "Total hours", "Avg hours / day"]
THIN = Border(
    left=Side(style="thin", color="DDDDDD"),
    right=Side(style="thin", color="DDDDDD"),
    top=Side(style="thin", color="DDDDDD"),
    bottom=Side(style="thin", color="DDDDDD"),
)


def file_tag(employee_id: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9._-]+", "-", (employee_id or "").strip())[:40]
    return f"-{raw}" if raw else ""


def resolve_period(period: str, work_date: str) -> tuple[str, str, str]:
    day = date.fromisoformat(work_date) if (work_date or "").strip() else date.today()
    start, end = period_range(period, day)
    return start.isoformat(), end.isoformat(), (period or "daily").lower()


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso)


def _late_label(row: dict) -> str:
    minutes = int(row.get("minutes_late") or 0)
    if minutes <= 0:
        return "On time"
    return f"Late {minutes} min"


def prepare_rows(sessions: list[dict]) -> list[dict]:
    rows = []
    for session in sessions:
        hours = session.get("hours")
        closed = bool(session.get("clock_out"))
        rows.append(
            {
                **session,
                "employee_name": session.get("employee_name") or "",
                "hours_formatted": "IN PROGRESS" if not closed else format_hours(float(hours) if hours is not None else None),
                "hours_status": "open" if not closed else hours_status(float(hours) if hours is not None else None),
                "late_label": _late_label(session),
            }
        )
    return rows


def summarize(rows: list[dict]) -> dict:
    closed = [r for r in rows if r.get("clock_out") and r.get("hours") is not None]
    total = sum(float(r["hours"]) for r in closed)
    by_emp: dict[str, dict] = {}
    for row in closed:
        eid = row["employee_id"]
        item = by_emp.setdefault(eid, {"name": row["employee_name"], "hours": 0.0, "days": set(), "sessions": 0})
        item["hours"] += float(row["hours"])
        item["days"].add(row.get("work_date"))
        item["sessions"] += 1
    people = []
    for eid, value in by_emp.items():
        days = max(1, len(value["days"]))
        avg = value["hours"] / days
        people.append(
            {
                "employee_id": eid,
                "employee_name": value["name"],
                "days_worked": len(value["days"]),
                "sessions": value["sessions"],
                "total_hours": round(value["hours"], 2),
                "avg_hours": round(avg, 2),
                "total_formatted": format_hours(value["hours"]),
                "avg_formatted": format_hours(avg),
            }
        )
    people.sort(key=lambda item: (item.get("employee_name") or "").lower())
    count = len(people)
    avg_emp = (total / count) if count else 0.0
    return {
        "sessions": len(rows),
        "closed": len(closed),
        "total_hours": round(total, 2),
        "total_formatted": format_hours(total) if closed else "0:00",
        "avg_hours_per_employee": round(avg_emp, 2),
        "avg_formatted": format_hours(avg_emp) if count else "—",
        "employees": people,
    }


def _fill_for(status: str):
    if status == "under":
        return RED, PDF_RED
    if status == "exact":
        return GREEN, PDF_GREEN
    if status == "over":
        return PURPLE, PDF_PURPLE
    return None, None


def _row_values(row: dict) -> list:
    return [
        row["employee_name"],
        row["employee_id"],
        row.get("shift_name") or "—",
        _fmt_time(row.get("clock_in")),
        _fmt_time(row.get("clock_out")) if row.get("clock_out") else "—",
        row.get("hours_formatted") or "—",
        row.get("late_label") or "On time",
    ]


def build_excel(rows: list[dict], summary: dict, start: str, end: str, kind: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    title_font = Font(bold=True, color="FFFFFF", size=14)
    head_font = Font(bold=True, color="FFFFFF")
    ws.append(["EspressoLab Attendance", f"{kind.title()} attendance report"])
    ws.merge_cells("A1:B1")
    ws["A1"].font = title_font
    ws["A1"].fill = ORANGE
    ws["B1"].fill = ORANGE
    ws["B1"].font = Font(color="FFFFFF")
    ws.append(["Period", f"{start} to {end}"])
    ws.append(["Closed sessions", summary["closed"], "Total hours", summary["total_formatted"]])
    ws.append(["Average hours / employee", summary["avg_formatted"]])
    add_excel_logo(ws, "D1")
    ws.append([])
    ws.append(HEADERS)
    for cell in ws[ws.max_row]:
        cell.font = head_font
        cell.fill = INK
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        ws.append(_row_values(row))
        excel_fill, _pdf_fill = _fill_for(row.get("hours_status") or "")
        if excel_fill and row.get("clock_out"):
            ws.cell(ws.max_row, 6).fill = excel_fill
        for cell in ws[ws.max_row]:
            cell.border = THIN
    if summary["employees"]:
        avg = wb.create_sheet("Employee summary")
        avg.append(["EspressoLab Attendance", "Hours"])
        avg.merge_cells("A1:B1")
        avg["A1"].font = title_font
        avg["A1"].fill = ORANGE
        avg["B1"].fill = ORANGE
        avg.append(["Period", f"{start} to {end}"])
        add_excel_logo(avg, "D1")
        avg.append([])
        avg.append(AVG_HEADERS)
        for cell in avg[avg.max_row]:
            cell.font = head_font
            cell.fill = INK
        for person in summary["employees"]:
            avg.append(
                [
                    person["employee_name"],
                    person["employee_id"],
                    person["days_worked"],
                    person["sessions"],
                    person["total_formatted"],
                    person["avg_formatted"],
                ]
            )
        for idx in range(1, avg.max_column + 1):
            avg.column_dimensions[get_column_letter(idx)].width = 20
    for idx in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(idx)].width = 18
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


PDF_WIDTH = A4[0] - 56  # portrait A4 between 28 pt margins


def _widths(weights: tuple[float, ...]) -> list[float]:
    """Column widths that add up to the page width, so a portrait page never overflows."""
    total = sum(weights)
    return [PDF_WIDTH * weight / total for weight in weights]


def build_pdf(rows: list[dict], summary: dict, start: str, end: str, kind: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=f"EspressoLab Attendance {kind} attendance",
        leftMargin=28,
        rightMargin=28,
        topMargin=28,
        bottomMargin=28,
    )
    styles = getSampleStyleSheet()
    logo = pdf_logo(150)
    story = [
        logo if logo is not None else Paragraph("EspressoLab Attendance", styles["Title"]),
        Spacer(1, 6),
        Paragraph(f"{kind.title()} attendance · {start} to {end} · EspressoLab Attendance", styles["Normal"]),
        Paragraph(
            f"Closed sessions {summary['closed']} · Total {summary['total_formatted']} · "
            f"Avg per employee {summary['avg_formatted']}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    if summary["employees"]:
        story.append(Paragraph("Employee summary", styles["Heading2"]))
        avg_data = [AVG_HEADERS]
        for person in summary["employees"]:
            avg_data.append(
                [
                    person["employee_name"],
                    person["employee_id"],
                    person["days_worked"],
                    person["sessions"],
                    person["total_formatted"],
                    person["avg_formatted"],
                ]
            )
        avg_table = Table(avg_data, repeatRows=1, colWidths=_widths((2.6, 0.8, 1.0, 1.0, 1.0, 1.2)))
        avg_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 0), (-1, 0), PDF_ORANGE),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(avg_table)
        story.append(Spacer(1, 14))
    story.append(Paragraph("Session log", styles["Heading2"]))
    data = [HEADERS]
    status_by_row = [None]
    for row in rows:
        data.append(_row_values(row))
        status_by_row.append(row.get("hours_status") if row.get("clock_out") else None)
    table = Table(data, repeatRows=1, colWidths=_widths((2.3, 0.7, 0.9, 1.6, 1.6, 1.0, 1.2)))
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), PDF_INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]
    for index, status in enumerate(status_by_row):
        _excel, pdf_fill = _fill_for(status or "")
        if pdf_fill:
            style_cmds.append(("BACKGROUND", (5, index), (5, index), pdf_fill))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    doc.build(story)
    return buf.getvalue()
