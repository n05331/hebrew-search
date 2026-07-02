"""חילוץ טקסט מ-PDF, עם נפילה ל-OCR לעמודים סרוקים ללא שכבת טקסט.

תומך בשני מצבים:
- ``allow_ocr=False`` (שלב מהיר): חילוץ שכבת הטקסט בלבד. אם הקובץ סרוק
  (אין/מעט טקסט) מסומן ``needs_ocr=True`` - ה-OCR ירוץ מאוחר יותר ברקע.
- ``allow_ocr=True`` (רקע): מריץ OCR מקבילי על העמודים הסרוקים.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from ..config import settings
from ..logging_setup import get_logger
from . import ocr
from .base import ExtractResult, Page

log = get_logger("extract.pdf")

# סף מינימלי של תווים בעמוד כדי להיחשב "בעל שכבת טקסט"
_MIN_TEXT_CHARS = 15

# גרסת אלגוריתם החילוץ; שינוי גורם לחילוץ-טקסט-מחדש ברקע (ללא OCR מחדש)
EXTRACT_VERSION = "2"


def _extract_text_layer(path: Path):
    """מחזיר (pages, text_pages_count). לעולם לא זורק.

    לכל עמוד מנסים קודם חילוץ "חכם" (זיהוי טורים RTL - הימני ראשון, איחוי
    שורות לפסקאות, שימור כותרות) כדי שהאינדקס יכיל רצפי מילים נכונים
    לחיפוש. אם החילוץ החכם נכשל או מחזיר מעט מדי - נופלים ל-extract_text
    הרגיל של pdfplumber.
    """
    from . import pdf_smart

    pages: list[Page] = []
    text_pages = 0
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    txt = pdf_smart.extract_page_text(page)
                except Exception as exc:
                    log.debug("חילוץ חכם נכשל בעמוד %d של %s: %s", i, path.name, exc)
                    txt = ""
                if len(txt.strip()) < _MIN_TEXT_CHARS:
                    plain = page.extract_text() or ""
                    if len(plain.strip()) > len(txt.strip()):
                        txt = plain
                pages.append(Page(number=i, text=txt))
                if len(txt.strip()) >= _MIN_TEXT_CHARS:
                    text_pages += 1
    except Exception as exc:
        log.warning("קריאת PDF נכשלה עבור %s: %s", path.name, exc)
    return pages, text_pages


def extract(
    path: Path,
    allow_ocr: bool = True,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> ExtractResult:
    pages, text_pages = _extract_text_layer(path)
    total_pages = len(pages)
    scanned = total_pages == 0 or text_pages < total_pages

    # שלב מהיר: טקסט בלבד. אם סרוק - מסמנים שנדרש OCR (ירוץ ברקע).
    if not allow_ocr:
        needs_ocr = scanned and ocr.available()
        return ExtractResult(pages=pages, source="extracted", needs_ocr=needs_ocr)

    # שלב OCR (רקע): רק אם באמת סרוק וה-OCR זמין
    if scanned and ocr.available():
        try:
            existing: Dict[int, str] = {i: p.text for i, p in enumerate(pages)}
            ocr_pages = ocr.render_and_ocr_pdf(
                path, existing_texts=existing, min_chars=_MIN_TEXT_CHARS, progress_cb=progress_cb
            )
            new_pages = [Page(number=num, text=txt) for num, txt in ocr_pages]
            source = "ocr" if text_pages == 0 else "mixed"
            log.info("בוצע OCR ל-%s (%d עמודים)", path.name, len(new_pages))
            return ExtractResult(pages=new_pages, source=source)
        except Exception as exc:
            log.warning("OCR ל-PDF נכשל עבור %s: %s", path.name, exc)

    needs_ocr = scanned and not ocr.available()
    return ExtractResult(pages=pages, source="extracted", needs_ocr=needs_ocr)
