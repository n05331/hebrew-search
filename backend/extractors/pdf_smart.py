"""חילוץ טקסט חכם מ-PDF: זיהוי טורים (RTL - הימני ראשון) ואיחוי פסקאות.

עובד ברמת מילים עם pdfplumber:
1. קיבוץ מילים לשורות לפי Y.
2. זיהוי טורים לפי פער X רחב ועקבי בין מקבצי מילים (הטור הימני ראשון).
3. איחוי שורות לפסקאות: שורה מצטרפת לקודמת אלא אם יש רווח אנכי גדול,
   הקודמת מסתיימת בפיסוק סופי, או שהיא קצרה משמעותית (כותרת/סוף פסקה).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ..logging_setup import get_logger

log = get_logger("extract.pdf_smart")

_END_PUNCT = (".", ":", "!", "?", ";", '"', "'", ")", "]")


def _cluster_lines(words: List[dict], y_tol: float = 3.0) -> List[List[dict]]:
    """מקבץ מילים לשורות לפי top (בסבילות)."""
    lines: List[List[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], -w["x1"])):
        placed = False
        for line in lines:
            if abs(line[0]["top"] - w["top"]) <= y_tol:
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: -w["x1"])  # RTL: מימין לשמאל
    lines.sort(key=lambda l: l[0]["top"])
    return lines


def _detect_columns(lines: List[List[dict]], page_width: float) -> List[tuple]:
    """מזהה גבולות טורים לפי 'תעלה' אנכית ריקה ועקבית. מחזיר [(x0,x1)] מימין לשמאל."""
    if not lines:
        return [(0, page_width)]

    # היסטוגרמת כיסוי X
    buckets = 200
    cover = [0] * buckets
    for line in lines:
        for w in line:
            b0 = int(w["x0"] / page_width * (buckets - 1))
            b1 = int(w["x1"] / page_width * (buckets - 1))
            for b in range(max(0, b0), min(buckets, b1 + 1)):
                cover[b] += 1

    total_lines = len(lines)
    # תעלה = רצף דליים באמצע העמוד עם כיסוי נמוך מאוד
    gaps = []
    in_gap = False
    gap_start = 0
    for i in range(buckets):
        low = cover[i] <= max(1, total_lines * 0.05)
        if low and not in_gap:
            in_gap = True
            gap_start = i
        elif not low and in_gap:
            in_gap = False
            frac0, frac1 = gap_start / buckets, i / buckets
            # תעלה רלוונטית: באמצע העמוד ורחבה מספיק
            if 0.2 < (frac0 + frac1) / 2 < 0.8 and (frac1 - frac0) >= 0.025:
                gaps.append((frac0 * page_width, frac1 * page_width))

    if not gaps:
        return [(0, page_width)]

    # בניית טורים מהגבולות, ממוינים מימין לשמאל
    edges = [0.0] + [g for gap in gaps for g in gap] + [page_width]
    cols = []
    for i in range(0, len(edges) - 1, 2):
        cols.append((edges[i], edges[i + 1]))
    cols.sort(key=lambda c: -c[1])  # הימני ראשון
    return cols


def _lines_to_paragraphs(lines: List[List[dict]]) -> List[str]:
    """מאחה שורות לפסקאות עם שימור כותרות."""
    if not lines:
        return []

    # טקסט ומדדים לכל שורה
    rendered = []
    for line in lines:
        text = " ".join(w["text"] for w in line)
        top = line[0]["top"]
        bottom = max(w["bottom"] for w in line)
        width = (max(w["x1"] for w in line) - min(w["x0"] for w in line))
        rendered.append({"text": text.strip(), "top": top, "bottom": bottom, "width": width})

    avg_width = sum(r["width"] for r in rendered) / len(rendered)
    heights = [r["bottom"] - r["top"] for r in rendered]
    avg_h = sum(heights) / len(heights)

    paragraphs: List[str] = []
    current: List[str] = []

    for i, r in enumerate(rendered):
        if not r["text"]:
            continue
        new_para = False
        if not current:
            new_para = False
        else:
            prev = rendered[i - 1]
            v_gap = r["top"] - prev["bottom"]
            if v_gap > avg_h * 0.9:
                new_para = True  # רווח אנכי גדול
            elif prev["text"].endswith(_END_PUNCT) and prev["width"] < avg_width * 0.75:
                new_para = True  # שורה קצרה שמסתיימת בפיסוק - סוף פסקה
            elif prev["width"] < avg_width * 0.45:
                new_para = True  # שורה קצרה מאוד (כותרת)

        if new_para and current:
            paragraphs.append(" ".join(current))
            current = []
        current.append(r["text"])

    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def extract_page_text(page) -> str:
    """חילוץ חכם של עמוד pdfplumber בודד: טורים RTL (הימני ראשון) + פסקאות.

    מחזיר "" אם אין מילים בעמוד. עשוי לזרוק - האחריות על המפעיל ליפול
    לחילוץ הרגיל.
    """
    words = page.extract_words(use_text_flow=False) or []
    if not words:
        return ""

    lines = _cluster_lines(words)
    cols = _detect_columns(lines, page.width or 600)

    page_parts: List[str] = []
    for cx0, cx1 in cols:
        col_lines = []
        for line in lines:
            col_words = [w for w in line if cx0 <= (w["x0"] + w["x1"]) / 2 <= cx1]
            if col_words:
                col_lines.append(col_words)
        paras = _lines_to_paragraphs(col_lines)
        if paras:
            page_parts.append("\n\n".join(paras))
    return "\n\n".join(page_parts)


def extract_smart(path: Path) -> str:
    """חילוץ חכם של כל ה-PDF. מחזיר טקסט עם פסקאות אמיתיות, טור ימני ראשון."""
    import pdfplumber

    out_pages: List[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            try:
                text = extract_page_text(page)
            except Exception as exc:
                log.debug("חילוץ חכם נכשל בעמוד: %s", exc)
                text = ""
            if text:
                out_pages.append(text)

    return "\n\n".join(out_pages)
