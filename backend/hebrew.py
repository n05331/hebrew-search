"""מנוע נירמול וטוקניזציה בעברית - הלב של איכות החיפוש.

עברית מציבה אתגרים ייחודיים לחיפוש טקסט מלא:
- ניקוד וטעמי מקרא שאינם חלק מהמילה לצורכי חיפוש.
- אותיות סופיות (ך ם ן ף ץ) לעומת רגילות.
- תחיליות דבקות (ו/ה/ב/כ/ל/מ/ש) שמשנות את צורת המילה.
- גרש/גרשיים בראשי תיבות ובשמות.
- כתיב מלא/חסר.

המודול מספק פונקציה אחת לטוקניזציה עם היסטים (offsets) שמשמשת גם לבניית
האינדקס וגם להדגשת ההקשר על הטקסט המקורי - כך שהתנהגות החיפוש וההדגשה
תמיד עקבית.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List

# ניקוד עברי (U+0591..U+05C7) - נקדד וטעמים
_NIQQUD_RE = re.compile(r"[\u0591-\u05C7]")

# גרש/גרשיים עבריים ופיסוק שנרצה לנרמל
_GERESH = "\u05F3"      # ׳
_GERSHAYIM = "\u05F4"   # ״

# מיפוי אותיות סופיות -> רגילות (לצורכי התאמה בלבד)
_FINALS = {
    "\u05DA": "\u05DB",  # ך -> כ
    "\u05DD": "\u05DE",  # ם -> מ
    "\u05DF": "\u05E0",  # ן -> נ
    "\u05E3": "\u05E4",  # ף -> פ
    "\u05E5": "\u05E6",  # ץ -> צ
}
_FINALS_TABLE = {ord(k): v for k, v in _FINALS.items()}

# תחיליות דבקות נפוצות בעברית
_PREFIX_LETTERS = set("והבכלמש")

# סיומות נטייה נפוצות (ריבוי, שייכות, נקבה) - לסטמינג קל שמרחיב recall.
# מסודרות מהארוכה לקצרה כדי להסיר את ההתאמה הארוכה ביותר תחילה.
_SUFFIXES = [
    "יותיהם", "ותיהם", "יהם", "יהן", "ותינו", "ותיכם",
    "יות", "ים", "ות", "ייך", "ותי", "נו", "כם", "כן",
    "הם", "הן", "תי", "תם", "תן",
    "ים", "ות", "ה", "ת", "י", "ך",
]

# אות עברית בודדת
_HEB = "\u05D0-\u05EA"

# טוקן = רצף אותיות עברית / לטינית / ספרות (כולל ניקוד וגרשיים בתוך המילה)
_TOKEN_RE = re.compile(
    rf"[0-9A-Za-z{_HEB}\u0591-\u05C7{_GERESH}{_GERSHAYIM}']+"
)


@dataclass
class Token:
    """טוקן בודד עם מיקומו בטקסט המקורי."""

    surface: str      # הצורה המקורית כפי שמופיעה בטקסט
    start: int        # היסט התחלה בטקסט המקורי (תווים)
    end: int          # היסט סיום (לא כולל)
    norm: str         # צורה מנורמלת (בסיס להתאמה)
    stem: str         # צורה לאחר הסרת תחילית (להרחבת recall)


def strip_niqqud(text: str) -> str:
    """הסרת ניקוד וטעמי מקרא."""
    return _NIQQUD_RE.sub("", text)


def normalize_token(surface: str) -> str:
    """נירמול טוקן בודד לצורת התאמה קנונית.

    שלבים: נירמול Unicode, הסרת ניקוד, הסרת גרש/גרשיים, מיפוי אותיות סופיות,
    והמרה לאותיות קטנות (עבור לטינית).
    """
    t = unicodedata.normalize("NFKC", surface)
    t = strip_niqqud(t)
    t = t.replace(_GERESH, "").replace(_GERSHAYIM, "").replace("'", "").replace('"', "")
    t = t.translate(_FINALS_TABLE)
    t = t.lower()
    return t


def strip_prefixes(norm_token: str) -> str:
    """הסרת אשכול תחיליות דבקות מטוקן מנורמל, בזהירות.

    מסירים תחיליות מקבוצת {ו,ה,ב,כ,ל,מ,ש} כל עוד נשארות לפחות 3 אותיות עבריות,
    כדי לא לפגוע במילים קצרות (כמו "בית", "מים"). מחזירים את הבסיס להרחבת recall.
    """
    # רק לטוקנים עבריים בלבד
    if not norm_token or not all("\u05D0" <= c <= "\u05EA" for c in norm_token):
        return norm_token

    t = norm_token
    # מסירים עד שתי תחיליות (למשל "וכשה...") אך שומרים אורך מינימלי
    for _ in range(2):
        if len(t) >= 4 and t[0] in _PREFIX_LETTERS:
            candidate = t[1:]
            if len(candidate) >= 3:
                t = candidate
                continue
        break
    return t


def _normalize_suffix(suf: str) -> str:
    """מנרמל סיומת לאותה צורה של הטוקנים (אותיות סופיות -> רגילות)."""
    return suf.translate(_FINALS_TABLE)


# הסיומות מנורמלות פעם אחת (אותיות סופיות מומרות) וממוינות מהארוכה לקצרה,
# כדי שיתאימו לטוקנים המנורמלים (בהם אין אותיות סופיות).
_SUFFIXES_NORM = sorted(
    {_normalize_suffix(s) for s in _SUFFIXES}, key=len, reverse=True
)


def _strip_suffixes(token: str) -> str:
    """הסרת סיומת נטייה אחת (הארוכה ביותר) לצורך סטמינג קל."""
    for suf in _SUFFIXES_NORM:
        if token.endswith(suf) and len(token) - len(suf) >= 2:
            return token[: -len(suf)]
    return token


def light_stem(norm_token: str) -> str:
    """סטמינג עברי קל: הסרת תחיליות ואז סיומת נטייה.

    משמש את שדה ה-recall המשני בלבד; השדה הראשי שומר על הצורה המדויקת ולכן
    הדיוק אינו נפגע. מחבר צורות כמו ילד↔ילדים, ספר↔ספרים.
    """
    if not norm_token:
        return norm_token
    # נירמול הגנתי: אם התקבלה צורה לא-מנורמלת (אות סופית), נמיר אותה
    norm_token = norm_token.translate(_FINALS_TABLE)
    if not all("\u05D0" <= c <= "\u05EA" for c in norm_token):
        return norm_token
    base = strip_prefixes(norm_token)
    stemmed = _strip_suffixes(base)
    return stemmed if len(stemmed) >= 2 else base


def tokenize(text: str) -> List[Token]:
    """טוקניזציה של טקסט מקורי עם שמירת היסטים.

    משמש הן לבניית שדות האינדקס והן לאיתור הדגשות על הטקסט המקורי.
    """
    tokens: List[Token] = []
    for m in _TOKEN_RE.finditer(text):
        surface = m.group(0)
        norm = normalize_token(surface)
        if not norm:
            continue
        tokens.append(
            Token(
                surface=surface,
                start=m.start(),
                end=m.end(),
                norm=norm,
                stem=light_stem(norm),
            )
        )
    return tokens


def normalized_stream(text: str) -> str:
    """זרם טוקנים מנורמלים מופרד ברווחים - השדה הראשי לאינדקס."""
    return " ".join(tok.norm for tok in tokenize(text))


def stemmed_stream(text: str) -> str:
    """זרם טוקנים לאחר סטמינג קל - שדה משני להרחבת recall."""
    return " ".join(tok.stem for tok in tokenize(text))


def query_terms(query: str) -> List[str]:
    """מחזיר רשימת טוקנים מנורמלים מתוך שאילתה."""
    return [tok.norm for tok in tokenize(query)]


def query_match_set(query: str) -> set[str]:
    """קבוצת צורות (מנורמל + בסיס) של שאילתה, לצורך הדגשה."""
    forms: set[str] = set()
    for tok in tokenize(query):
        forms.add(tok.norm)
        forms.add(tok.stem)
    forms.discard("")
    return forms


def phrase_occurrence_spans(text: str, phrase_terms: List[str]) -> List[tuple]:
    """מחזיר טווחי (start, end) של כל הופעות רצף הביטוי השלם בטקסט.

    התאמה על הצורה המנורמלת (ללא ניקוד/סופיות), ללא הרחבת תחיליות/סיומות -
    כך שהביטוי מודגש רק כשהוא מופיע צמוד ושלם.
    """
    if not phrase_terms or not text:
        return []
    tokens = tokenize(text)
    norms = [t.norm for t in tokens]
    n = len(phrase_terms)
    spans: List[tuple] = []
    for i in range(0, len(norms) - n + 1):
        if norms[i : i + n] == phrase_terms:
            spans.append((tokens[i].start, tokens[i + n - 1].end))
    return spans


def word_occurrence_spans(text: str, match_forms: set[str]) -> List[tuple]:
    """טווחי הופעות של מילים בודדות (כולל הרחבת בסיס) - למצב חיפוש רגיל."""
    if not match_forms or not text:
        return []
    return [
        (tok.start, tok.end)
        for tok in tokenize(text)
        if tok.norm in match_forms or tok.stem in match_forms
    ]


def contains_phrase(text: str, phrase_terms: List[str]) -> bool:
    """האם רצף המילים ``phrase_terms`` מופיע צמוד בטקסט (על הצורה המנורמלת).

    משמש לאכיפת "ביטוי מדויק" בעברית: התאמה על הצורה המנורמלת (ללא ניקוד/סופיות)
    אך ללא הסרת תחיליות/סיומות, כך שהביטוי חייב להופיע כפי שהוא.
    """
    if not phrase_terms:
        return True
    norms = [tok.norm for tok in tokenize(text)]
    n = len(phrase_terms)
    if n == 0 or len(norms) < n:
        return False
    for i in range(0, len(norms) - n + 1):
        if norms[i : i + n] == phrase_terms:
            return True
    return False
