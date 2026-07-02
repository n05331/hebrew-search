"""עטיפת OCR מבוססת Tesseract לזיהוי טקסט עברי מתמונות וסריקות.

המודול מזהה בעצמו אם Tesseract והתלויות זמינים, כדי שהאפליקציה תעבוד גם
לפני התקנת ה-OCR (הקבצים פשוט לא יעברו OCR). איתור נתיב ה-exe נעשה
ממשתנה סביבה, מהגדרות, או ממיקומי ברירת מחדל נפוצים ב-Windows.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..config import resource_root, settings
from ..logging_setup import get_logger

log = get_logger("extract.ocr")


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


def _find_tesseract() -> Optional[str]:
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


@lru_cache(maxsize=1)
def available() -> bool:
    """האם ניתן להריץ OCR (Tesseract + pytesseract + מנוע רינדור)."""
    if not settings.enable_ocr:
        return False
    cmd = _find_tesseract()
    if not cmd:
        log.info("Tesseract לא נמצא - OCR מושבת עד להתקנתו.")
        return False
    try:
        import pytesseract  # noqa: F401
    except Exception:
        log.info("pytesseract לא מותקן - OCR מושבת.")
        return False
    return True


def _configure() -> None:
    import pytesseract

    cmd = _find_tesseract()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


def _tessdata_config() -> str:
    """מחזיר קונפיג ל-pytesseract שמפנה לתיקיית המודלים של האפליקציה."""
    td = settings.tessdata_dir
    if td and Path(td).exists():
        # ללא מרכאות: pytesseract מפצל את הקונפיג לפי רווחים (הנתיב הקצר ללא רווחים)
        return f"--tessdata-dir {short_path(str(td))}"
    return ""


def preprocess_image(image):
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
        if img.width < 1500:
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        # שיפור ניגודיות עדין
        img = ImageEnhance.Contrast(img).enhance(1.4)

        # בינריזציה בשיטת Otsu (חישוב סף מהיסטוגרמה)
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


def ocr_image(image, preprocess: bool = True) -> str:
    """מריץ OCR על אובייקט תמונה (PIL) ומחזיר טקסט."""
    if not available():
        return ""
    import pytesseract

    _configure()
    _ensure_ascii_temp()
    try:
        img = preprocess_image(image) if preprocess else image
        config = _tessdata_config() + " --psm 3"
        return pytesseract.image_to_string(img, lang=settings.ocr_languages, config=config)
    except Exception as exc:
        log.warning("OCR נכשל: %s", exc)
        return ""


def ocr_image_file(path: Path) -> str:
    if not available():
        return ""
    from PIL import Image

    with Image.open(path) as img:
        return ocr_image(img)


def ocr_image_region(path: Path, rx: float, ry: float, rw: float, rh: float) -> str:
    """OCR על אזור נבחר בתמונה. הקואורדינטות יחסיות (0-1) לרוחב/גובה התמונה."""
    if not available():
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
        return ocr_image(crop)


def _ocr_workers() -> int:
    """מספר עובדי OCR מקביליים - מוגבל כדי לא להקפיא את המערכת."""
    try:
        n = os.cpu_count() or 2
    except Exception:
        n = 2
    return max(1, min(4, n - 1))


def render_and_ocr_pdf(
    path: Path,
    existing_texts: Optional[Dict[int, str]] = None,
    min_chars: int = 15,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    dpi: int = 300,
) -> List[Tuple[int, str]]:
    """מרנדר ומריץ OCR על עמודי PDF: רינדור סדרתי (pdfium אינו thread-safe)
    ו-OCR מקבילי (Tesseract כתת-תהליך). עמודים שכבר יש להם טקסט מדולגים.

    מחזיר רשימת (מספר_עמוד, טקסט). ``progress_cb(done, total)`` לדיווח התקדמות.
    """
    import pypdfium2 as pdfium

    _configure()
    _ensure_ascii_temp()
    existing_texts = existing_texts or {}
    pdf = pdfium.PdfDocument(str(path))
    try:
        n = len(pdf)
        scale = dpi / 72.0
        results: Dict[int, str] = {}
        todo: List[int] = []
        for i in range(n):
            prev = existing_texts.get(i, "")
            if len((prev or "").strip()) >= min_chars:
                results[i] = prev
            else:
                todo.append(i)

        done = n - len(todo)
        if progress_cb:
            progress_cb(done, n)

        workers = _ocr_workers()
        for start in range(0, len(todo), workers):
            batch = todo[start : start + workers]
            images = [pdf[i].render(scale=scale).to_pil() for i in batch]  # רינדור סדרתי
            with ThreadPoolExecutor(max_workers=workers) as ex:
                texts = list(ex.map(ocr_image, images))
            for i, txt in zip(batch, texts):
                results[i] = txt
            done += len(batch)
            if progress_cb:
                progress_cb(done, n)

        return [(i + 1, results.get(i, "")) for i in range(n)]
    finally:
        pdf.close()
