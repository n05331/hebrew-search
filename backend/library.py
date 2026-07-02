"""מודול הספרייה: עץ ספרים, מוסכמות @, תוכן ספרים, כותרות וחיפוש-בספר.

מוסכמות התיקיות (לפי דרישת הלקוח):
- תיקייה בשם "שם הספר@" המכילה קובץ טקסט + קובץ PDF - מוצגת בעץ כספר יחיד
  דו-פורמטי (נפתח לפי ברירת המחדל בהגדרות, עם מעבר תצוגה).
- תיקייה בשם "שם הספר@מפרשים" - אוסף מפרשים של הספר באותה רמה; לא מוצגת
  כתיקייה, אלא נחשפת דרך כפתור "מפרשים" בספר עצמו.
- קידומת מספר בשם תיקייה/קובץ ("1_רבינו הקדוש", "02_ספר המידות") קובעת את
  סדר התצוגה אך אינה מוצגת.

כל תוכן הספרים מוגש כ"טקסט תצוגה" (ראו ``toc.py``): קודי הכותרות של
תורת-אמת/אוצריא מוסרים, וכל ההיסטים (קטעים, חיפוש, כותרות) עקביים.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import hebrew, matching, toc
from .catalog import catalog
from .config import settings
from .logging_setup import get_logger

log = get_logger("library")

# גודל קטע (תווים) לדפדוף בספרי טקסט גדולים; נחתך בגבול פסקה
_CHUNK_SIZE = 12000

_MEFARSHIM_SUFFIX = "@מפרשים"

_SKIP_DIRS = {"node_modules", "$recycle.bin", "system volume information"}

# קידומת סדר: ספרות ואחריהן מפריד (מקף/קו תחתון/נקודה/רווח)
_ORDER_PREFIX_RE = re.compile(r"^\s*(\d+)\s*[-_.\s]\s*")


def order_key_and_display(name: str) -> Tuple[int, str]:
    """מחזיר (מספר סדר, שם לתצוגה ללא הקידומת). ללא קידומת - סדר גדול."""
    m = _ORDER_PREFIX_RE.match(name)
    if m:
        display = name[m.end():].strip()
        if display:
            return int(m.group(1)), display
    return 10**9, name.strip()


def _entry_type(ext: str) -> str:
    if ext in settings.pdf_extensions:
        return "pdf"
    if ext in settings.image_extensions:
        return "image"
    return "text"


def _book_files_in(folder: Path) -> Dict[str, str]:
    """מאתר קובצי טקסט/PDF בתיקיית ספר @. מחזיר {'text': path, 'pdf': path}."""
    found: Dict[str, str] = {}
    try:
        for f in sorted(folder.iterdir(), key=lambda f: order_key_and_display(f.name)):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in settings.pdf_extensions and "pdf" not in found:
                found["pdf"] = str(f)
            elif ext in settings.text_extensions and "text" not in found:
                found["text"] = str(f)
            elif ext in settings.docx_extensions and "text" not in found:
                found["text"] = str(f)
    except OSError:
        pass
    return found


def build_tree() -> List[dict]:
    """בונה את עץ הספרים מכל תיקיות המקור."""
    roots = catalog.list_roots()
    out: List[dict] = []
    for r in roots:
        p = Path(r)
        if not p.exists():
            continue
        node = _build_dir_node(p)
        if node:
            out.append(node)
    return out


def _build_dir_node(folder: Path) -> Optional[dict]:
    children: List[dict] = []
    mefarshim_map: Dict[str, str] = {}  # שם ספר (גולמי, ללא קידומת) -> נתיב תיקיית מפרשים

    try:
        entries = sorted(
            folder.iterdir(),
            key=lambda e: (e.is_file(), order_key_and_display(e.stem if e.is_file() else e.name)),
        )
    except OSError:
        return None

    # מעבר ראשון: איתור תיקיות מפרשים
    for e in entries:
        if e.is_dir() and e.name.endswith(_MEFARSHIM_SUFFIX):
            base = e.name[: -len(_MEFARSHIM_SUFFIX)].strip()
            mefarshim_map[base] = str(e)
            _, disp = order_key_and_display(base)
            mefarshim_map.setdefault(disp, str(e))

    for e in entries:
        name = e.name
        if e.is_dir():
            if name.startswith(".") or name.lower() in _SKIP_DIRS:
                continue
            if name.endswith(_MEFARSHIM_SUFFIX):
                continue  # נחשף דרך הספר עצמו
            if "@" in name:
                # ספר דו-פורמטי: "שם הספר@"
                base = name.split("@")[0].strip()
                _, display = order_key_and_display(base)
                files = _book_files_in(e)
                if files:
                    children.append(
                        {
                            "kind": "book",
                            "name": display,
                            "dual": len(files) > 1,
                            "text_path": files.get("text"),
                            "pdf_path": files.get("pdf"),
                            "mefarshim": mefarshim_map.get(base) or mefarshim_map.get(display),
                        }
                    )
                continue
            sub = _build_dir_node(e)
            if sub and (sub["children"]):
                children.append(sub)
        elif e.is_file():
            ext = e.suffix.lower()
            if ext not in settings.supported_extensions:
                continue
            base = e.stem
            _, display = order_key_and_display(base)
            entry = {
                "kind": "book",
                "name": display,
                "dual": False,
                "type": _entry_type(ext),
                "mefarshim": mefarshim_map.get(base) or mefarshim_map.get(display),
            }
            if _entry_type(ext) == "pdf":
                entry["pdf_path"] = str(e)
            elif _entry_type(ext) == "image":
                entry["image_path"] = str(e)
                entry["kind"] = "image"
            else:
                entry["text_path"] = str(e)
            children.append(entry)

    _, folder_display = order_key_and_display(folder.name)
    return {"kind": "folder", "name": folder_display, "path": str(folder), "children": children}


def list_mefarshim(folder: str) -> List[dict]:
    """רשימת ספרי המפרשים בתיקיית מפרשים (כולל תיקיות @ פנימיות)."""
    p = Path(folder)
    if not p.exists() or not p.is_dir():
        return []
    out = []
    try:
        entries = sorted(p.iterdir(), key=lambda e: order_key_and_display(e.stem if e.is_file() else e.name))
    except OSError:
        return []
    for e in entries:
        if e.is_file() and e.suffix.lower() in settings.supported_extensions:
            t = _entry_type(e.suffix.lower())
            _, display = order_key_and_display(e.stem)
            out.append({"name": display, "path": str(e), "type": t})
        elif e.is_dir() and "@" in e.name and not e.name.endswith(_MEFARSHIM_SUFFIX):
            files = _book_files_in(e)
            path = files.get("text") or files.get("pdf")
            if path:
                base = e.name.split("@")[0].strip()
                _, display = order_key_and_display(base)
                out.append({"name": display, "path": path, "type": _entry_type(Path(path).suffix.lower())})
    return out


# ---- תוכן ספר טקסטואלי ----

def _read_book_text(path: Path) -> str:
    """קורא טקסט גולמי מקובץ ספר (txt/docx). ל-PDF יש תצוגה נפרדת."""
    ext = path.suffix.lower()
    if ext in settings.docx_extensions:
        from .extractors import docx_extractor

        res = docx_extractor.extract(path)
        return "\n".join(p.text for p in res.pages)
    from .extractors import txt_extractor

    return txt_extractor._read_text(path)


def _get_display(path: Path) -> Tuple[str, List[dict]]:
    """(display_text, headings) עם cache."""
    return toc.get_parsed(path, _read_book_text)


def _chunk_boundaries(text: str) -> List[int]:
    """גבולות קטעים: כל ~CHUNK_SIZE תווים, נחתך בגבול פסקה (שורה ריקה) או שורה."""
    bounds = [0]
    n = len(text)
    pos = 0
    while pos < n:
        nxt = min(n, pos + _CHUNK_SIZE)
        if nxt < n:
            # חיפוש גבול פסקה אחורה
            para = text.rfind("\n\n", pos + _CHUNK_SIZE // 2, nxt)
            if para == -1:
                para = text.rfind("\n", pos + _CHUNK_SIZE // 2, nxt)
            if para != -1:
                nxt = para + 1
        bounds.append(nxt)
        pos = nxt
    return bounds


def _chunk_of(bounds: List[int], offset: int) -> int:
    total = max(1, len(bounds) - 1)
    i = bisect_right(bounds, offset) - 1
    return min(max(0, i), total - 1)


def get_book_chunk(path: str, chunk: int = 0) -> Optional[dict]:
    """מחזיר קטע מספר טקסטואלי + כותרות בתוכו + מטא-דאטה לדפדוף."""
    p = Path(path)
    if not p.exists():
        return None
    text, headings = _get_display(p)
    bounds = _chunk_boundaries(text)
    total_chunks = max(1, len(bounds) - 1)
    chunk = max(0, min(chunk, total_chunks - 1))
    start, end = bounds[chunk], bounds[chunk + 1]

    chunk_headings = [
        {
            "level": h["level"],
            "title": h["title"],
            "start": h["start"] - start,
            "end": h["end"] - start,
        }
        for h in headings
        if start <= h["start"] < end
    ]

    has_niqqud = bool(re.search(r"[\u05B0-\u05C7]", text[start:end]))
    has_teamim = bool(re.search(r"[\u0591-\u05AF]", text[start:end]))

    return {
        "path": path,
        "name": order_key_and_display(p.stem)[1],
        "chunk": chunk,
        "total_chunks": total_chunks,
        "chunk_start": start,
        "text": text[start:end],
        "headings": chunk_headings,
        "has_niqqud": has_niqqud,
        "has_teamim": has_teamim,
        "percent": round(chunk / total_chunks * 100, 1),
    }


def get_book_toc(path: str) -> Optional[dict]:
    """עץ הכותרות של ספר טקסטואלי, עם מיקום (קטע+היסט) לכל כותרת."""
    p = Path(path)
    if not p.exists():
        return None
    text, headings = _get_display(p)
    bounds = _chunk_boundaries(text)
    out = [
        {
            "level": h["level"],
            "title": h["title"],
            "abs_offset": h["start"],
            "chunk": _chunk_of(bounds, h["start"]),
            "offset": h["start"] - bounds[_chunk_of(bounds, h["start"])],
        }
        for h in headings
    ]
    return {"path": path, "headings": out, "total_chunks": max(1, len(bounds) - 1)}


def _snippet_around(text: str, start: int, end: int, chars: int = 90) -> Tuple[str, int, int]:
    """קטע הקשר סביב התאמה. מחזיר (snippet, hl_start, hl_end) יחסית ל-snippet."""
    lo = max(0, start - chars)
    hi = min(len(text), end + chars)
    # יישור לגבולות מילים
    if lo > 0:
        sp = text.find(" ", lo, start)
        if sp != -1:
            lo = sp + 1
    if hi < len(text):
        sp = text.rfind(" ", end, hi)
        if sp != -1:
            hi = sp
    snippet = text[lo:hi].replace("\n", " ")
    return snippet, start - lo, end - lo


def search_in_book(
    path: str,
    query: str,
    opts: Optional[matching.MatchOptions] = None,
    max_hits: int = 500,
) -> Optional[dict]:
    """חיפוש בתוך ספר - בכל סוגי הקבצים, עם כל אפשרויות ההתאמה.

    ספר טקסט: חיפוש על טקסט התצוגה, תוצאות עם (chunk, start, end, snippet).
    PDF/תמונה: חיפוש על הטקסט המחולץ/OCR מהקטלוג, תוצאות עם (page, snippet).
    """
    p = Path(path)
    if not p.exists():
        return None
    opts = opts or matching.MatchOptions(proximity=0)

    ext = p.suffix.lower()
    if ext in settings.pdf_extensions or ext in settings.image_extensions:
        return _search_in_pdf(p, query, opts, max_hits)

    text, _ = _get_display(p)
    ok, spans = matching.analyze(text, query, opts)
    if not ok:
        return {"kind": "text", "query": query, "total": 0, "hits": [], "total_chunks": 1}

    bounds = _chunk_boundaries(text)
    total_chunks = max(1, len(bounds) - 1)

    hits = []
    for s, e in spans[:max_hits]:
        c = _chunk_of(bounds, s)
        snippet, hs, he = _snippet_around(text, s, e)
        hits.append(
            {
                "chunk": c,
                "start": s - bounds[c],
                "end": e - bounds[c],
                "abs_start": s,
                "snippet": snippet,
                "hl": [hs, he],
            }
        )
    return {
        "kind": "text",
        "query": query,
        "total": len(spans),
        "hits": hits,
        "total_chunks": total_chunks,
    }


def _search_in_pdf(p: Path, query: str, opts: matching.MatchOptions, max_hits: int) -> dict:
    row = catalog.get_file_by_path(str(p))
    if row is None or not (row["full_text"] or "").strip():
        pending = row is not None and row["status"] == "pending_ocr"
        return {
            "kind": "pdf",
            "query": query,
            "total": 0,
            "hits": [],
            "pending": pending,
            "message": "הטקסט של הקובץ עדיין בהכנה (OCR ברקע)" if pending else "אין טקסט מחולץ לקובץ זה",
        }

    full_text = row["full_text"]
    ok, spans = matching.analyze(full_text, query, opts)
    if not ok:
        return {"kind": "pdf", "query": query, "total": 0, "hits": []}

    segs = catalog.get_segments(row["id"])
    seg_starts = [s["char_start"] for s in segs]
    hits = []
    for s, e in spans[:max_hits]:
        i = max(0, bisect_right(seg_starts, s) - 1)
        page = segs[i]["page"] if segs else None
        snippet, hs, he = _snippet_around(full_text, s, e)
        hits.append({"page": page, "snippet": snippet, "hl": [hs, he]})
    return {"kind": "pdf", "query": query, "total": len(spans), "hits": hits}


# ---- סנכרון מיקום טקסט <-> PDF לפי כותרות ----

# cache טוקניזציה של טקסט PDF: path -> (mtime, norms, starts, positions_by_first)
_PDF_TOKENS_CACHE: Dict[str, tuple] = {}


def _pdf_tokens(p: Path, full_text: str):
    key = str(p)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    hit = _PDF_TOKENS_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1], hit[2], hit[3]

    tokens = hebrew.tokenize(full_text)
    norms = [t.norm for t in tokens]
    starts = [t.start for t in tokens]
    positions: Dict[str, List[int]] = {}
    for i, n in enumerate(norms):
        positions.setdefault(n, []).append(i)

    if len(_PDF_TOKENS_CACHE) >= 4:
        _PDF_TOKENS_CACHE.pop(next(iter(_PDF_TOKENS_CACHE)))
    _PDF_TOKENS_CACHE[key] = (mtime, norms, starts, positions)
    return norms, starts, positions


def _find_phrase_first(norms: List[str], positions: Dict[str, List[int]], terms: List[str]) -> Optional[int]:
    """אינדקס הטוקן של ההופעה הראשונה של רצף terms, או None."""
    if not terms:
        return None
    for i in positions.get(terms[0], []):
        if norms[i : i + len(terms)] == terms:
            return i
    return None


def sync_position(
    text_path: str,
    pdf_path: str,
    direction: str,
    offset: Optional[int] = None,
    page: Optional[int] = None,
) -> dict:
    """ממפה מיקום בין תצוגת טקסט לתצוגת PDF לפי כותרות הספר.

    direction="to_pdf": offset (בטקסט התצוגה) -> עמוד PDF.
    direction="to_text": page -> (chunk, offset) בטקסט התצוגה.
    נפילה: מיפוי לפי אחוז התקדמות.
    """
    tp, pp = Path(text_path), Path(pdf_path)
    if not tp.exists() or not pp.exists():
        return {"ok": False}

    text, headings = _get_display(tp)
    bounds = _chunk_boundaries(text)
    total_chunks = max(1, len(bounds) - 1)

    row = catalog.get_file_by_path(str(pp))
    pdf_text = (row["full_text"] or "") if row else ""
    pdf_pages = (row["page_count"] or 0) if row else 0

    if direction == "to_pdf":
        offset = offset or 0
        if row and pdf_text and headings:
            norms, starts, positions = _pdf_tokens(pp, pdf_text)
            # הכותרת האחרונה שלפני המיקום הנוכחי, מהקרובה לרחוקה
            before = [h for h in headings if h["start"] <= offset]
            for h in reversed(before):
                terms = hebrew.query_terms(h["title"])
                if not terms:
                    continue
                idx = _find_phrase_first(norms, positions, terms)
                if idx is not None:
                    pg = catalog.page_for_offset(row["id"], starts[idx])
                    if pg:
                        return {"ok": True, "page": pg, "matched": h["title"]}
        # נפילה לאחוז
        pct = offset / max(1, len(text))
        return {"ok": True, "page": max(1, round(pct * max(1, pdf_pages))), "matched": None}

    # to_text
    page = page or 1
    if row and pdf_text and headings:
        segs = catalog.get_segments(row["id"])
        page_end = None
        for s in segs:
            if s["page"] == page:
                page_end = s["char_end"]
        if page_end is not None:
            norms, starts, positions = _pdf_tokens(pp, pdf_text)
            best = None
            for h in headings:
                terms = hebrew.query_terms(h["title"])
                if not terms:
                    continue
                idx = _find_phrase_first(norms, positions, terms)
                if idx is not None and starts[idx] <= page_end:
                    if best is None or starts[idx] > best[0]:
                        best = (starts[idx], h)
            if best is not None:
                h = best[1]
                c = _chunk_of(bounds, h["start"])
                return {
                    "ok": True,
                    "chunk": c,
                    "offset": h["start"] - bounds[c],
                    "abs_offset": h["start"],
                    "matched": h["title"],
                }
    pct = (page - 1) / max(1, pdf_pages or 1)
    target = min(total_chunks - 1, round(pct * total_chunks))
    return {"ok": True, "chunk": target, "offset": 0, "abs_offset": bounds[target], "matched": None}
