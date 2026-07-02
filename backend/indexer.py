"""אינדקסר דו-שלבי.

שלב א׳ (מהיר): חילוץ שכבת טקסט בלבד ואינדוקס מיידי, כך שהחיפוש זמין כמעט מיד.
קבצים סרוקים ללא טקסט מסומנים ``pending_ocr`` ונכנסים לתור.
שלב ב׳ (רקע): worker קבוע שמנקז את תור ה-OCR בעדיפות נמוכה, מריץ OCR מקבילי
ומעדכן את האינדקס - בלי לחסום את החיפוש. commit מבוסס-זמן מציג תוצאות בהדרגה.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .catalog import Catalog, Segment, catalog
from .config import settings
from .extractors import extract_file, is_supported
from .logging_setup import get_logger
from .search_engine import SearchEngine, engine

log = get_logger("indexer")

_PAGE_SEP = "\n\n"
_COMMIT_INTERVAL = 2.0  # שניות בין commit-ים להצגת תוצאות מיידית


@dataclass
class Progress:
    running: bool = False
    phase: str = "idle"          # idle / scanning / indexing / done / error
    total: int = 0
    processed: int = 0
    indexed: int = 0
    pending_ocr: int = 0
    skipped: int = 0
    errors: int = 0
    current: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "phase": self.phase,
            "total": self.total,
            "processed": self.processed,
            "indexed": self.indexed,
            "pending_ocr": self.pending_ocr,
            "skipped": self.skipped,
            "errors": self.errors,
            "current": self.current,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _sha1_of(path: Path, size: int) -> str:
    """hash מהיר: לקבצים גדולים מדגמים חלקים, לקטנים - הכל."""
    h = hashlib.sha1()
    h.update(str(size).encode())
    try:
        with path.open("rb") as f:
            if size <= 4 * 1024 * 1024:
                h.update(f.read())
            else:
                for _ in range(3):
                    h.update(f.read(1024 * 1024))
                    f.seek(max(0, size // 2), os.SEEK_SET)
    except Exception:
        pass
    return h.hexdigest()


def _build_full_text(pages):
    """בונה טקסט מלא + מיקומי עמודים מרשימת עמודים."""
    full_parts: List[str] = []
    segments: List[Segment] = []
    cursor = 0
    for page in pages:
        text = page.text or ""
        start = cursor
        full_parts.append(text)
        cursor += len(text)
        segments.append(Segment(page=page.number, char_start=start, char_end=cursor))
        full_parts.append(_PAGE_SEP)
        cursor += len(_PAGE_SEP)
    return "".join(full_parts), segments


class Indexer:
    def __init__(self, cat: Catalog, eng: SearchEngine) -> None:
        self.catalog = cat
        self.engine = eng
        self.progress = Progress()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

        # סטטוס worker ה-OCR הרקעי
        self.ocr_status = {"running": False, "pending": 0, "current": "", "page": 0, "pages": 0}
        self._ocr_thread: Optional[threading.Thread] = None
        self._ocr_stop = threading.Event()

    # ---- API ציבורי ----
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        self._cancel.set()

    def start_index_roots(self, roots: List[str]) -> bool:
        if self.is_running():
            return False
        for r in roots:
            self.catalog.add_root(r)
        self._launch(self._run_index_paths, roots)
        return True

    def start_reindex_all(self) -> bool:
        if self.is_running():
            return False
        roots = self.catalog.list_roots()
        self._launch(self._run_index_paths, roots)
        return True

    def _launch(self, target, *args) -> None:
        self._cancel.clear()
        self._thread = threading.Thread(target=self._guard(target), args=args, daemon=True)
        self._thread.start()

    def _guard(self, target):
        def wrapper(*args):
            try:
                target(*args)
            except Exception as exc:
                log.exception("אינדוקס נכשל: %s", exc)
                self.progress.phase = "error"
            finally:
                self.progress.running = False
                self.progress.finished_at = time.time()
                try:
                    self.engine.commit()
                except Exception as exc:
                    log.warning("commit בסיום נכשל: %s", exc)
        return wrapper

    # ---- איסוף קבצים ----
    def _collect_files(self, roots: List[str]) -> List[Path]:
        files: List[Path] = []
        for root in roots:
            root_path = Path(root)
            if root_path.is_file():
                if is_supported(root_path):
                    files.append(root_path)
                continue
            for dirpath, dirnames, filenames in os.walk(root_path):
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".")
                    and d.lower() not in {"node_modules", "$recycle.bin", "system volume information"}
                ]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    if is_supported(p):
                        files.append(p)
        return files

    # ---- שלב א׳: אינדוקס טקסט מהיר ----
    def _run_index_paths(self, roots: List[str]) -> None:
        self.progress = Progress(running=True, phase="scanning", started_at=time.time())
        log.info("סריקת תיקיות: %s", roots)
        files = self._collect_files(roots)
        self.progress.total = len(files)
        self.progress.phase = "indexing"
        log.info("נמצאו %d קבצים נתמכים", len(files))

        last_commit = time.time()
        dirty = False
        for path in files:
            if self._cancel.is_set():
                log.info("האינדוקס בוטל על ידי המשתמש")
                break
            self.progress.current = str(path)
            self.progress.processed += 1
            try:
                status = self._index_one(path, allow_ocr=False)
                if status == "indexed":
                    self.progress.indexed += 1
                    dirty = True
                elif status == "pending_ocr":
                    self.progress.pending_ocr += 1
                    dirty = True
                elif status == "error":
                    self.progress.errors += 1
                else:
                    self.progress.skipped += 1
            except Exception as exc:
                self.progress.errors += 1
                log.warning("כשל באינדוקס %s: %s", path, exc)

            if dirty and (time.time() - last_commit) >= _COMMIT_INTERVAL:
                self.engine.commit()
                last_commit = time.time()
                dirty = False

        self.engine.commit()
        self._cleanup_deleted(files)
        self.progress.phase = "done"
        self.ocr_status["pending"] = self.catalog.count_pending_ocr()
        log.info(
            "שלב טקסט הסתיים: %d מאונדקסים, %d ממתינים ל-OCR, %d דילוגים, %d שגיאות",
            self.progress.indexed, self.progress.pending_ocr,
            self.progress.skipped, self.progress.errors,
        )

    def _index_one(self, path: Path, allow_ocr: bool = False) -> str:
        """שלב טקסט מהיר לקובץ בודד.

        מחזיר: 'indexed' / 'pending_ocr' / 'skipped' / 'error'.
        """
        try:
            stat = path.stat()
        except OSError:
            return "skipped"

        size = stat.st_size
        if size > settings.max_file_mb * 1024 * 1024:
            log.debug("דילוג על קובץ גדול מדי: %s", path)
            return "skipped"

        sha1 = _sha1_of(path, size)
        if not self.catalog.needs_reindex(str(path), sha1):
            return "skipped"

        file_id = self.catalog.upsert_file_meta(
            path=str(path), name=path.name, ext=path.suffix.lower(),
            size=size, mtime=stat.st_mtime, sha1=sha1,
        )

        result = extract_file(path, allow_ocr=allow_ocr)
        full_text, segments = _build_full_text(result.pages)
        has_text = bool(full_text.strip())

        if has_text:
            self.catalog.save_content(
                file_id=file_id, full_text=full_text, segments=segments,
                source=result.source, page_count=len(result.pages),
            )
            self.engine.add_document(
                file_id=file_id, path=str(path), name=path.name,
                ext=path.suffix.lower(), mtime=int(stat.st_mtime), content=full_text,
            )
            # מסמך מעורב (חלק סרוק) - מסמנים גם ל-OCR רקעי להשלמה
            if result.needs_ocr:
                self.catalog.mark_pending_ocr(file_id)
                return "pending_ocr"
            return "indexed"

        # אין טקסט
        if result.needs_ocr:
            self.catalog.mark_pending_ocr(file_id)
            return "pending_ocr"
        self.catalog.mark_error(file_id, "לא נמצא טקסט בקובץ")
        return "error"

    # ---- שלב ב׳: worker רקעי ל-OCR ----
    def start_ocr_worker(self) -> None:
        if self._ocr_thread is not None and self._ocr_thread.is_alive():
            return
        self._ocr_stop.clear()
        self._ocr_thread = threading.Thread(target=self._ocr_loop, daemon=True)
        self._ocr_thread.start()
        log.info("worker רקעי ל-OCR הופעל")

    def stop_ocr_worker(self) -> None:
        self._ocr_stop.set()

    def _ocr_loop(self) -> None:
        was_working = False
        while not self._ocr_stop.is_set():
            try:
                pending = self.catalog.count_pending_ocr()
                self.ocr_status["pending"] = pending
                if pending == 0:
                    self.ocr_status["running"] = False
                    self.ocr_status["current"] = ""
                    if was_working:
                        # התור התרוקן - משחררים משאבי מנועים (למשל worker של Surya)
                        was_working = False
                        try:
                            from .extractors import ocr_engines

                            ocr_engines.idle_engines()
                        except Exception as exc:
                            log.debug("שחרור מנועי OCR נכשל: %s", exc)
                    time.sleep(2.0)
                    continue
                was_working = True
                rows = self.catalog.list_pending_ocr(limit=1)
                if not rows:
                    time.sleep(1.0)
                    continue
                row = rows[0]
                self.ocr_status["running"] = True
                self._process_ocr(row)
            except Exception as exc:
                log.warning("שגיאה ב-worker ה-OCR: %s", exc)
                time.sleep(2.0)

    def _process_ocr(self, row) -> None:
        file_id = row["id"]
        path = Path(row["path"])
        self.ocr_status["current"] = str(path)
        self.ocr_status["page"] = 0
        self.ocr_status["pages"] = 0

        if not path.exists():
            self.catalog.mark_error(file_id, "הקובץ לא נמצא בעת OCR")
            return

        def cb(done: int, total: int) -> None:
            self.ocr_status["page"] = done
            self.ocr_status["pages"] = total

        # עד 3 ניסיונות: קובץ עשוי להיות נעול זמנית (למשל בזמן העתקה לתיקייה)
        result = None
        full_text, segments = "", []
        for attempt in range(3):
            try:
                result = extract_file(path, allow_ocr=True, progress_cb=cb)
            except Exception as exc:
                log.warning("OCR נכשל עבור %s (ניסיון %d): %s", path, attempt + 1, exc)
                result = None
            if result is not None:
                full_text, segments = _build_full_text(result.pages)
                if full_text.strip():
                    break
            if attempt < 2:
                time.sleep(3.0)

        if result is None:
            self.catalog.mark_error(file_id, "OCR נכשל")
            return
        if not full_text.strip():
            self.catalog.mark_error(file_id, "OCR לא הפיק טקסט")
            return

        self.catalog.save_content(
            file_id=file_id, full_text=full_text, segments=segments,
            source=result.source, page_count=len(result.pages),
        )
        self.engine.add_document(
            file_id=file_id, path=str(path), name=path.name,
            ext=path.suffix.lower(), mtime=int(row["mtime"] or 0), content=full_text,
        )
        self.engine.commit()
        log.info("OCR הושלם ואונדקס: %s", path)

    def rebuild_index_from_catalog(self) -> None:
        """בונה את אינדקס Tantivy מחדש מהתוכן השמור בקטלוג (ללא חילוץ/OCR מחדש).

        משמש במעבר גרסת סכמה. רץ ברקע ומהיר יחסית (הטקסטים כבר ב-SQLite).
        """
        def run():
            try:
                rows = self.catalog.iter_indexed_files()
                log.info("בנייה מחדש של האינדקס מהקטלוג: %d קבצים", len(rows))
                for i, row in enumerate(rows):
                    self.engine.add_document(
                        file_id=row["id"],
                        path=row["path"],
                        name=row["name"],
                        ext=row["ext"] or "",
                        mtime=int(row["mtime"] or 0),
                        content=row["full_text"] or "",
                    )
                    if (i + 1) % 100 == 0:
                        self.engine.commit()
                self.engine.commit()
                log.info("בנייה מחדש של האינדקס הושלמה")
            except Exception as exc:
                log.exception("בנייה מחדש של האינדקס נכשלה: %s", exc)

        threading.Thread(target=run, daemon=True).start()

    def _cleanup_deleted(self, current_files: List[Path]) -> None:
        try:
            current = {str(p) for p in current_files}
            for path in self.catalog.all_indexed_paths():
                if path not in current and not Path(path).exists():
                    fid = self.catalog.delete_file(path)
                    if fid is not None:
                        self.engine.delete_document(fid)
                        log.info("הוסר קובץ שנמחק: %s", path)
        except Exception as exc:
            log.warning("ניקוי קבצים שנמחקו נכשל: %s", exc)


indexer = Indexer(catalog, engine)
