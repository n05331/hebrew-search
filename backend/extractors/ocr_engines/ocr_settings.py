"""גישה להגדרות OCR: טבלת settings בקטלוג, עם עקיפה ממשתני סביבה.

הערכים נשמרים ב-DB (נשלטים ממסך ההגדרות), ומשתני הסביבה הוותיקים
(OCR_LANGS וכו') ממשיכים לעבוד כעקיפה - לתאימות ולצרכי פיתוח.
נעשה שימוש במטמון קצר כדי לא לפנות ל-DB בכל עמוד; ``invalidate()``
נקרא לאחר כל שינוי הגדרות.
"""

from __future__ import annotations

import os
from threading import Lock
from typing import Dict, Optional

# מיפוי מפתח הגדרה -> משתנה סביבה עוקף (תאימות לאחור)
_ENV_OVERRIDES = {
    "ocr_languages": "OCR_LANGS",
}

DEFAULTS: Dict[str, str] = {
    "ocr_engine": "tesseract",         # המנוע לאינדוקס רקע
    "ocr_region_engine": "tesseract",  # המנוע ל-OCR אזורי אינטראקטיבי
    "ocr_export_engine": "tesseract",  # המנוע לייצוא טקסט (חילוץ מלא מהצפיין)
    "ocr_ignore_text_layer": "0",      # OCR תמיד, גם כשיש שכבת טקסט (איטי!)
    "ocr_languages": "heb+eng",
    "ocr_psm": "3",
    "ocr_dpi": "300",
    "ocr_preprocess": "1",
    "ocr_upscale": "1",
    "ocr_contrast": "1",
    "ocr_binarize": "1",
    "ocr_traineddata": "",             # ריק = מודל heb המובנה; אחרת שם מודל מותאם
    "ocr_surya_gpu": "0",              # האצת Vulkan על GPU משולב (ניסיוני)
}

_cache: Optional[Dict[str, str]] = None
_lock = Lock()


def _load() -> Dict[str, str]:
    from ...catalog import catalog

    values = dict(DEFAULTS)
    try:
        stored = catalog.all_settings()
        for k in DEFAULTS:
            v = stored.get(k)
            if v not in (None, ""):
                values[k] = v
    except Exception:
        pass
    for k, env_name in _ENV_OVERRIDES.items():
        env_v = os.environ.get(env_name)
        if env_v:
            values[k] = env_v
    return values


def get(key: str, default: str = "") -> str:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load()
        return _cache.get(key, default or DEFAULTS.get(key, ""))


def get_bool(key: str) -> bool:
    return get(key) in ("1", "true", "True", "on")


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get(key))
    except (TypeError, ValueError):
        return default


def invalidate() -> None:
    """איפוס המטמון - נקרא לאחר שמירת הגדרות."""
    global _cache
    with _lock:
        _cache = None
