"""מעקב חי אחר שינויי קבצים לעדכון מצטבר של האינדקס.

משתמש ב-watchdog לניטור התיקיות המנוטרות. אירועים עוברים דה-באונסינג
(איגום לזמן קצר) כדי להימנע מאינדוקס חוזר בזמן כתיבה, ומעובדים ב-thread
ייעודי שמאנדקס קבצים שהשתנו ומסיר קבצים שנמחקו.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .catalog import catalog
from .extractors import is_supported
from .indexer import indexer
from .logging_setup import get_logger
from .search_engine import engine

log = get_logger("watcher")

_DEBOUNCE_SEC = 2.0


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "FileWatcher") -> None:
        self.watcher = watcher

    def on_created(self, event):
        if not event.is_directory:
            self.watcher.queue_change(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.watcher.queue_change(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.watcher.queue_delete(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.watcher.queue_delete(event.src_path)
            self.watcher.queue_change(event.dest_path)


class FileWatcher:
    def __init__(self) -> None:
        self._observer: Optional[Observer] = None
        self._pending_change: Dict[str, float] = {}
        self._pending_delete: Set[str] = set()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._active = False

    def is_active(self) -> bool:
        return self._active

    def queue_change(self, path: str) -> None:
        p = Path(path)
        if not is_supported(p):
            return
        with self._lock:
            self._pending_change[str(p)] = time.time()
            self._pending_delete.discard(str(p))

    def queue_delete(self, path: str) -> None:
        with self._lock:
            self._pending_delete.add(str(path))
            self._pending_change.pop(str(path), None)

    def start(self) -> bool:
        if self._active:
            return False
        roots = [r for r in catalog.list_roots() if Path(r).exists()]
        if not roots:
            log.info("אין תיקיות לניטור")
            return False

        self._observer = Observer()
        handler = _Handler(self)
        for root in roots:
            try:
                self._observer.schedule(handler, root, recursive=True)
            except Exception as exc:
                log.warning("ניטור נכשל עבור %s: %s", root, exc)
        self._observer.start()

        self._stop.clear()
        self._worker = threading.Thread(target=self._process_loop, daemon=True)
        self._worker.start()
        self._active = True
        log.info("מעקב חי הופעל על %d תיקיות", len(roots))
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception:
                pass
            self._observer = None
        self._active = False
        log.info("מעקב חי הופסק")

    def restart(self) -> None:
        self.stop()
        self.start()

    def _process_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(1.0)
            if indexer.is_running():
                continue  # לא מתערבים באינדוקס מלא שרץ
            now = time.time()
            ready_changes: List[str] = []
            ready_deletes: List[str] = []
            with self._lock:
                for path, ts in list(self._pending_change.items()):
                    if now - ts >= _DEBOUNCE_SEC:
                        ready_changes.append(path)
                        del self._pending_change[path]
                if self._pending_delete:
                    ready_deletes = list(self._pending_delete)
                    self._pending_delete.clear()

            changed = False
            for path in ready_deletes:
                try:
                    fid = catalog.delete_file(path)
                    if fid is not None:
                        engine.delete_document(fid)
                        changed = True
                        log.info("הוסר מהאינדקס (נמחק): %s", path)
                except Exception as exc:
                    log.warning("הסרה נכשלה עבור %s: %s", path, exc)

            for path in ready_changes:
                try:
                    # טקסט-ראשון: OCR (אם נדרש) יטופל ע"י ה-worker הרקעי
                    status = indexer._index_one(Path(path), allow_ocr=False)
                    if status in ("indexed", "pending_ocr"):
                        changed = True
                        log.info("אונדקס מחדש (השתנה): %s [%s]", path, status)
                except Exception as exc:
                    log.warning("אינדוקס מצטבר נכשל עבור %s: %s", path, exc)

            if changed:
                try:
                    engine.commit()
                except Exception as exc:
                    log.warning("commit במעקב נכשל: %s", exc)


watcher = FileWatcher()
