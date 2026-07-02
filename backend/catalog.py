"""קטלוג מבוסס SQLite: מטא-דאטה של קבצים, טקסט מחולץ ומיקומי קטעים.

הקטלוג הוא מקור האמת לתצוגה: הטקסט המקורי נשמר כאן (עבור הצגת הקשר, הדגשה
וייצוא), בעוד ש-Tantivy מחזיק את האינדקס לחיפוש בלבד. שמירת מיקומי העמודים
מאפשרת פתיחת PDF בעמוד הרלוונטי.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

from .config import settings
from .logging_setup import get_logger

log = get_logger("catalog")


@dataclass
class Segment:
    """קטע טקסט (בדרך כלל עמוד) עם מיקומו בטקסט המלא של הקובץ."""

    page: Optional[int]
    char_start: int
    char_end: int


class Catalog:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or settings.db_path
        self._lock = Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        settings.ensure_dirs()
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False, timeout=30.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        log.info("קטלוג מחובר: %s", self.db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    def _create_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id          INTEGER PRIMARY KEY,
                path        TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                ext         TEXT,
                size        INTEGER,
                mtime       REAL,
                sha1        TEXT,
                status      TEXT DEFAULT 'pending',
                error       TEXT,
                source      TEXT,
                page_count  INTEGER DEFAULT 0,
                char_count  INTEGER DEFAULT 0,
                full_text   TEXT,
                indexed_at  REAL
            );

            CREATE TABLE IF NOT EXISTS segments (
                id          INTEGER PRIMARY KEY,
                file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                seq         INTEGER NOT NULL,
                page        INTEGER,
                char_start  INTEGER NOT NULL,
                char_end    INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_segments_file ON segments(file_id);

            CREATE TABLE IF NOT EXISTS roots (
                path      TEXT PRIMARY KEY,
                added_at  REAL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key    TEXT PRIMARY KEY,
                value  TEXT
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                id          INTEGER PRIMARY KEY,
                book_path   TEXT NOT NULL,
                book_name   TEXT NOT NULL,
                view        TEXT DEFAULT 'text',
                position    TEXT,
                label       TEXT,
                created_at  REAL
            );
            """
        )
        self.conn.commit()

    # ---- ניהול תיקיות מנוטרות ----
    def add_root(self, path: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO roots(path, added_at) VALUES (?, ?)",
                (path, time.time()),
            )
            self.conn.commit()

    def remove_root(self, path: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM roots WHERE path = ?", (path,))
            self.conn.commit()

    def list_roots(self) -> List[str]:
        rows = self.conn.execute("SELECT path FROM roots ORDER BY path").fetchall()
        return [r["path"] for r in rows]

    # ---- קבצים ----
    def get_file_by_path(self, path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE path = ?", (path,)
        ).fetchone()

    def get_file(self, file_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE id = ?", (file_id,)
        ).fetchone()

    def needs_reindex(self, path: str, sha1: str) -> bool:
        row = self.get_file_by_path(path)
        if row is None:
            return True
        # קובץ שכבר אונדקס או ממתין ל-OCR ולא השתנה - אין צורך לחלץ טקסט מחדש
        if row["status"] not in ("indexed", "pending_ocr"):
            return True
        return row["sha1"] != sha1

    def mark_pending_ocr(self, file_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE files SET status='pending_ocr', error=NULL WHERE id=?",
                (file_id,),
            )
            self.conn.commit()

    def list_pending_ocr(self, limit: int = 1) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE status='pending_ocr' ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()

    def count_pending_ocr(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM files WHERE status='pending_ocr'"
        ).fetchone()
        return row["c"] if row else 0

    # ---- הגדרות ----
    def get_setting(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            self.conn.commit()

    def all_settings(self) -> Dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ---- סימניות ----
    def add_bookmark(self, book_path: str, book_name: str, view: str, position: str, label: str) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO bookmarks (book_path, book_name, view, position, label, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (book_path, book_name, view, position, label, time.time()),
            )
            self.conn.commit()
            return cur.lastrowid

    def list_bookmarks(self) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM bookmarks ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_bookmark(self, bookmark_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
            self.conn.commit()

    def delete_bookmarks(self, ids: List[int]) -> None:
        if not ids:
            return
        with self._lock:
            self.conn.executemany(
                "DELETE FROM bookmarks WHERE id = ?", [(i,) for i in ids]
            )
            self.conn.commit()

    def find_indexed_by_sha1(self, sha1: str, exclude_id: int = 0) -> Optional[sqlite3.Row]:
        """מוצא קובץ אחר עם אותו תוכן (sha1) - לשימוש חוזר ב-OCR.

        מוגבל לקבצים שתוכנם הגיע מ-OCR (מלא או חלקי): שם החיסכון האמיתי.
        כולל רשומות 'cache' - טקסטים שיובאו ממחשב אחר עבור קבצים שטרם נסרקו.
        """
        return self.conn.execute(
            "SELECT * FROM files WHERE sha1=? AND id!=? AND status IN ('indexed','cache') "
            "AND source IN ('ocr','mixed') AND full_text IS NOT NULL LIMIT 1",
            (sha1, exclude_id),
        ).fetchone()

    def import_content_row(
        self, path: str, name: str, ext: str, size: int, mtime: float, sha1: str,
        full_text: str, segments: List[Segment], source: str, page_count: int,
        status: str = "indexed",
    ) -> int:
        """מוסיף רשומה מיובאת (מגיבוי) עם תוכן מלא. לא דורס רשומה מאונדקסת קיימת."""
        with self._lock:
            row = self.conn.execute(
                "SELECT id, status FROM files WHERE path=?", (path,)
            ).fetchone()
            if row is not None and row["status"] == "indexed":
                return row["id"]
            if row is None:
                cur = self.conn.execute(
                    "INSERT INTO files (path, name, ext, size, mtime, sha1, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (path, name, ext, size, mtime, sha1, status),
                )
                file_id = cur.lastrowid
            else:
                file_id = row["id"]
            self.conn.execute("DELETE FROM segments WHERE file_id=?", (file_id,))
            self.conn.executemany(
                "INSERT INTO segments (file_id, seq, page, char_start, char_end) "
                "VALUES (?, ?, ?, ?, ?)",
                [(file_id, i, s.page, s.char_start, s.char_end) for i, s in enumerate(segments)],
            )
            self.conn.execute(
                "UPDATE files SET status=?, error=NULL, source=?, page_count=?, "
                "char_count=?, full_text=?, indexed_at=?, sha1=?, size=?, mtime=? WHERE id=?",
                (status, source, page_count, len(full_text), full_text,
                 time.time(), sha1, size, mtime, file_id),
            )
            self.conn.commit()
            return file_id

    def backup_to(self, target: Path) -> None:
        """עותק עקבי של הקטלוג (SQLite backup API) - בטוח גם תוך כדי עבודה."""
        with self._lock:
            dest = sqlite3.connect(str(target))
            try:
                self.conn.backup(dest)
            finally:
                dest.close()

    def mark_ocr_rerun(self) -> int:
        """מחזיר לתור ה-OCR את כל הקבצים שתוכנם הגיע מ-OCR (מלא או חלקי).

        משמש את כפתור "הרצת OCR מחדש" לאחר שינוי מנוע/הגדרות. כולל גם קבצי
        תמונה/PDF שנכשלו ב-OCR קודם - ייתכן שמנוע אחר יצליח.
        """
        img_exts = ",".join(f"'{e}'" for e in sorted(settings.image_extensions))
        with self._lock:
            cur = self.conn.execute(
                "UPDATE files SET status='pending_ocr', error=NULL "
                "WHERE (status='indexed' AND source IN ('ocr','mixed')) "
                f"   OR (status='error' AND ext IN ({img_exts}, '.pdf'))"
            )
            self.conn.commit()
            return cur.rowcount or 0

    def mark_pdfs_for_reextract(self) -> int:
        """מסמן קבצי PDF שחולצו משכבת טקסט (ללא OCR) לחילוץ-מחדש.

        משמש במעבר גרסת אלגוריתם החילוץ: קבצים שמקורם OCR אינם מסומנים,
        כדי לא להריץ OCR יקר מחדש (הערת לקוח: OCR פעם אחת לכל קובץ).
        """
        with self._lock:
            cur = self.conn.execute(
                "UPDATE files SET status='pending' "
                "WHERE ext='.pdf' AND status='indexed' AND source='extracted'"
            )
            self.conn.commit()
            return cur.rowcount or 0

    def iter_indexed_files(self) -> List[sqlite3.Row]:
        """כל הקבצים המאונדקסים עם תוכנם - לבניית אינדקס מחדש."""
        return self.conn.execute(
            "SELECT id, path, name, ext, mtime, full_text FROM files "
            "WHERE status='indexed' AND full_text IS NOT NULL"
        ).fetchall()

    def upsert_file_meta(
        self, path: str, name: str, ext: str, size: int, mtime: float, sha1: str
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO files (path, name, ext, size, mtime, sha1, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name, ext=excluded.ext, size=excluded.size,
                    mtime=excluded.mtime, sha1=excluded.sha1, status='pending',
                    error=NULL
                """,
                (path, name, ext, size, mtime, sha1),
            )
            self.conn.commit()
            if cur.lastrowid:
                row = self.get_file_by_path(path)
                return row["id"] if row else cur.lastrowid
            row = self.get_file_by_path(path)
            return row["id"]

    def save_content(
        self,
        file_id: int,
        full_text: str,
        segments: List[Segment],
        source: str,
        page_count: int,
    ) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM segments WHERE file_id = ?", (file_id,))
            self.conn.executemany(
                "INSERT INTO segments (file_id, seq, page, char_start, char_end) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (file_id, i, s.page, s.char_start, s.char_end)
                    for i, s in enumerate(segments)
                ],
            )
            self.conn.execute(
                "UPDATE files SET status='indexed', error=NULL, source=?, "
                "page_count=?, char_count=?, full_text=?, indexed_at=? WHERE id=?",
                (source, page_count, len(full_text), full_text, time.time(), file_id),
            )
            self.conn.commit()

    def mark_error(self, file_id: int, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE files SET status='error', error=? WHERE id=?",
                (error[:2000], file_id),
            )
            self.conn.commit()

    def delete_file(self, path: str) -> Optional[int]:
        row = self.get_file_by_path(path)
        if row is None:
            return None
        with self._lock:
            self.conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
            self.conn.commit()
        return row["id"]

    def get_content(self, file_id: int) -> Optional[str]:
        row = self.conn.execute(
            "SELECT full_text FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        return row["full_text"] if row else None

    def get_segments(self, file_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM segments WHERE file_id = ? ORDER BY seq", (file_id,)
        ).fetchall()

    def page_for_offset(self, file_id: int, offset: int) -> Optional[int]:
        """מוצא את מספר העמוד שאליו שייך היסט תווים נתון."""
        row = self.conn.execute(
            "SELECT page FROM segments WHERE file_id = ? AND char_start <= ? "
            "AND char_end >= ? ORDER BY seq LIMIT 1",
            (file_id, offset, offset),
        ).fetchone()
        return row["page"] if row else None

    def stats(self) -> Dict:
        cur = self.conn.cursor()
        total = cur.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
        indexed = cur.execute(
            "SELECT COUNT(*) c FROM files WHERE status='indexed'"
        ).fetchone()["c"]
        errors = cur.execute(
            "SELECT COUNT(*) c FROM files WHERE status='error'"
        ).fetchone()["c"]
        chars = cur.execute(
            "SELECT COALESCE(SUM(char_count),0) s FROM files WHERE status='indexed'"
        ).fetchone()["s"]
        return {
            "total_files": total,
            "indexed_files": indexed,
            "error_files": errors,
            "total_chars": chars,
            "roots": self.list_roots(),
        }

    def all_indexed_paths(self) -> List[str]:
        rows = self.conn.execute(
            "SELECT path FROM files WHERE status='indexed'"
        ).fetchall()
        return [r["path"] for r in rows]

    def list_errors(self) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT path, error FROM files WHERE status='error' ORDER BY indexed_at DESC LIMIT 200"
        ).fetchall()
        return [{"path": r["path"], "error": r["error"]} for r in rows]


catalog = Catalog()
