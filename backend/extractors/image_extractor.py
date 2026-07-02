"""חילוץ טקסט מתמונות באמצעות OCR עברי."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ..logging_setup import get_logger
from . import ocr
from .base import ExtractResult, Page

log = get_logger("extract.image")


def extract(
    path: Path,
    allow_ocr: bool = True,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> ExtractResult:
    # תמונה היא תמיד OCR: בשלב המהיר אין טקסט, ומסמנים שנדרש OCR (ירוץ ברקע)
    if not allow_ocr:
        return ExtractResult(pages=[Page(number=1, text="")], source="ocr", needs_ocr=ocr.available())

    if not ocr.available():
        return ExtractResult(pages=[Page(number=1, text="")], source="ocr", needs_ocr=True)

    if progress_cb:
        progress_cb(0, 1)
    text = ocr.ocr_image_file(path)
    if progress_cb:
        progress_cb(1, 1)
    log.debug("OCR לתמונה %s החזיר %d תווים", path.name, len(text))
    return ExtractResult(pages=[Page(number=1, text=text)], source="ocr")
