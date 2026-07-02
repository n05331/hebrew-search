"""מנוע OCR מבוסס Tesseract - מנוע ברירת המחדל, ארוז ב-EXE.

המנוע מזהה בעצמו אם Tesseract והתלויות זמינים, כדי שהאפליקציה תעבוד גם
בלעדיו (הקבצים פשוט לא יעברו OCR). איתור נתיב ה-exe נעשה מהגרסה הארוזה,
ממשתנה סביבה, או ממיקומי ברירת מחדל נפוצים ב-Windows.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from ...config import resource_root, settings
from ...logging_setup import get_logger
from . import ocr_settings
from .base import OcrEngine

log = get_logger("extract.ocr.tesseract")


def short_path(path: str) -> str:
    """ממיר נתיב Windows לצורת 8.3 הקצרה (ASCII).

    הכרחי כי Tesseract ב-CLI אינו מתמודד עם נתיבים המכילים תווים שאינם ASCII
    (למשל שם משתמש בעברית). אם ההמרה נכשלת (8.3 מושבת) מוחזר הנתיב המקורי.
    """
    if sys.platform != "win32" or not path:
        return path
    try:
        buf = ctypes.create_unicode_buffer(600)
        get_short = ctypes.windll.kernel32.GetShortPathNameW
        rv = get_short(str(path), buf, len(buf))
        if rv:
            return buf.value
    except Exception:
        pass
    return path


_temp_ready = False


def _ensure_ascii_temp() -> None:
    """מוודא שקבצים זמניים של pytesseract נכתבים לנתיב ASCII."""
    global _temp_ready
    if _temp_ready:
        return
    base = short_path(tempfile.gettempdir())
    if base and os.path.exists(base):
        tempfile.tempdir = base
    _temp_ready = True


_COMMON_WINDOWS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def find_tesseract() -> Optional[str]:
    # עדיפות ל-Tesseract המצורף לגרסה הארוזה (עצמאי, ללא תלות בהתקנה)
    bundled = resource_root() / "tesseract" / "tesseract.exe"
    if bundled.exists():
        return str(bundled)
    if settings.tesseract_cmd and Path(settings.tesseract_cmd).exists():
        return settings.tesseract_cmd
    env = os.environ.get("TESSERACT_CMD")
    if env and Path(env).exists():
        return env
    found = shutil.which("tesseract")
    if found:
        return found
    for p in _COMMON_WINDOWS_PATHS:
        if Path(p).exists():
            return p
    return None


def custom_tessdata_dir() -> Path:
    """תיקיית מודלים מותאמים-אישית (תוצרי אשף האימון)."""
    return settings.data_dir / "tessdata_custom"


def list_custom_models() -> List[str]:
    """שמות המודלים המותאמים הזמינים (ללא סיומת)."""
    d = custom_tessdata_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.traineddata"))


def preprocess_image(image, upscale: bool = True, contrast: bool = True, binarize: bool = True):
    """עיבוד-מקדים לשיפור דיוק ה-OCR בעברית.

    הצינור המקובל: גווני אפור, הגדלת תמונות קטנות, שיפור ניגודיות עדין,
    ובינריזציה אדפטיבית (Otsu). משפר משמעותית סריקות באיכות בינונית.
    """
    from PIL import Image, ImageEnhance, ImageOps

    img = image
    try:
        # גווני אפור
        if img.mode not in ("L", "1"):
            img = ImageOps.grayscale(img)

        # הגדלת תמונות קטנות (מתחת ל~1500px רוחב) פי 2
        if upscale and img.width < 1500:
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        # שיפור ניגודיות עדין
        if contrast:
            img = ImageEnhance.Contrast(img).enhance(1.4)

        # בינריזציה בשיטת Otsu (חישוב סף מהיסטוגרמה)
        if binarize:
            hist = img.histogram()
            total = sum(hist)
            if total > 0:
                sum_all = sum(i * h for i, h in enumerate(hist))
                sum_b = 0.0
                w_b = 0
                max_var = 0.0
                threshold = 127
                for i in range(256):
                    w_b += hist[i]
                    if w_b == 0:
                        continue
                    w_f = total - w_b
                    if w_f == 0:
                        break
                    sum_b += i * hist[i]
                    m_b = sum_b / w_b
                    m_f = (sum_all - sum_b) / w_f
                    var_between = w_b * w_f * (m_b - m_f) ** 2
                    if var_between > max_var:
                        max_var = var_between
                        threshold = i
                img = img.point(lambda p, t=threshold: 255 if p > t else 0)

        return img
    except Exception as exc:
        log.debug("עיבוד-מקדים נכשל, ממשיך עם המקור: %s", exc)
        return image


def _ocr_workers() -> int:
    """מספר עובדי OCR מקביליים - מוגבל כדי לא להקפיא את המערכת."""
    try:
        n = os.cpu_count() or 2
    except Exception:
        n = 2
    return max(1, min(4, n - 1))


class TesseractEngine(OcrEngine):
    id = "tesseract"
    label = "Tesseract (מובנה)"

    def __init__(self) -> None:
        self._available: Optional[bool] = None
        self.pdf_batch = _ocr_workers()

    # ---- זמינות ----
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        if not settings.enable_ocr:
            self._available = False
            return False
        cmd = find_tesseract()
        if not cmd:
            log.info("Tesseract לא נמצא - OCR מושבת עד להתקנתו.")
            self._available = False
            return False
        try:
            import pytesseract  # noqa: F401
        except Exception:
            log.info("pytesseract לא מותקן - OCR מושבת.")
            self._available = False
            return False
        self._available = True
        return True

    def status(self) -> str:
        return "מוכן" if self.available() else "Tesseract לא נמצא"

    def invalidate(self) -> None:
        self._available = None

    def settings_schema(self) -> List[dict]:
        model_options = [{"value": "", "label": "עברית מובנה (heb)"}] + [
            {"value": m, "label": f"{m} (מודל מאומן)"} for m in list_custom_models()
        ]
        return [
            {
                "key": "ocr_traineddata", "label": "מודל שפה",
                "type": "select", "options": model_options,
                "default": "",
                "help": "מודל מותאם שנוצר באשף האימון, או המודל העברי המובנה",
            },
            {
                "key": "ocr_languages", "label": "שפות זיהוי",
                "type": "select",
                "options": [
                    {"value": "heb+eng", "label": "עברית + אנגלית"},
                    {"value": "heb", "label": "עברית בלבד"},
                ],
                "default": "heb+eng",
            },
            {
                "key": "ocr_psm", "label": "ניתוח פריסת עמוד (PSM)",
                "type": "select",
                "options": [
                    {"value": "3", "label": "אוטומטי (ברירת מחדל)"},
                    {"value": "1", "label": "אוטומטי + זיהוי כיוון"},
                    {"value": "4", "label": "עמודה אחת של טקסט"},
                    {"value": "6", "label": "בלוק טקסט אחיד"},
                    {"value": "11", "label": "טקסט מפוזר"},
                ],
                "default": "3",
                "help": "לעלונים עם עמודות - אוטומטי; לעמוד ספר פשוט - בלוק אחיד עשוי לדייק יותר",
            },
            {
                "key": "ocr_dpi", "label": "רזולוציית רינדור PDF (DPI)",
                "type": "number", "min": 150, "max": 600, "default": "300",
                "help": "גבוה יותר = מדויק יותר אך איטי; 300 מומלץ לרוב הסריקות",
            },
            {
                "key": "ocr_preprocess", "label": "עיבוד-מקדים לתמונה",
                "type": "bool", "default": "1",
                "help": "גווני אפור, הגדלה, ניגודיות ובינריזציה - משפר סריקות באיכות בינונית",
            },
            {
                "key": "ocr_upscale", "label": "הגדלת תמונות קטנות",
                "type": "bool", "default": "1", "depends": "ocr_preprocess",
            },
            {
                "key": "ocr_contrast", "label": "שיפור ניגודיות",
                "type": "bool", "default": "1", "depends": "ocr_preprocess",
            },
            {
                "key": "ocr_binarize", "label": "בינריזציה (שחור-לבן)",
                "type": "bool", "default": "1", "depends": "ocr_preprocess",
            },
        ]

    # ---- תצורה אפקטיבית ----
    def _configure(self) -> None:
        import pytesseract

        cmd = find_tesseract()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

    def _effective_lang_and_dir(self) -> tuple[str, Optional[Path]]:
        """מחשב את צירוף השפות ותיקיית המודלים לפי ההגדרות.

        כשנבחר מודל מותאם, מוודאים שהמודלים המובנים (heb/eng) קיימים גם
        בתיקייה המותאמת - ל-Tesseract יש --tessdata-dir יחיד.
        """
        langs = ocr_settings.get("ocr_languages") or "heb+eng"
        custom = ocr_settings.get("ocr_traineddata")
        base_dir = settings.tessdata_dir if Path(settings.tessdata_dir).exists() else None

        if custom:
            cdir = custom_tessdata_dir()
            model_file = cdir / f"{custom}.traineddata"
            if model_file.exists():
                # השלמת מודלים מובנים לתיקייה המותאמת (העתקה חד-פעמית)
                if base_dir:
                    for part in langs.split("+"):
                        src = Path(base_dir) / f"{part}.traineddata"
                        dst = cdir / f"{part}.traineddata"
                        if src.exists() and not dst.exists():
                            try:
                                shutil.copy2(src, dst)
                            except Exception as exc:
                                log.warning("העתקת מודל %s נכשלה: %s", part, exc)
                # המודל המותאם מחליף את heb בצירוף
                parts = [p for p in langs.split("+") if p != "heb"]
                lang = "+".join([custom] + parts)
                return lang, cdir
            log.warning("המודל המותאם %s לא נמצא - נופל למודל המובנה", custom)

        return langs, base_dir

    def _config_str(self) -> tuple[str, str]:
        """מחזיר (lang, config) להרצת pytesseract לפי ההגדרות הנוכחיות."""
        lang, tessdir = self._effective_lang_and_dir()
        parts = []
        if tessdir:
            # ללא מרכאות: pytesseract מפצל את הקונפיג לפי רווחים (הנתיב הקצר ללא רווחים)
            parts.append(f"--tessdata-dir {short_path(str(tessdir))}")
        psm = ocr_settings.get("ocr_psm") or "3"
        parts.append(f"--psm {psm}")
        return lang, " ".join(parts)

    def render_dpi(self) -> int:
        dpi = ocr_settings.get_int("ocr_dpi", 300)
        return min(600, max(150, dpi))

    # ---- זיהוי ----
    def ocr_image(self, image) -> str:
        if not self.available():
            return ""
        import pytesseract

        self._configure()
        _ensure_ascii_temp()
        try:
            if ocr_settings.get_bool("ocr_preprocess"):
                img = preprocess_image(
                    image,
                    upscale=ocr_settings.get_bool("ocr_upscale"),
                    contrast=ocr_settings.get_bool("ocr_contrast"),
                    binarize=ocr_settings.get_bool("ocr_binarize"),
                )
            else:
                img = image
            lang, config = self._config_str()
            return pytesseract.image_to_string(img, lang=lang, config=config)
        except Exception as exc:
            log.warning("OCR נכשל: %s", exc)
            return ""

    def ocr_images(self, images: List) -> List[str]:
        """OCR מקבילי - Tesseract רץ כתת-תהליך ולכן threads מקבילים באמת."""
        if len(images) <= 1:
            return [self.ocr_image(img) for img in images]
        with ThreadPoolExecutor(max_workers=min(len(images), _ocr_workers())) as ex:
            return list(ex.map(self.ocr_image, images))
