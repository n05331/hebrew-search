"""טיפוסי יסוד משותפים למחלצים."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Page:
    """טקסט של עמוד/מקטע לוגי בקובץ."""

    number: int          # מספר עמוד (מתחיל מ-1); למסמכים ללא עמודים נשתמש ב-1
    text: str


@dataclass
class ExtractResult:
    """תוצר חילוץ מקובץ יחיד."""

    pages: List[Page] = field(default_factory=list)
    source: str = "extracted"   # extracted / ocr / mixed
    needs_ocr: bool = False     # האם התוכן ריק וייתכן שנדרש OCR

    @property
    def has_text(self) -> bool:
        return any(p.text and p.text.strip() for p in self.pages)
