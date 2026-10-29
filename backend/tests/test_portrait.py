"""Every PDF and printed worksheet is portrait A4 and nothing runs off the page."""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app.exports import DETAIL_ALL
from test_app import _device
from test_market_ready import _load

PARAMS = {"start_date": "2026-10-01", "end_date": "2026-10-06", "source": "device"}


@pytest.fixture()
def people(client, auth):
    device = _device(client, auth, name="HQ")
    users = [{"user_id": "30", "name": "ABDELAZIZ.MOHAMED ABDELA LONGNAME"}, {"user_id": "31", "name": "Dina Daily"}]
    logs = []
    for user in ("30", "31"):
        logs += [
            {"user_id": user, "punched_at": "2026-10-01T09:46:28", "punch": 0},
            {"user_id": user, "punched_at": "2026-10-01T17:29:53", "punch": 1},
            {"user_id": user, "punched_at": "2026-10-04T09:00:00", "punch": 0},
        ]
    _load(client, auth, device["id"], users, logs)


def _pages(pdf: bytes):
    pymupdf = pytest.importorskip("pymupdf", reason="PDF page geometry needs PyMuPDF")
    return pymupdf.open(stream=pdf, filetype="pdf")


def _inside_page(doc) -> bool:
    for page in doc:
        width, height = page.rect.width, page.rect.height
        if not height > width:
            return False
        for block in page.get_text("blocks"):
            if block[0] < 0 or block[2] > width + 0.5:
                return False
    return True


@pytest.mark.parametrize("report", ["monthly", "daily", "late", "absences", "hours", "employees"])
def test_export_pdfs_are_portrait_and_fit(client, auth, people, report):
    columns = ",".join(DETAIL_ALL)  # the widest layout a user can pick
    pdf = client.get("/api/v1/exports", headers=auth, params={**PARAMS, "report": report, "format": "pdf", "columns": columns})
    assert pdf.status_code == 200, pdf.text
    assert _inside_page(_pages(pdf.content)), report


def test_session_log_pdf_is_portrait_and_fits(client, auth, people):
    pdf = client.get("/api/v1/reports/pdf", headers=auth, params={"work_date": "2026-10-01", "period": "monthly"})
    assert pdf.status_code == 200
    assert _inside_page(_pages(pdf.content))


def test_worksheets_print_portrait(client, auth, people):
    content = client.get("/api/v1/exports", headers=auth, params={**PARAMS, "report": "monthly", "format": "xlsx"}).content
    book = load_workbook(io.BytesIO(content))
    assert {book[name].page_setup.orientation for name in book.sheetnames} == {"portrait"}
