"""בניית קטעי הקשר עם הדגשה על הטקסט המקורי.

עובד על רשימת טווחי הופעות (start, end) בטקסט המלא - כך שאותו קוד משרת
גם חיפוש מילים רגיל וגם ביטוי מדויק (שם הטווח הוא הביטוי השלם).
חלון ההקשר נמדד במילים (ברירת מחדל מההגדרות, ניתנת לשינוי).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass
class Span:
    start: int  # יחסי לתחילת הקטע
    end: int


@dataclass
class Match:
    snippet: str
    spans: List[Span]
    abs_offset: int          # היסט מוחלט בטקסט המלא (של ההופעה הראשונה בקטע)
    page: Optional[int]


_WS_RE = re.compile(r"\S+")


def _page_for_offset(segments: Sequence[Tuple[Optional[int], int, int]], offset: int) -> Optional[int]:
    for page, start, end in segments:
        if start <= offset < end:
            return page
    return segments[-1][0] if segments else None


def _expand_by_words(text: str, start: int, end: int, words: int) -> Tuple[int, int]:
    """מרחיב טווח בכ-N מילים לכל כיוון (לפי רצפי לא-רווח)."""
    # אחורה
    count = 0
    pos = start
    while pos > 0 and count < words:
        pos -= 1
        # דילוג על רווחים ואז על מילה
        while pos > 0 and text[pos].isspace():
            pos -= 1
        while pos > 0 and not text[pos - 1].isspace():
            pos -= 1
        count += 1
    ctx_start = pos

    # קדימה
    count = 0
    pos = end
    n = len(text)
    while pos < n and count < words:
        while pos < n and text[pos].isspace():
            pos += 1
        while pos < n and not text[pos].isspace():
            pos += 1
        count += 1
    ctx_end = pos

    return ctx_start, ctx_end


def build_matches_from_spans(
    full_text: str,
    segments: Sequence[Tuple[Optional[int], int, int]],
    occurrence_spans: Sequence[Tuple[int, int]],
    window_words: int = 50,
    max_matches: int = 8,
) -> Tuple[List[Match], int]:
    """בונה קטעים מודגשים מתוך טווחי הופעות. מחזיר (קטעים, סה"כ הופעות)."""
    if not full_text or not occurrence_spans:
        return [], 0

    spans_sorted = sorted(occurrence_spans, key=lambda s: s[0])
    total = len(spans_sorted)

    matches: List[Match] = []
    used_until = -1

    for occ_start, occ_end in spans_sorted:
        if len(matches) >= max_matches:
            break
        if occ_start < used_until:
            continue  # ההופעה כבר מכוסה בקטע קודם (הודגשה שם)

        ctx_start, ctx_end = _expand_by_words(full_text, occ_start, occ_end, window_words)

        snippet_text = full_text[ctx_start:ctx_end]
        prefix = "…" if ctx_start > 0 else ""
        suffix = "…" if ctx_end < len(full_text) else ""

        rel_spans = []
        for s, e in spans_sorted:
            if ctx_start <= s and e <= ctx_end:
                rel_spans.append(Span(start=len(prefix) + (s - ctx_start), end=len(prefix) + (e - ctx_start)))

        matches.append(
            Match(
                snippet=prefix + snippet_text + suffix,
                spans=_dedup_spans(rel_spans),
                abs_offset=occ_start,
                page=_page_for_offset(segments, occ_start),
            )
        )
        used_until = ctx_end

    return matches, total


def _dedup_spans(spans: List[Span]) -> List[Span]:
    seen = set()
    out = []
    for s in sorted(spans, key=lambda x: x.start):
        key = (s.start, s.end)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
