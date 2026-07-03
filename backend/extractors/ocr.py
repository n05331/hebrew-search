"""חזית ה-OCR של המחלצים - מאצילה למנוע הפעיל דרך רישום המנועים.

הלוגיקה עצמה עברה לחבילת ``ocr_engines`` (מנוע לכל מימוש + registry).
המודול הזה שומר על ה-API הוותיק שהמחלצים והשרת משתמשים בו.
כל פלט עובר רשת ביטחון לתיקון סדר חזותי (עברית הפוכה) - ראו hebrew_bidi.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .. import hebrew_bidi
from ..logging_setup import get_logger
from . import ocr_engines

log = get_logger("extract.ocr")


def _bidi_safe(text: str, origin: str) -> str:
    """תיקון פלט מנוע שיצא בסדר חזותי (הפוך), עם אזהרה בלוג."""
    fixed, changed = hebrew_bidi.fix_visual_order(text)
    if changed:
        log.warning("פלט OCR בסדר חזותי (הפוך) תוקן: %s", origin)
    return fixed


def available() -> bool:
    """האם ניתן להריץ OCR (מנוע כלשהו זמין)."""
    return ocr_engines.get_engine().available()


def ocr_image(image, preprocess: bool = True) -> str:
    """מריץ OCR על אובייקט תמונה (PIL) במנוע הפעיל ומחזיר טקסט."""
    engine = ocr_engines.get_engine()
    return _bidi_safe(engine.ocr_image(image), engine.id)


def ocr_image_file(path: Path) -> str:
    engine = ocr_engines.get_engine()
    if not engine.available():
        return ""
    from PIL import Image

    with Image.open(path) as img:
        return _bidi_safe(engine.ocr_image(img), path.name)


def ocr_image_region(path: Path, rx: float, ry: float, rw: float, rh: float) -> str:
    """OCR על אזור נבחר בתמונה. הקואורדינטות יחסיות (0-1) לרוחב/גובה התמונה.

    משתמש במנוע האזורי (מהיר, אינטראקטיבי) - לא בהכרח מנוע האינדוקס.
    """
    engine = ocr_engines.get_region_engine()
    if not engine.available():
        return ""
    from PIL import Image

    with Image.open(path) as img:
        text = _ocr_pil_region(engine, img, rx, ry, rw, rh)
        return _bidi_safe(text, path.name)


def ocr_pdf_region(
    path: Path, page: int, rx: float, ry: float, rw: float, rh: float
) -> str:
    """OCR על אזור נבחר בעמוד PDF (העמוד 1-based, קואורדינטות יחסיות 0-1).

    העמוד מרונדר לתמונה ב-DPI של המנוע האזורי, נחתך ונשלח לזיהוי.
    """
    engine = ocr_engines.get_region_engine()
    if not engine.available():
        return ""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        if page < 1 or page > len(pdf):
            return ""
        scale = engine.render_dpi() / 72.0
        img = pdf[page - 1].render(scale=scale).to_pil()
    finally:
        pdf.close()
    text = _ocr_pil_region(engine, img, rx, ry, rw, rh)
    return _bidi_safe(text, f"{path.name} עמוד {page}")


def _ocr_pil_region(engine, img, rx: float, ry: float, rw: float, rh: float) -> str:
    """חיתוך אזור יחסי מתמונת PIL והרצת המנוע עליו."""
    w, h = img.size
    box = (
        max(0, int(rx * w)),
        max(0, int(ry * h)),
        min(w, int((rx + rw) * w)),
        min(h, int((ry + rh) * h)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return ""
    return engine.ocr_image(img.crop(box))


def render_and_ocr_pdf(
    path: Path,
    existing_texts: Optional[Dict[int, str]] = None,
    min_chars: int = 15,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    partial_cb: Optional[Callable[[List[Tuple[int, str]], int], None]] = None,
) -> List[Tuple[int, str]]:
    """מרנדר ומריץ OCR על עמודי PDF במנוע הפעיל."""
    return ocr_engines.get_engine().render_and_ocr_pdf(
        path, existing_texts=existing_texts, min_chars=min_chars,
        progress_cb=progress_cb, partial_cb=partial_cb,
    )
