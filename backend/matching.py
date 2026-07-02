"""מנוע התאמה מתקדם לחיפוש: מרכז את כל סמנטיקות ההתאמה במקום אחד.

אפשרויות (לפי דרישות הלקוח):
- ``fold_vy``   - "כתיב מלא/חסר": התאמה גם כשיש/חסרות אותיות ו/י.
- ``fold_aa``   - "אידיש": התאמה גם כשיש/חסרות אותיות ע/א.
- ``whole_word``- "מילה שלימה": ללא הרחבת תחיליות/סיומות.
- ``exact``     - "חיפוש מדויק": רצף המילים צמוד ובסדר שנכתב.
- ``min_words`` - "לפחות X מילים": מספיק ש-X מילים מהשאילתה יופיעו.
- ``proximity`` - חיפוש לא-מדויק: המילים בכל סדר במרחק עד N מילים (0 = ללא הגבלה).

אותה לוגיקה משמשת גם לסינון (האם המסמך תואם) וגם לטווחי ההדגשה -
כך שהמשתמש תמיד רואה בדיוק את מה שנמצא.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from . import hebrew


@dataclass
class MatchOptions:
    exact: bool = False
    whole_word: bool = False
    fold_vy: bool = False
    fold_aa: bool = False
    min_words: int = 0       # 0 = כל המילים
    proximity: int = 30      # 0 = ללא הגבלת מרחק


def fold_form(token: str, fold_vy: bool, fold_aa: bool) -> str:
    """מקפל צורה מנורמלת לפי אפשרויות כתיב מלא/חסר ואידיש."""
    t = token
    if fold_vy:
        t = t.replace("\u05D5", "").replace("\u05D9", "")  # ו, י
    if fold_aa:
        t = t.replace("\u05E2", "").replace("\u05D0", "")  # ע, א
    # אם הקיפול רוקן את הצורה - נשארים עם המקור (מילים כמו "או")
    return t if t else token


def full_fold(token: str) -> str:
    """קיפול מקסימלי (ו/י/ע/א) - משמש לשדה האינדקס content_fold."""
    return fold_form(token, True, True)


def analyze(full_text: str, query: str, opts: MatchOptions) -> Tuple[bool, List[Tuple[int, int]]]:
    """בודק האם המסמך תואם ומחזיר (תואם?, טווחי הדגשה בטקסט המקורי)."""
    qterms = hebrew.query_terms(query)
    if not qterms or not full_text:
        return False, []

    tokens = hebrew.tokenize(full_text)
    if not tokens:
        return False, []

    def fold(t: str) -> str:
        return fold_form(t, opts.fold_vy, opts.fold_aa)

    # ---- חיפוש מדויק: רצף צמוד ובסדר שנכתב ----
    if opts.exact:
        qf = [fold(q) for q in qterms]
        norms = [fold(t.norm) for t in tokens]
        n = len(qf)
        spans = []
        for i in range(0, len(norms) - n + 1):
            if norms[i : i + n] == qf:
                spans.append((tokens[i].start, tokens[i + n - 1].end))
        return bool(spans), spans

    # ---- חיפוש רגיל: איתור הופעות לכל מילת שאילתה ----
    q_pairs = []
    for q in qterms:
        qn = fold(q)
        qs = fold(hebrew.light_stem(q))
        q_pairs.append((qn, qs))

    matches_per_word: List[List[int]] = [[] for _ in qterms]
    for i, tok in enumerate(tokens):
        tn = fold(tok.norm)
        ts = fold(tok.stem) if not opts.whole_word else None
        for w, (qn, qs) in enumerate(q_pairs):
            if tn == qn:
                matches_per_word[w].append(i)
            elif not opts.whole_word and (ts == qs or ts == qn or tn == qs):
                matches_per_word[w].append(i)

    total_words = len(qterms)
    required = opts.min_words if 0 < opts.min_words < total_words else total_words

    matched_words = sum(1 for idxs in matches_per_word if idxs)
    if matched_words < required:
        return False, []

    # ---- בדיקת קרבה: חלון של proximity מילים המכיל לפחות required מילים שונות ----
    ok = False
    if required <= 1 or opts.proximity <= 0:
        ok = True
    else:
        events = sorted(
            (i, w) for w, idxs in enumerate(matches_per_word) for i in idxs
        )
        counts: dict = {}
        distinct = 0
        left = 0
        for right in range(len(events)):
            i_r, w_r = events[right]
            counts[w_r] = counts.get(w_r, 0) + 1
            if counts[w_r] == 1:
                distinct += 1
            while events[right][0] - events[left][0] > opts.proximity:
                i_l, w_l = events[left]
                counts[w_l] -= 1
                if counts[w_l] == 0:
                    distinct -= 1
                left += 1
            if distinct >= required:
                ok = True
                break

    if not ok:
        return False, []

    spans = sorted(
        {(tokens[i].start, tokens[i].end) for idxs in matches_per_word for i in idxs}
    )
    return True, spans


def context_key(full_text: str, first_span: Tuple[int, int], words: int = 50) -> str:
    """מפתח הקשר לאיחוד כפילויות: hash של 50 מילים מנורמלות לפני ואחרי ההתאמה.

    תוצאה זהה בכמה ספרים (אותו הקשר) תקבל אותו מפתח ותאוחד בתצוגה.
    """
    import hashlib

    tokens = hebrew.tokenize(full_text)
    if not tokens:
        return ""
    # איתור הטוקן הראשון של ההתאמה
    idx = 0
    for i, t in enumerate(tokens):
        if t.start >= first_span[0]:
            idx = i
            break
    lo = max(0, idx - words)
    hi = min(len(tokens), idx + words)
    ctx = " ".join(t.norm for t in tokens[lo:hi])
    return hashlib.sha1(ctx.encode("utf-8")).hexdigest()
