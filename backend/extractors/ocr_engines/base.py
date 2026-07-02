"""מחלקת הבסיס למנועי OCR.

כל מנוע מממש זיהוי טקסט מתמונה בודדת, ומקבל חינם את לולאת הרינדור של PDF
(רינדור סדרתי - pdfium אינו thread-safe - וזיהוי באצוות בגודל שהמנוע קובע).
המנוע גם מתאר את עצמו ל-UI: שם, זמינות וסכימת הגדרות, כך שמסך ההגדרות
נבנה דינמית ומנוע חדש אינו דורש שינוי ב-frontend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


class OcrEngine:
    """ממשק אחיד לכל מנועי ה-OCR."""

    id: str = ""
    label: str = ""
    # כמה תמונות מעבדים באצווה אחת בלולאת ה-PDF
    pdf_batch: int = 1

    # ---- זהות וזמינות ----
    def available(self) -> bool:
        raise NotImplementedError

    def status(self) -> str:
        """תיאור קצר למסך ההגדרות (למשל 'מוכן' / 'לא מותקן')."""
        return "מוכן" if self.available() else "לא זמין"

    def invalidate(self) -> None:
        """איפוס מטמונים פנימיים לאחר שינוי הגדרות."""

    def settings_schema(self) -> List[dict]:
        """סכימת ההגדרות של המנוע ל-UI הדינמי.

        כל שדה: {key, label, type: select/number/bool, options?, min?, max?,
        default, help?}. הערכים נשמרים בטבלת settings הרגילה.
        """
        return []

    # ---- זיהוי ----
    def ocr_image(self, image) -> str:
        """מריץ OCR על אובייקט תמונה (PIL) ומחזיר טקסט."""
        raise NotImplementedError

    def ocr_images(self, images: List) -> List[str]:
        """זיהוי אצווה של תמונות. ברירת מחדל: סדרתי; מנוע רשאי להקביל."""
        return [self.ocr_image(img) for img in images]

    def render_dpi(self) -> int:
        """רזולוציית רינדור עמודי PDF."""
        return 300

    def render_and_ocr_pdf(
        self,
        path: Path,
        existing_texts: Optional[Dict[int, str]] = None,
        min_chars: int = 15,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> List[Tuple[int, str]]:
        """מרנדר ומריץ OCR על עמודי PDF. עמודים שכבר יש להם טקסט מדולגים.

        מחזיר רשימת (מספר_עמוד, טקסט). ``progress_cb(done, total)`` לדיווח.
        """
        import pypdfium2 as pdfium

        existing_texts = existing_texts or {}
        pdf = pdfium.PdfDocument(str(path))
        try:
            n = len(pdf)
            scale = self.render_dpi() / 72.0
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

            step = max(1, self.pdf_batch)
            for start in range(0, len(todo), step):
                batch = todo[start : start + step]
                images = [pdf[i].render(scale=scale).to_pil() for i in batch]  # רינדור סדרתי
                texts = self.ocr_images(images)
                for i, txt in zip(batch, texts):
                    results[i] = txt
                done += len(batch)
                if progress_cb:
                    progress_cb(done, n)

            return [(i + 1, results.get(i, "")) for i in range(n)]
        finally:
            pdf.close()
