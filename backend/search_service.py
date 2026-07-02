"""שירות חיפוש: מאחד תוצאות מנוע Tantivy עם הקטלוג ובונה תגובה עשירה.

אחראי על: הפעלת המנוע עם אפשרויות ההתאמה (מדויק/מילה שלימה/כתיב מלא-חסר/
אידיש/קרבה/מינימום מילים), סינון לפי היקף ספרים וסוגי קבצים, איחוד תוצאות
כפולות (אותו הקשר בכמה ספרים), ובניית קטעי הקשר מודגשים.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from . import hebrew, highlight, matching
from .catalog import Catalog, catalog
from .logging_setup import get_logger
from .search_engine import SearchEngine, engine

log = get_logger("search_service")

# סטטוס חיפוש חי - לחיווי התקדמות ב-UI (נבדקו X מתוך Y, זמן משוער)
search_status: Dict = {"running": False, "candidates": 0, "checked": 0, "started_at": 0.0}


def _matches_filters(row, exts, folder, path_set, prefix_list) -> bool:
    if exts and (row["ext"] or "").lower() not in exts:
        return False
    if folder and not str(row["path"]).lower().startswith(folder.lower()):
        return False
    if path_set is not None:
        p = str(row["path"]).lower()
        if p not in path_set and not any(p.startswith(pref) for pref in prefix_list):
            return False
    return True


def search(
    query: str,
    limit: int = 30,
    offset: int = 0,
    opts: Optional[matching.MatchOptions] = None,
    exts: Optional[List[str]] = None,
    folder: Optional[str] = None,
    paths: Optional[List[str]] = None,
    cat: Catalog = catalog,
    eng: SearchEngine = engine,
) -> dict:
    query = (query or "").strip()
    if not query:
        return {"query": query, "total": 0, "results": []}

    opts = opts or matching.MatchOptions()

    ext_set = {"." + e.lower().lstrip(".") for e in exts} if exts else None

    # היקף ספרים: קבצים ספציפיים + תיקיות (prefix)
    path_set = None
    prefix_list: List[str] = []
    if paths:
        path_set = set()
        for p in paths:
            pl = str(p).lower()
            path_set.add(pl)
            prefix_list.append(pl.rstrip("\\/") + "\\")

    # מושכים מועמדים ברוחב - האכיפה המדויקת נעשית על הטקסט המלא
    raw_limit = min(max((limit + offset) * 5, 200), 3000)
    hits, _ = eng.search(query, limit=raw_limit, offset=0, opts=opts)

    window_words = get_setting_int("snippet_words", 50, cat)

    search_status.update(
        {"running": True, "candidates": len(hits), "checked": 0, "started_at": time.time()}
    )

    # שלב 1: סינון + אימות התאמה + איסוף טווחים + מפתח כפילות
    matched: List[dict] = []
    seen_ctx: Dict[str, dict] = {}
    for file_id, score in hits:
        search_status["checked"] += 1
        row = cat.get_file(file_id)
        if row is None:
            continue
        if not _matches_filters(row, ext_set, folder, path_set, prefix_list):
            continue
        full_text = row["full_text"] or ""
        ok, spans = matching.analyze(full_text, query, opts)
        if not ok or not spans:
            continue

        ctx_key = matching.context_key(full_text, spans[0], words=50)
        entry = {
            "file_id": file_id,
            "score": score,
            "row": row,
            "spans": spans,
            "full_text": full_text,
        }
        if ctx_key and ctx_key in seen_ctx:
            seen_ctx[ctx_key]["duplicates"].append(
                {"file_id": file_id, "name": row["name"], "path": row["path"], "ext": row["ext"]}
            )
            continue
        entry["duplicates"] = []
        if ctx_key:
            seen_ctx[ctx_key] = entry
        matched.append(entry)

    # שלב 2: בניית קטעים רק עבור העמוד המבוקש
    page_rows = matched[offset : offset + limit]
    results = []
    for entry in page_rows:
        row = entry["row"]
        file_id = entry["file_id"]
        segs = [(s["page"], s["char_start"], s["char_end"]) for s in cat.get_segments(file_id)]
        matches, occ = highlight.build_matches_from_spans(
            entry["full_text"], segs, entry["spans"], window_words=window_words, max_matches=6
        )
        results.append(
            {
                "file_id": file_id,
                "path": row["path"],
                "name": row["name"],
                "ext": row["ext"],
                "size": row["size"],
                "mtime": row["mtime"],
                "page_count": row["page_count"],
                "source": row["source"],
                "score": round(entry["score"], 4),
                "occurrences": occ,
                "duplicates": entry["duplicates"],
                "matches": [
                    {
                        "snippet": m.snippet,
                        "spans": [[s.start, s.end] for s in m.spans],
                        "abs_offset": m.abs_offset,
                        "page": m.page,
                    }
                    for m in matches
                ],
            }
        )

    search_status["running"] = False
    return {"query": query, "total": len(matched), "results": results}


def get_setting_int(key: str, default: int, cat: Catalog = catalog) -> int:
    try:
        v = cat.get_setting(key)
        return int(v) if v is not None else default
    except Exception:
        return default


def get_document_text(
    file_id: int,
    query: Optional[str] = None,
    opts: Optional[matching.MatchOptions] = None,
    cat: Catalog = catalog,
) -> Optional[dict]:
    row = cat.get_file(file_id)
    if row is None:
        return None

    full_text = row["full_text"] or ""
    spans: List[List[int]] = []
    if query:
        ok, sp = matching.analyze(full_text, query, opts or matching.MatchOptions())
        if ok:
            spans = [[s, e] for s, e in sp]

    pages = [
        {"page": s["page"], "start": s["char_start"], "end": s["char_end"]}
        for s in cat.get_segments(file_id)
    ]

    return {
        "file_id": file_id,
        "path": row["path"],
        "name": row["name"],
        "full_text": full_text,
        "page_count": row["page_count"],
        "source": row["source"],
        "spans": spans,
        "pages": pages,
    }
