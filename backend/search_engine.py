"""מנוע חיפוש מעל Tantivy.

עקרון הליבה לעברית: אנו מזינים ל-Tantivy טקסט *מנורמל* (ניקוד/סופיות/תחיליות
מטופלים ב-``hebrew.py``) בשני שדות:
- ``content``      - צורה מנורמלת מדויקת (דיוק גבוה, תומך בביטויים).
- ``content_stem`` - צורה לאחר הסרת תחיליות (מרחיב recall).
השאילתה עוברת אותו נירמול, כך שהתנהגות ההתאמה עקבית לחלוטין.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from threading import Lock
from typing import List, Optional, Tuple

import tantivy

from . import hebrew, matching
from .config import settings
from .logging_setup import get_logger

log = get_logger("search_engine")

# גרסת סכמת האינדקס; שינוי סכמה מחייב בנייה מחדש (מהקטלוג, ללא OCR מחדש)
INDEX_SCHEMA_VERSION = "2"


def _build_schema() -> tantivy.Schema:
    sb = tantivy.SchemaBuilder()
    sb.add_integer_field("file_id", stored=True, indexed=True, fast=True)
    sb.add_text_field("path", stored=True, tokenizer_name="raw")
    sb.add_text_field("name", stored=True, tokenizer_name="default")
    sb.add_text_field("content", stored=False, tokenizer_name="default")
    sb.add_text_field("content_stem", stored=False, tokenizer_name="default")
    # שדה מקופל (ללא ו/י/ע/א) לאיתור מועמדים בכתיב מלא/חסר ובאידיש
    sb.add_text_field("content_fold", stored=False, tokenizer_name="default")
    sb.add_text_field("ext", stored=True, tokenizer_name="raw")
    sb.add_integer_field("mtime", stored=True, indexed=True, fast=True)
    return sb.build()


_PHRASE_RE = re.compile(r'"([^"]+)"')


class SearchEngine:
    def __init__(self, index_dir: Optional[Path] = None) -> None:
        self.index_dir = index_dir or settings.index_dir
        self._lock = Lock()
        self.schema: Optional[tantivy.Schema] = None
        self.index: Optional[tantivy.Index] = None
        self._writer = None

    def open(self) -> None:
        settings.ensure_dirs()
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.schema = _build_schema()
        try:
            self.index = tantivy.Index(self.schema, path=str(self.index_dir))
        except Exception as exc:
            # סכמה ישנה/אינדקס פגום - מוחקים ובונים מחדש (התוכן ייבנה מהקטלוג)
            log.warning("פתיחת אינדקס נכשלה (%s) - בונה אינדקס חדש", exc)
            self.wipe()
            self.index = tantivy.Index(self.schema, path=str(self.index_dir))
        log.info("אינדקס Tantivy נפתח: %s", self.index_dir)

    def wipe(self) -> None:
        """מוחק את קבצי האינדקס (למעבר גרסת סכמה)."""
        with self._lock:
            self._writer = None
            self.index = None
        try:
            shutil.rmtree(self.index_dir, ignore_errors=True)
        except Exception:
            pass
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def _get_writer(self):
        if self._writer is None:
            self._writer = self.index.writer()
        return self._writer

    # ---- כתיבה ----
    def add_document(
        self,
        file_id: int,
        path: str,
        name: str,
        ext: str,
        mtime: int,
        content: str,
    ) -> None:
        assert self.index is not None
        with self._lock:
            writer = self._get_writer()
            # מוחקים גרסה קודמת של אותו קובץ לפני הוספה
            writer.delete_documents("file_id", file_id)
            tokens = hebrew.tokenize(content)
            norm_stream = " ".join(t.norm for t in tokens)
            stem_stream = " ".join(t.stem for t in tokens)
            # שדה מקופל: גם צורות מנורמלות וגם בסיסים, מקופלים (ו/י/ע/א)
            fold_stream = " ".join(
                matching.full_fold(t.norm) for t in tokens
            ) + " " + " ".join(matching.full_fold(t.stem) for t in tokens)

            doc = tantivy.Document()
            doc.add_integer("file_id", file_id)
            doc.add_text("path", path)
            doc.add_text("name", name)
            doc.add_text("content", norm_stream)
            doc.add_text("content_stem", stem_stream)
            doc.add_text("content_fold", fold_stream)
            doc.add_text("ext", ext)
            doc.add_integer("mtime", mtime)
            writer.add_document(doc)

    def delete_document(self, file_id: int) -> None:
        assert self.index is not None
        with self._lock:
            writer = self._get_writer()
            writer.delete_documents("file_id", file_id)

    def commit(self) -> None:
        with self._lock:
            if self._writer is not None:
                self._writer.commit()
        if self.index is not None:
            self.index.reload()

    # ---- חיפוש ----
    def _build_query(
        self, raw_query: str, opts: Optional["matching.MatchOptions"] = None
    ) -> Optional[tantivy.Query]:
        """בונה שאילתת מועמדים לפי אפשרויות ההתאמה.

        האכיפה המדויקת (רצף/קרבה/קיפול) נעשית ב-search_service על הטקסט המלא;
        כאן רק מאתרים מועמדים ברוחב מספק.
        """
        assert self.schema is not None
        opts = opts or matching.MatchOptions()
        raw_query = raw_query.strip()
        if not raw_query:
            return None

        phrases = _PHRASE_RE.findall(raw_query)
        remainder = _PHRASE_RE.sub(" ", raw_query)
        terms: List[str] = []
        for phrase in phrases:
            terms += hebrew.query_terms(phrase)
        terms += hebrew.query_terms(remainder)
        if not terms:
            return None

        total = len(terms)
        required = opts.min_words if 0 < opts.min_words < total else total
        occur = tantivy.Occur.Must if required >= total else tantivy.Occur.Should
        subs: List[Tuple[tantivy.Occur, tantivy.Query]] = [
            (occur, self._term_or(term, opts)) for term in terms
        ]
        if occur == tantivy.Occur.Should:
            return tantivy.Query.boolean_query(subs, minimum_number_should_match=required)
        return tantivy.Query.boolean_query(subs)

    def _term_or(self, term: str, opts: "matching.MatchOptions") -> tantivy.Query:
        """התאמת מילה בודדת על פני השדות, לפי אפשרויות."""
        assert self.schema is not None
        shoulds: List[Tuple[tantivy.Occur, tantivy.Query]] = [
            (tantivy.Occur.Should, tantivy.Query.term_query(self.schema, "content", term)),
        ]
        if not opts.whole_word:
            stem = hebrew.light_stem(term)
            shoulds += [
                (tantivy.Occur.Should, tantivy.Query.term_query(self.schema, "content_stem", stem)),
                (tantivy.Occur.Should, tantivy.Query.term_query(self.schema, "content_stem", term)),
            ]
            shoulds.append(
                (
                    tantivy.Occur.Should,
                    tantivy.Query.boost_query(
                        tantivy.Query.term_query(self.schema, "name", term), 2.5
                    ),
                )
            )
        if opts.fold_vy or opts.fold_aa:
            folded = matching.full_fold(term)
            shoulds.append(
                (tantivy.Occur.Should, tantivy.Query.term_query(self.schema, "content_fold", folded))
            )
            if not opts.whole_word:
                folded_stem = matching.full_fold(hebrew.light_stem(term))
                shoulds.append(
                    (tantivy.Occur.Should, tantivy.Query.term_query(self.schema, "content_fold", folded_stem))
                )
        return tantivy.Query.boolean_query(shoulds)

    def search(
        self,
        raw_query: str,
        limit: int = 50,
        offset: int = 0,
        opts: Optional["matching.MatchOptions"] = None,
    ) -> Tuple[List[Tuple[int, float]], int]:
        """מחזיר (רשימת (file_id, score), מספר תוצאות כולל)."""
        assert self.index is not None
        query = self._build_query(raw_query, opts=opts)
        if query is None:
            return [], 0
        self.index.reload()
        searcher = self.index.searcher()
        result = searcher.search(query, limit=limit + offset, count=True)
        hits = result.hits[offset : offset + limit]
        out: List[Tuple[int, float]] = []
        for score, addr in hits:
            doc = searcher.doc(addr)
            file_id = doc.get_first("file_id")
            out.append((int(file_id), float(score)))
        return out, result.count

    def num_docs(self) -> int:
        if self.index is None:
            return 0
        self.index.reload()
        return self.index.searcher().num_docs


engine = SearchEngine()
