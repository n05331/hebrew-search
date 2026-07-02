"""הגדרות מרכזיות ונתיבי נתונים של האפליקציה.

כל הנתיבים נגזרים ממיקום נתוני-המשתמש (LOCALAPPDATA ב-Windows), כך שהאפליקציה
עובדת זהה בהרצה מהקוד ובגרסת ה-EXE הארוזה. ניתן לעקוף דרך משתנה הסביבה
``HEBREW_SEARCH_DATA``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "HebrewSearch"


def _default_data_dir() -> Path:
    """מחזיר את תיקיית נתוני-המשתמש הקבועה של האפליקציה."""
    override = os.environ.get("HEBREW_SEARCH_DATA")
    if override:
        return Path(override)

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / APP_NAME

    return Path.home() / f".{APP_NAME.lower()}"


def is_frozen() -> bool:
    """האם אנו רצים כתוך EXE ארוז (PyInstaller)."""
    return getattr(sys, "frozen", False)


def resource_root() -> Path:
    """שורש המשאבים הסטטיים (frontend בנוי, מודלים) - שונה בין קוד ל-EXE."""
    if is_frozen():
        # PyInstaller פורש את הקבצים ל-_MEIPASS
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


class Settings:
    """אובייקט הגדרות יחיד לשימוש בכל האפליקציה."""

    def __init__(self) -> None:
        self.data_dir: Path = _default_data_dir()
        self.index_dir: Path = self.data_dir / "index"
        self.db_path: Path = self.data_dir / "catalog.db"
        self.log_dir: Path = self.data_dir / "logs"

        # שורש קבצי ה-frontend הבנוי (dist)
        self.frontend_dir: Path = resource_root() / "frontend" / "dist"

        # הגדרות OCR (שאר הגדרות ה-OCR נשמרות ב-DB - ראו ocr_engines/ocr_settings)
        self.tesseract_cmd: str | None = os.environ.get("TESSERACT_CMD")
        self.enable_ocr: bool = True
        # תיקיית מודלי השפה (מצורפת ל-EXE); ניתן לעקוף דרך TESSDATA_DIR
        _td = os.environ.get("TESSDATA_DIR")
        self.tessdata_dir: Path = Path(_td) if _td else resource_root() / "tessdata"

        # הרחבות קבצים נתמכות
        self.text_extensions = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".htm", ".html"}
        self.docx_extensions = {".docx"}
        self.pdf_extensions = {".pdf"}
        self.image_extensions = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}

        # מגבלות בטיחות
        self.max_file_mb: int = 200
        self.snippet_window: int = 60  # תווים מכל צד של ההתאמה

    @property
    def supported_extensions(self) -> set[str]:
        return (
            self.text_extensions
            | self.docx_extensions
            | self.pdf_extensions
            | self.image_extensions
        )

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.index_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
