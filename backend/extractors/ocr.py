"""חזית ה-OCR של המחלצים - מאצילה למנוע הפעיל דרך רישום המנועים.

הלוגיקה עצמה עברה לחבילת ``ocr_engines`` (מנוע לכל מימוש + registry).
המודול הזה שומר על ה-API הוותיק שהמחלצים והשרת משתמשים בו.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..logging_setup import get_logger
from . import ocr_engines

log = get_logger("extract.ocr")


def available() -> bool:
    """האם ניתן להריץ OCR (מנוע כלשהו זמין)."""
    return ocr_engines.get_engine().available()


def ocr_image(image, preprocess: bool = True) -> str:
    """מריץ OCR על אובייקט תמונה (PIL) במנוע הפעיל ומחזיר טקסט."""
    return ocr_engines.get_engine().ocr_image(image)


def ocr_image_file(path: Path) -> str:
    engine = ocr_engines.get_engine()
    if not engine.available():
        return ""
    from PIL import Image

    with Image.open(path) as img:
        return engine.ocr_image(img)


def ocr_image_region(path: Path, rx: float, ry: float, rw: float, rh: float) -> str:
    """OCR על אזור נבחר בתמונה. הקואורדינטות יחסיות (0-1) לרוחב/גובה התמונה.

    משתמש במנוע האזורי (מהיר, אינטראקטיבי) - לא בהכרח מנוע האינדוקס.
    """
    engine = ocr_engines.get_region_engine()
    if not engine.available():
        return ""
    from PIL import Image

    with Image.open(path) as img:
        w, h = img.size
        box = (
            max(0, int(rx * w)),
            max(0, int(ry * h)),
            min(w, int((rx + rw) * w)),
            min(h, int((ry + rh) * h)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            return ""
        crop = img.crop(box)
        return engine.ocr_image(crop)


def render_and_ocr_pdf(
    path: Path,
    existing_texts: Optional[Dict[int, str]] = None,
    min_chars: int = 15,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[Tuple[int, str]]:
    """מרנדר ומריץ OCR על עמודי PDF במנוע הפעיל."""
    return ocr_engines.get_engine().render_and_ocr_pdf(
        path, existing_texts=existing_texts, min_chars=min_chars, progress_cb=progress_cb
    )
