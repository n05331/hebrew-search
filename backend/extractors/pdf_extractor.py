"""חילוץ טקסט מ-PDF, עם נפילה ל-OCR לעמודים סרוקים ללא שכבת טקסט.

תומך בשני מצבים:
- ``allow_ocr=False`` (שלב מהיר): חילוץ שכבת הטקסט בלבד. אם הקובץ סרוק
  (אין/מעט טקסט) מסומן ``needs_ocr=True`` - ה-OCR ירוץ מאוחר יותר ברקע.
- ``allow_ocr=True`` (רקע): מריץ OCR מקבילי על העמודים הסרוקים.

מצב "התעלמות משכבת הטקסט" (``force_ocr`` או ההגדרה הגלובלית
``ocr_ignore_text_layer``) מריץ OCR על כל העמודים גם כשיש בהם טקסט מוטמע -
לקבצים ששכבת הטקסט שלהם פגומה. עמודים שכבר עברו OCR בריצה קודמת
(``existing_ocr`` - שמירת התקדמות חלקית) מנוצלים תמיד ולא נסרקים שוב.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .. import hebrew_bidi
from ..config import settings
from ..logging_setup import get_logger
from . import ocr
from .base import ExtractResult, Page
from .ocr_engines import ocr_settings

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
    הרגיל של pdfplumber. שכבת טקסט בסדר חזותי (קבצים ישנים) מזוהה ומתוקנת.
    """
    from . import pdf_smart

    pages: list[Page] = []
    text_pages = 0
    fixed_pages = 0
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
                # רשת ביטחון: תיקון סדר חזותי גם על נתיב הנפילה (החילוץ
                # החכם כבר מתקן בעצמו ברמת המילים)
                txt, was_fixed = hebrew_bidi.fix_visual_order(txt)
                if was_fixed:
                    fixed_pages += 1
                pages.append(Page(number=i, text=txt))
                if len(txt.strip()) >= _MIN_TEXT_CHARS:
                    text_pages += 1
    except Exception as exc:
        log.warning("קריאת PDF נכשלה עבור %s: %s", path.name, exc)
    if fixed_pages:
        log.info("תוקנה שכבת טקסט הפוכה (סדר חזותי): %s - %d עמודים", path.name, fixed_pages)
    return pages, text_pages


def _force_ocr_active(force_ocr: bool) -> bool:
    """האם להתעלם משכבת הטקסט: דגל פר-קובץ או ההגדרה הגלובלית."""
    return force_ocr or ocr_settings.get_bool("ocr_ignore_text_layer")


def extract(
    path: Path,
    allow_ocr: bool = True,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    force_ocr: bool = False,
    existing_ocr: Optional[Dict[int, str]] = None,
    partial_cb: Optional[Callable[[List[Tuple[int, str]], int], None]] = None,
) -> ExtractResult:
    """חילוץ PDF מלא.

    ``existing_ocr``: טקסטים של עמודים (1-based) שכבר עברו OCR בריצה קודמת
    שנקטעה - מנוצלים במקום סריקה חוזרת.
    ``partial_cb(pairs, total)``: דיווח תקופתי של תוצאות ה-OCR שהושלמו עד כה,
    לשמירת התקדמות חלקית.
    """
    force = _force_ocr_active(force_ocr)
    pages, text_pages = _extract_text_layer(path)
    total_pages = len(pages)
    scanned = total_pages == 0 or text_pages < total_pages

    # שלב מהיר: טקסט בלבד. אם סרוק (או במצב התעלמות משכבת הטקסט) -
    # מסמנים שנדרש OCR (ירוץ ברקע). שכבת הטקסט מאונדקסת בינתיים.
    if not allow_ocr:
        needs_ocr = (scanned or force) and ocr.available()
        return ExtractResult(pages=pages, source="extracted", needs_ocr=needs_ocr)

    # שלב OCR (רקע): אם סרוק, או שהתבקשה התעלמות משכבת הטקסט
    if (scanned or force) and ocr.available():
        try:
            if force:
                # מתעלמים משכבת הטקסט - אך עמודי OCR קודמים מנוצלים
                existing: Dict[int, str] = {}
            else:
                existing = {i: p.text for i, p in enumerate(pages)}
            for page_num, txt in (existing_ocr or {}).items():
                if txt and txt.strip():
                    existing[page_num - 1] = txt
            ocr_pages = ocr.render_and_ocr_pdf(
                path, existing_texts=existing, min_chars=_MIN_TEXT_CHARS,
                progress_cb=progress_cb, partial_cb=partial_cb,
            )
            new_pages = [Page(number=num, text=txt) for num, txt in ocr_pages]
            source = "ocr" if (force or text_pages == 0) else "mixed"
            log.info("בוצע OCR ל-%s (%d עמודים)", path.name, len(new_pages))
            return ExtractResult(pages=new_pages, source=source)
        except Exception as exc:
            log.warning("OCR ל-PDF נכשל עבור %s: %s", path.name, exc)

    needs_ocr = scanned and not ocr.available()
    return ExtractResult(pages=pages, source="extracted", needs_ocr=needs_ocr)
