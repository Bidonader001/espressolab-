"""The EspressoLab logo on exported PDFs and workbooks. A missing file never breaks an export."""

from __future__ import annotations

import logging
from pathlib import Path

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"
LOGO_RATIO = 85 / 267  # height / width of assets/logo.png

log = logging.getLogger("espressolab")


def pdf_logo(width_pt: float = 150):
    """A reportlab Image flowable, or None when the logo file is unavailable."""
    if not LOGO_PATH.is_file():
        log.warning("Logo file not found at %s; exports are produced without it", LOGO_PATH)
        return None
    from reportlab.platypus import Image

    image = Image(str(LOGO_PATH), width=width_pt, height=width_pt * LOGO_RATIO)
    image.hAlign = "LEFT"
    return image


def add_excel_logo(ws, anchor: str, width_px: int = 150, row: int = 1) -> bool:
    """Place the logo on a worksheet and make the row tall enough to hold it."""
    if not LOGO_PATH.is_file():
        log.warning("Logo file not found at %s; workbook is produced without it", LOGO_PATH)
        return False
    from openpyxl.drawing.image import Image

    image = Image(str(LOGO_PATH))
    image.width = width_px
    image.height = round(width_px * LOGO_RATIO)
    ws.add_image(image, anchor)
    ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 0, image.height * 0.75 + 4)
    return True
