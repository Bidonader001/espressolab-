"""The logo appears in every PDF and workbook, and a missing file never breaks an export."""

from __future__ import annotations

import io
import zipfile

import pytest

from app import branding
from test_app import _device
from test_market_ready import _load

RANGE = {"start_date": "2026-10-01", "end_date": "2026-10-04", "source": "device"}


@pytest.fixture()
def with_data(client, auth):
    device = _device(client, auth, name="Kitchen")
    logs = [
        {"user_id": "1", "punched_at": "2026-10-01T09:00:00", "punch": 0},
        {"user_id": "1", "punched_at": "2026-10-01T17:00:00", "punch": 1},
    ]
    _load(client, auth, device["id"], [{"user_id": "1", "name": "Lena Logo"}], logs)


def _media(payload: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as book:
        return [name for name in book.namelist() if name.startswith("xl/media/")]


def test_logo_file_is_shipped_with_the_backend():
    assert branding.LOGO_PATH.is_file()
    assert abs(branding.LOGO_RATIO - 85 / 267) < 0.001


@pytest.mark.parametrize("report", ["monthly", "daily", "late", "absences", "hours", "employees"])
def test_export_pdfs_and_workbooks_carry_the_logo(client, auth, with_data, report):
    pdf = client.get("/api/v1/exports", headers=auth, params={**RANGE, "report": report, "format": "pdf"})
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF") and b"/Subtype /Image" in pdf.content
    book = client.get("/api/v1/exports", headers=auth, params={**RANGE, "report": report, "format": "xlsx"})
    assert book.status_code == 200, book.text
    assert _media(book.content), "the workbook must contain the logo image"


def test_session_log_reports_carry_the_logo(client, auth, with_data):
    params = {"work_date": "2026-10-01", "period": "daily"}
    pdf = client.get("/api/v1/reports/pdf", headers=auth, params=params)
    assert pdf.status_code == 200 and b"/Subtype /Image" in pdf.content
    book = client.get("/api/v1/reports/excel", headers=auth, params=params)
    assert book.status_code == 200 and _media(book.content)


def test_csv_stays_plain_text(client, auth, with_data):
    csv_file = client.get("/api/v1/exports", headers=auth, params={**RANGE, "report": "monthly", "format": "csv"})
    assert csv_file.status_code == 200 and b"/Subtype /Image" not in csv_file.content


def test_a_missing_logo_does_not_break_exports(client, auth, with_data, monkeypatch, tmp_path):
    monkeypatch.setattr(branding, "LOGO_PATH", tmp_path / "gone.png")
    pdf = client.get("/api/v1/exports", headers=auth, params={**RANGE, "report": "monthly", "format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and b"/Subtype /Image" not in pdf.content
    book = client.get("/api/v1/exports", headers=auth, params={**RANGE, "report": "monthly", "format": "xlsx"})
    assert book.status_code == 200 and not _media(book.content)
