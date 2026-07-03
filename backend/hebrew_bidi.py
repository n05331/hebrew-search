"""זיהוי ותיקון טקסט עברי שנשמר בסדר חזותי (הפוך).

קובצי PDF ישנים שנוצרו בתוכנות שאינן תומכות יוניקוד שומרים את שכבת הטקסט
בסדר חזותי - האותיות בכל שורה כתובות משמאל לימין, כך שכל מילה נקראת הפוך
("שלום" נשמר כ"םולש"). טקסט כזה שבור גם לחיפוש וגם לתצוגה.

הזיהוי מבוסס על שתי עובדות לשוניות:
1. אותיות סופיות (ך ם ן ף ץ) לעולם אינן פותחות מילה עברית - בטקסט הפוך
   הן מופיעות דווקא בתחילת מילים.
2. מילים עבריות שכיחות (של, את, על...) מופיעות בטקסט תקין ולא בהפוך.

התיקון הפיך-אורך: היפוך גרפמות (אות + סימני הניקוד הצמודים לה נשארים יחד)
עם שימור רצפי ספרות/לטינית (שנשמרים תמיד משמאל לימין, נבדק על קבצים
אמיתיים) - כך שאורך הטקסט אינו משתנה ומיקומי העמודים (segments) בקטלוג
נשארים תקפים. סוגריים אינם משוקפים - בקבצים חזותיים אמיתיים הם שמורים
כבר בצורת הגליף המוצג, והיפוך פשוט מחזיר אותם למקומם הנכון.

שני מצבי תיקון:
- ``lines``: היפוך כל שורה בשלמותה - מתאים לפלט חזותי גולמי (extract_text
  של pdfplumber, או מנוע OCR שפלט סדר חזותי).
- ``words``: היפוך תוכן כל מילה תוך שמירת סדר המילים - מתאים לטקסט שסדר
  המילים בו כבר נקבע נכון לפי קואורדינטות (הפלט הישן של pdf_smart).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Tuple

# אותיות סופיות - סמן הכיוון החזק ביותר
_FINALS = set("\u05DA\u05DD\u05DF\u05E3\u05E5")  # ך ם ן ף ץ

# מילים עבריות שכיחות מאוד (ללא תחיליות) - סמן משני
_COMMON_WORDS = {
    "של", "את", "על", "לא", "כל", "הוא", "היא", "זה", "גם", "כי",
    "אם", "או", "מן", "עם", "אין", "יש", "היה", "אשר", "אבל", "רק",
    "כמו", "אחד", "מה", "אני", "הם", "לפני", "אחרי", "בין", "כדי",
    "אמר", "דבר", "איש", "יום", "שנה", "בית", "אלא", "אף", "כך", "שם",
    "אשה", "ולא", "אל", "עוד", "אבן", "רבי", "וכל", "כאשר", "אלו",
}

_NIQQUD_RE = re.compile(r"[\u0591-\u05C7]")
_HEB_WORD_RE = re.compile(r"[\u05D0-\u05EA\u0591-\u05C7]{2,}")

# רצף ספרות/לטינית (כולל מפרידים פנימיים כמו במספרי טלפון ותאריכים) -
# נשמר תמיד בסדר שמאל-לימין גם באחסון חזותי, ולכן מוחזר לאחר ההיפוך
_LTR_RUN_RE = re.compile(r"[0-9A-Za-z]+(?:[.,:/\-][0-9A-Za-z]+)*")

# סף החלטה: דורש ראיות מובהקות כדי לא לגעת בטקסט תקין
_MIN_SCORE = 6.0


def _graphemes(s: str) -> List[str]:
    """פיצול לגרפמות: אות בסיס + סימני הניקוד/הטעמים שאחריה."""
    out: List[str] = []
    for ch in s:
        if out and unicodedata.combining(ch):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def reverse_visual(s: str) -> str:
    """היפוך מחרוזת חזותית ללוגית: גרפמות מהסוף להתחלה, עם שחזור רצפי
    ספרות/לטינית שנשארים משמאל לימין. משמר אורך."""
    reversed_s = "".join(reversed(_graphemes(s)))
    return _LTR_RUN_RE.sub(lambda m: m.group(0)[::-1], reversed_s)


def _hebrew_words(text: str) -> List[str]:
    """מילים עבריות (ללא ניקוד) באורך 2+ לצורך ניקוד הכיוון."""
    return [_NIQQUD_RE.sub("", w) for w in _HEB_WORD_RE.findall(text)]


def direction_score(text: str) -> float:
    """ניקוד "עבריות תקינה": גבוה = נראה כעברית לוגית, שלילי = חשוד כהפוך."""
    score = 0.0
    for w in _hebrew_words(text):
        if len(w) < 2:
            continue
        if w[-1] in _FINALS:
            score += 2.0
        if w[0] in _FINALS:
            score -= 2.0
        if w in _COMMON_WORDS:
            score += 1.0
    return score


def _reverse_lines(text: str) -> str:
    """היפוך כל שורה בשלמותה (סדר המילים וגם תוכנן)."""
    return "\n".join(reverse_visual(line) for line in text.split("\n"))


def _reverse_words_keep_order(text: str) -> str:
    """היפוך תוכן כל מילה תוך שמירת סדר המילים והרווחים (משמר אורך)."""
    parts = re.split(r"(\s+)", text)
    return "".join(p if not p or p.isspace() else reverse_visual(p) for p in parts)


def _looks_reversed(text: str) -> bool:
    """האם תווי המילים בטקסט הפוכים (בלי קשר לסדר המילים)."""
    if not text or not _HEB_WORD_RE.search(text):
        return False
    orig = direction_score(text)
    fixed = direction_score(_reverse_words_keep_order(text))
    return fixed >= _MIN_SCORE and fixed >= orig + _MIN_SCORE


def fix_visual_order(text: str, mode: str = "lines") -> Tuple[str, bool]:
    """מזהה ומתקן טקסט בסדר חזותי. מחזיר (טקסט, האם_תוקן).

    ``mode="lines"``: היפוך שורות מלא - לפלט חזותי גולמי (ברירת מחדל).
    ``mode="words"``: היפוך תוכן המילים בלבד - לטקסט שסדר מיליו כבר נכון.

    הזיהוי עצמו זהה בשני המצבים (ניקוד המילים אינו תלוי בסדרן); טקסט תקין
    מוחזר תמיד כמות שהוא.
    """
    if not _looks_reversed(text):
        return text, False
    if mode == "words":
        return _reverse_words_keep_order(text), True
    return _reverse_lines(text), True


def line_order_reversed(text: str) -> bool:
    """אומדן האם גם סדר המילים בשורות הפוך (ולא רק תוכן המילים).

    בטקסט לוגי תקין פיסוק סוגר (נקודה, פסיק...) מופיע בסוף שורות; כשסדר
    השורה הפוך הוא מופיע דווקא בתחילתן. משמש את תיקון-הקטלוג להבחין בין
    טקסט מ-pdf_smart (סדר מילים נכון) לפלט חזותי גולמי (הכל הפוך).
    """
    starts = ends = 0
    for line in text.split("\n"):
        t = line.strip()
        if len(t) < 2:
            continue
        if t[0] in ".,:;!?":
            starts += 1
        if t[-1] in ".,:;!?":
            ends += 1
    return starts > ends


def words_look_reversed(words: Iterable[str]) -> bool:
    """האם רשימת מילים (למשל מ-pdfplumber) נראית הפוכה ברמת התווים.

    משמש את החילוץ החכם: שם סדר המילים נקבע לפי קואורדינטות, ולכן השאלה
    היא רק האם תווי כל מילה הפוכים.
    """
    return _looks_reversed(" ".join(words))
