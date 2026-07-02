"""ניתוח כותרות בספרי טקסט לפי כללי "תורת אמת" ו"אוצריא".

כללי תורת אמת (תו בתחילת שורה):
- ``$`` כותרת כללית (h1), ``@`` כותרת מרכזית (h2), ``~`` כותרת משנה (h3).
כללי אוצריא (תגיות עוטפות): ``<h1>…</h1>``, ``<h2>…</h2>``, ``<h3>…</h3>``.

המודול מפיק "טקסט תצוגה" (display_text) שבו תווי הסימון הוסרו, ורשימת
כותרות עם היסטים בטקסט התצוגה. כל שירותי הספר (קטעים, חיפוש-בספר, עץ
כותרות, סימניות) עובדים על אותה מערכת היסטים - כך אין סתירות בין הדגשה,
קפיצה לכותרת ותצוגה.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .logging_setup import get_logger

log = get_logger("toc")

# תגיות אוצריא: <h1>כותרת</h1> (רווחים סביב מותרים)
_OTZARIA_RE = re.compile(r"^\s*<h([123])>(.*?)</h\1>\s*$", re.IGNORECASE)

# קודי תורת אמת בראש שורה
_TORAT_EMET_MARKS = {"$": 1, "@": 2, "~": 3}

_HEB_RE = re.compile(r"[\u05D0-\u05EA]")

# תווי קוד של תורת אמת בראש קובץ (שאינם כותרות $/@/~)
_LEGEND_LEAD_CHARS = set("!#^&*+=|%;`")


def _is_legend_line(line: str) -> bool:
    """שורת 'קוד' בראש קובץ תורת אמת - מסומנת בתו קוד שאינו כותרת."""
    s = line.strip()
    if not s:
        return False
    first = s[0]
    if first in _TORAT_EMET_MARKS:
        return False
    if first in _LEGEND_LEAD_CHARS:
        return True
    # שורה שמתחילה בסימן אחר ואין בה כמעט עברית - כנראה שורת קוד/הגדרה
    if not first.isalnum() and not _HEB_RE.match(first):
        heb_chars = len(_HEB_RE.findall(s))
        return heb_chars < max(2, len(s) // 4)
    return False


def parse_book(raw_text: str) -> Tuple[str, List[dict]]:
    """מפרק טקסט גולמי ל(טקסט תצוגה, רשימת כותרות).

    כל כותרת: ``{"level": 1|2|3, "title": str, "start": int, "end": int}``
    כשההיסטים מתייחסים לטקסט התצוגה.
    """
    display_parts: List[str] = []
    headings: List[dict] = []
    cursor = 0
    in_leading_legend = True

    for line in raw_text.splitlines():
        stripped = line.strip()

        # הסרת שורות קוד בראש הקובץ בלבד
        if in_leading_legend:
            if _is_legend_line(line):
                continue
            if stripped:
                in_leading_legend = False

        level = 0
        title = None

        if stripped and stripped[0] in _TORAT_EMET_MARKS:
            level = _TORAT_EMET_MARKS[stripped[0]]
            title = stripped[1:].strip()
        else:
            m = _OTZARIA_RE.match(line)
            if m:
                level = int(m.group(1))
                title = m.group(2).strip()

        if level and title is not None:
            if title:
                start = cursor
                display_parts.append(title)
                cursor += len(title)
                headings.append({"level": level, "title": title, "start": start, "end": cursor})
            # כותרת ריקה (תו סימון בלבד) - מוסרת לגמרי
            display_parts.append("\n")
            cursor += 1
            continue

        display_parts.append(line)
        cursor += len(line)
        display_parts.append("\n")
        cursor += 1

    return "".join(display_parts), headings


# ---- cache לפי (path, mtime) - ספרים גדולים לא ינותחו בכל בקשה ----
_CACHE: Dict[str, Tuple[float, str, List[dict]]] = {}
_CACHE_MAX = 6


def get_parsed(path: Path, raw_reader) -> Tuple[str, List[dict]]:
    """מחזיר (display_text, headings) עם cache לפי mtime.

    ``raw_reader(path) -> str`` נקרא רק בעת החטאה.
    """
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    hit = _CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1], hit[2]

    raw = raw_reader(path)
    display, headings = parse_book(raw)

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (mtime, display, headings)
    return display, headings
