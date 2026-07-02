"""ניתוב חילוץ לפי סוג הקובץ."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ..config import settings
from ..logging_setup import get_logger
from . import docx_extractor, image_extractor, pdf_extractor, txt_extractor
from .base import ExtractResult, Page

log = get_logger("extract")


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in settings.supported_extensions


def extract_file(
    path: Path,
    allow_ocr: bool = True,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> ExtractResult:
    """מחלץ טקסט מקובץ לפי סיומת. מעולם לא זורק - מחזיר תוצאה ריקה במקרה כשל.

    ``allow_ocr=False`` מחלץ טקסט בלבד (שלב מהיר); OCR ירוץ מאוחר יותר ברקע.
    """
    ext = path.suffix.lower()
    try:
        if ext in settings.docx_extensions:
            return docx_extractor.extract(path)
        if ext in settings.pdf_extensions:
            return pdf_extractor.extract(path, allow_ocr=allow_ocr, progress_cb=progress_cb)
        if ext in settings.image_extensions:
            return image_extractor.extract(path, allow_ocr=allow_ocr, progress_cb=progress_cb)
        if ext in settings.text_extensions:
            return txt_extractor.extract(path)
    except Exception as exc:
        log.warning("חילוץ נכשל עבור %s: %s", path, exc)
        return ExtractResult(pages=[Page(number=1, text="")], source="error")

    return ExtractResult(pages=[Page(number=1, text="")], source="unsupported")
