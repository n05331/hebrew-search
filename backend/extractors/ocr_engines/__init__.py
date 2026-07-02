"""רישום מנועי ה-OCR ובחירת המנוע הפעיל לפי ההגדרות.

מנוע חדש מתווסף כאן בלבד: יצירת מופע והוספה ל-``_ENGINES``. ה-UI מקבל את
הרשימה, הזמינות וסכימת ההגדרות דרך ``describe_engines()`` ונבנה דינמית.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ...logging_setup import get_logger
from . import ocr_settings
from .base import OcrEngine
from .tesseract_engine import TesseractEngine

log = get_logger("extract.ocr")

_ENGINES: Dict[str, OcrEngine] = {}


def _engines() -> Dict[str, OcrEngine]:
    global _ENGINES
    if not _ENGINES:
        tess = TesseractEngine()
        _ENGINES = {tess.id: tess}
        try:
            from .surya_engine import SuryaEngine

            surya = SuryaEngine()
            _ENGINES[surya.id] = surya
        except ImportError:
            pass
    return _ENGINES


def get_engine(engine_id: Optional[str] = None) -> OcrEngine:
    """המנוע הפעיל לאינדוקס. נופל ל-Tesseract אם המבוקש אינו זמין."""
    engines = _engines()
    eid = engine_id or ocr_settings.get("ocr_engine") or "tesseract"
    eng = engines.get(eid)
    if eng is not None and eng.available():
        return eng
    if eng is not None and eid != "tesseract":
        log.warning("מנוע OCR '%s' אינו זמין - נופל ל-Tesseract", eid)
    return engines["tesseract"]


def get_region_engine() -> OcrEngine:
    """המנוע ל-OCR אזורי אינטראקטיבי (ברירת מחדל: Tesseract המהיר)."""
    return get_engine(ocr_settings.get("ocr_region_engine") or "tesseract")


def describe_engines() -> List[dict]:
    """תיאור כל המנועים ל-UI: זהות, זמינות וסכימת הגדרות."""
    out = []
    for eng in _engines().values():
        out.append({
            "id": eng.id,
            "label": eng.label,
            "available": eng.available(),
            "status": eng.status(),
            "settings": eng.settings_schema(),
        })
    return out


def invalidate() -> None:
    """איפוס מטמונים לאחר שינוי הגדרות (נקרא מ-PUT /api/settings)."""
    ocr_settings.invalidate()
    for eng in _engines().values():
        eng.invalidate()
