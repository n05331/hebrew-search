"""חילוץ קבצי טקסט (txt, md, csv, html וכו') עם זיהוי קידוד."""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from .base import ExtractResult, Page

log = get_logger("extract.txt")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    # ניסיון זיהוי קידוד חכם (charset-normalizer מותקן כתלות של requests/uvicorn)
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None:
            return str(best)
    except Exception as exc:  # נפילה לקידודים נפוצים
        log.debug("זיהוי קידוד נכשל, מנסה ברירות מחדל: %s", exc)

    for enc in ("utf-8-sig", "utf-8", "cp1255", "windows-1255", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract(path: Path) -> ExtractResult:
    text = _read_text(path)
    if path.suffix.lower() in {".html", ".htm", ".xml"}:
        text = _strip_markup(text)
    return ExtractResult(pages=[Page(number=1, text=text)], source="extracted")


def _strip_markup(text: str) -> str:
    """הסרת תגיות בסיסית מ-HTML/XML."""
    import re

    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text
