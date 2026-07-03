"""שרת ה-FastAPI המקומי: API לחיפוש, אינדוקס, פתיחה, ייצוא ולוגים.

מגיש גם את ה-frontend הבנוי (אם קיים) כדי שהכל ירוץ מתהליך אחד - חיוני
לאריזה ל-EXE יחיד.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import hebrew, library, search_service
from .catalog import catalog
from .config import settings
from .indexer import indexer
from .logging_setup import get_logger, ring_buffer, setup_logging
from .search_engine import engine
from .watcher import watcher

log = get_logger("server")


# ---- מודלים ----
class IndexRequest(BaseModel):
    paths: List[str]


class RootRequest(BaseModel):
    path: str


class OpenRequest(BaseModel):
    path: str
    page: Optional[int] = None


class ExportResultsRequest(BaseModel):
    query: str = ""
    file_ids: List[int] = []
    include_full_text: bool = False


class SettingsRequest(BaseModel):
    values: dict


class BookmarkRequest(BaseModel):
    book_path: str
    book_name: str
    view: str = "text"
    position: str = ""
    label: str = ""


class RegionOcrRequest(BaseModel):
    path: str
    x: float
    y: float
    w: float
    h: float


class TransferRequest(BaseModel):
    path: str
    components: List[str] = []


class TrainingRequest(BaseModel):
    font_paths: List[str]
    name: str
    noise: str = "medium"       # low / medium / high
    lines: int = 400
    iterations: int = 400


class SearchRequest(BaseModel):
    q: str
    limit: int = 30
    offset: int = 0
    exact: bool = False
    whole_word: bool = False
    fold_vy: bool = False
    fold_aa: bool = False
    min_words: int = 0
    proximity: int = 30
    exts: List[str] = []
    folder: str = ""
    paths: List[str] = []


class BookmarksDeleteRequest(BaseModel):
    ids: List[int]


class SmartExtractRequest(BaseModel):
    path: str


class BookSearchRequest(BaseModel):
    path: str
    q: str
    exact: bool = False
    whole_word: bool = False
    fold_vy: bool = False
    fold_aa: bool = False


class SyncPositionRequest(BaseModel):
    text_path: str
    pdf_path: str
    direction: str  # to_pdf / to_text
    offset: Optional[int] = None
    page: Optional[int] = None


class ClipboardRequest(BaseModel):
    text: str


class SaveTextFileRequest(BaseModel):
    path: str
    text: str
    format: str = "txt"  # txt / docx


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="חיפוש עברי", version="0.3.3")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        from .extractors.pdf_extractor import EXTRACT_VERSION
        from .search_engine import INDEX_SCHEMA_VERSION

        catalog.connect()

        # מעבר גרסת סכמת אינדקס: מחיקה ובנייה מחדש מהקטלוג (ללא OCR מחדש)
        current_ver = catalog.get_setting("index_version")
        needs_rebuild = current_ver != INDEX_SCHEMA_VERSION
        if needs_rebuild:
            log.info(
                "גרסת אינדקס השתנתה (%s -> %s) - בונה אינדקס מחדש מהקטלוג",
                current_ver, INDEX_SCHEMA_VERSION,
            )
            engine.wipe()

        engine.open()

        if needs_rebuild:
            catalog.set_setting("index_version", INDEX_SCHEMA_VERSION)
            indexer.rebuild_index_from_catalog()

        # מעבר גרסת אלגוריתם חילוץ PDF: חילוץ טקסט מחדש ברקע (ללא OCR מחדש)
        if catalog.get_setting("extract_version") != EXTRACT_VERSION:
            n = catalog.mark_pdfs_for_reextract()
            catalog.set_setting("extract_version", EXTRACT_VERSION)
            if n:
                log.info("גרסת חילוץ PDF השתנתה - %d קבצים יחולצו מחדש ברקע", n)
                indexer.start_reindex_all()

        log.info("השרת מוכן. מסמכים באינדקס: %d", engine.num_docs())
        try:
            import threading

            threading.Thread(target=_install_bundled_fonts, daemon=True).start()
        except Exception as exc:
            log.warning("התקנת גופנים לא הופעלה: %s", exc)
        try:
            watcher.start()
        except Exception as exc:
            log.warning("הפעלת מעקב חי נכשלה: %s", exc)
        try:
            indexer.start_ocr_worker()
        except Exception as exc:
            log.warning("הפעלת worker ה-OCR נכשלה: %s", exc)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        from .extractors import ocr_engines

        watcher.stop()
        indexer.stop_ocr_worker()
        ocr_engines.idle_engines()

    # ---- בריאות וסטטיסטיקה ----
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "docs": engine.num_docs()}

    @app.get("/api/stats")
    def stats() -> dict:
        s = catalog.stats()
        s["index_docs"] = engine.num_docs()
        s["ocr_available"] = _ocr_available()
        s["watch_active"] = watcher.is_active()
        s["ocr_pending"] = indexer.ocr_status.get("pending", 0)
        return s

    # ---- תיקיות מנוטרות ----
    @app.get("/api/roots")
    def get_roots() -> dict:
        return {"roots": catalog.list_roots()}

    @app.post("/api/roots")
    def add_root(req: RootRequest) -> dict:
        p = Path(req.path)
        if not p.exists():
            raise HTTPException(400, "הנתיב אינו קיים")
        catalog.add_root(str(p))
        _restart_watch_async()
        return {"roots": catalog.list_roots()}

    @app.delete("/api/roots")
    def remove_root(req: RootRequest) -> dict:
        catalog.remove_root(req.path)
        _restart_watch_async()
        return {"roots": catalog.list_roots()}

    @app.get("/api/watch")
    def watch_status() -> dict:
        return {"active": watcher.is_active()}

    @app.post("/api/watch/start")
    def watch_start() -> dict:
        watcher.start()
        return {"active": watcher.is_active()}

    @app.post("/api/watch/stop")
    def watch_stop() -> dict:
        watcher.stop()
        return {"active": watcher.is_active()}

    # ---- אינדוקס ----
    @app.post("/api/index")
    def start_index(req: IndexRequest) -> dict:
        ok = indexer.start_index_roots(req.paths)
        if not ok:
            raise HTTPException(409, "אינדוקס כבר רץ")
        return {"started": True}

    @app.post("/api/reindex")
    def reindex() -> dict:
        ok = indexer.start_reindex_all()
        if not ok:
            raise HTTPException(409, "אינדוקס כבר רץ")
        return {"started": True}

    @app.post("/api/index/cancel")
    def cancel_index() -> dict:
        indexer.cancel()
        return {"cancelled": True}

    @app.get("/api/progress")
    def progress() -> dict:
        snap = indexer.progress.snapshot()
        snap["ocr"] = indexer.ocr_status
        return snap

    # ---- חיפוש ----
    @app.post("/api/search")
    def do_search_post(req: SearchRequest) -> dict:
        from . import matching

        opts = matching.MatchOptions(
            exact=req.exact,
            whole_word=req.whole_word,
            fold_vy=req.fold_vy,
            fold_aa=req.fold_aa,
            min_words=req.min_words,
            proximity=req.proximity,
        )
        return search_service.search(
            query=req.q,
            limit=req.limit,
            offset=req.offset,
            opts=opts,
            exts=req.exts or None,
            folder=req.folder or None,
            paths=req.paths or None,
        )

    @app.get("/api/search")
    def do_search(
        q: str,
        limit: int = 30,
        offset: int = 0,
        exact: bool = False,
        exts: Optional[str] = None,
        folder: Optional[str] = None,
    ) -> dict:
        from . import matching

        ext_list = [e for e in (exts.split(",") if exts else []) if e]
        return search_service.search(
            query=q,
            limit=limit,
            offset=offset,
            opts=matching.MatchOptions(exact=exact),
            exts=ext_list or None,
            folder=folder,
        )

    @app.get("/api/search/progress")
    def search_progress() -> dict:
        st = dict(search_service.search_status)
        if st.get("running") and st.get("started_at"):
            st["elapsed"] = round(time.time() - st["started_at"], 2)
        return st

    @app.get("/api/document/{file_id}")
    def document(
        file_id: int,
        q: Optional[str] = None,
        exact: bool = False,
        whole_word: bool = False,
        fold_vy: bool = False,
        fold_aa: bool = False,
    ) -> dict:
        from . import matching

        opts = matching.MatchOptions(
            exact=exact, whole_word=whole_word, fold_vy=fold_vy, fold_aa=fold_aa, proximity=0
        )
        doc = search_service.get_document_text(file_id, query=q, opts=opts)
        if doc is None:
            raise HTTPException(404, "המסמך לא נמצא")
        return doc

    # ---- פתיחה במיקום ----
    @app.post("/api/open")
    def open_file(req: OpenRequest) -> dict:
        path = Path(req.path)
        if not path.exists():
            raise HTTPException(404, "הקובץ לא נמצא בדיסק")
        try:
            if path.suffix.lower() == ".pdf" and req.page:
                url = path.resolve().as_uri() + f"#page={req.page}"
                webbrowser.open(url)
            else:
                _open_with_default(path)
            log.info("נפתח קובץ: %s (עמוד %s)", path, req.page)
            return {"opened": True}
        except Exception as exc:
            log.warning("פתיחת קובץ נכשלה: %s", exc)
            raise HTTPException(500, f"פתיחה נכשלה: {exc}")

    @app.post("/api/reveal")
    def reveal_file(req: OpenRequest) -> dict:
        path = Path(req.path)
        if not path.exists():
            raise HTTPException(404, "הקובץ לא נמצא בדיסק")
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)])
            else:
                subprocess.run(["xdg-open", str(path.parent)])
            return {"revealed": True}
        except Exception as exc:
            raise HTTPException(500, f"פעולה נכשלה: {exc}")

    # ---- ייצוא ----
    @app.get("/api/export/document/{file_id}")
    def export_document(file_id: int):
        doc = search_service.get_document_text(file_id)
        if doc is None:
            raise HTTPException(404, "המסמך לא נמצא")
        content = f"# {doc['name']}\n# {doc['path']}\n\n{doc['full_text']}"
        return _text_download(content, f"{Path(doc['name']).stem}.txt")

    @app.post("/api/export/results")
    def export_results(req: ExportResultsRequest):
        from . import highlight as hl

        lines: List[str] = [f"תוצאות חיפוש: {req.query}", "=" * 60, ""]
        for fid in req.file_ids:
            doc = search_service.get_document_text(fid)
            if doc is None:
                continue
            lines.append(f"■ {doc['name']}")
            lines.append(f"  {doc['path']}")
            if req.include_full_text:
                lines.append("")
                lines.append(doc["full_text"])
            elif req.query:
                segs = [(s["page"], s["char_start"], s["char_end"]) for s in catalog.get_segments(fid)]
                occ = search_service._occurrence_spans(doc["full_text"], req.query, False)
                matches, _ = hl.build_matches_from_spans(
                    doc["full_text"], segs, occ,
                    window_words=search_service.get_setting_int("snippet_words", 50),
                    max_matches=10,
                )
                for m in matches:
                    page = f" (עמוד {m.page})" if m.page else ""
                    lines.append(f"   … {m.snippet}{page}")
            lines.append("")
            lines.append("-" * 60)
            lines.append("")
        return _text_download("\n".join(lines), "search_results.txt")

    # ---- ספרייה: עץ, ספרים, מפרשים ----
    @app.get("/api/tree")
    def tree() -> dict:
        return {"tree": library.build_tree()}

    @app.get("/api/book/text")
    def book_text(path: str, chunk: int = 0) -> dict:
        doc = library.get_book_chunk(path, chunk)
        if doc is None:
            raise HTTPException(404, "הספר לא נמצא")
        return doc

    @app.get("/api/book/toc")
    def book_toc(path: str) -> dict:
        res = library.get_book_toc(path)
        if res is None:
            raise HTTPException(404, "הספר לא נמצא")
        return res

    @app.post("/api/book/search")
    def book_search(req: BookSearchRequest) -> dict:
        from . import matching

        opts = matching.MatchOptions(
            exact=req.exact,
            whole_word=req.whole_word,
            fold_vy=req.fold_vy,
            fold_aa=req.fold_aa,
            proximity=0,
        )
        res = library.search_in_book(req.path, req.q, opts=opts)
        if res is None:
            raise HTTPException(404, "הספר לא נמצא")
        return res

    @app.post("/api/book/sync-position")
    def book_sync_position(req: SyncPositionRequest) -> dict:
        return library.sync_position(
            req.text_path, req.pdf_path, req.direction, offset=req.offset, page=req.page
        )

    @app.get("/api/mefarshim")
    def mefarshim(folder: str) -> dict:
        return {"books": library.list_mefarshim(folder)}

    @app.get("/api/file")
    def serve_file(path: str):
        """מגיש קובץ מקומי (PDF/תמונה) לתצוגה מוטמעת. מוגבל לתיקיות המקור."""
        p = Path(path)
        if not p.exists() or not p.is_file():
            raise HTTPException(404, "הקובץ לא נמצא")
        roots = catalog.list_roots()
        resolved = str(p.resolve()).lower()
        if not any(resolved.startswith(str(Path(r).resolve()).lower()) for r in roots):
            raise HTTPException(403, "הקובץ מחוץ לתיקיות המקור")
        media = "application/pdf" if p.suffix.lower() == ".pdf" else None
        return FileResponse(str(p), media_type=media, filename=p.name)

    # ---- חילוץ חכם ----
    @app.post("/api/extract/pdf-smart")
    def extract_pdf_smart(req: SmartExtractRequest) -> dict:
        from .extractors import pdf_smart

        p = Path(req.path)
        if not p.exists():
            raise HTTPException(404, "הקובץ לא נמצא")
        try:
            text = pdf_smart.extract_smart(p)
        except Exception as exc:
            log.warning("חילוץ חכם נכשל עבור %s: %s", p, exc)
            raise HTTPException(500, f"החילוץ נכשל: {exc}")
        log.info("חילוץ חכם: %s (%d תווים)", p.name, len(text))
        return {"path": req.path, "name": p.stem, "text": text}

    @app.post("/api/ocr/region")
    def ocr_region(req: RegionOcrRequest) -> dict:
        from .extractors import ocr

        p = Path(req.path)
        if not p.exists():
            raise HTTPException(404, "הקובץ לא נמצא")
        if not ocr.available():
            raise HTTPException(503, "OCR אינו זמין")
        text = ocr.ocr_image_region(p, req.x, req.y, req.w, req.h)
        log.info("OCR אזורי: %s -> %d תווים", p.name, len(text))
        return {"text": text}

    # ---- מנועי OCR ----
    @app.get("/api/ocr/engines")
    def ocr_engines_list() -> dict:
        from .extractors import ocr_engines

        return {"engines": ocr_engines.describe_engines()}

    @app.post("/api/ocr/rerun")
    def ocr_rerun() -> dict:
        """מחזיר לתור ה-OCR את כל הקבצים שעברו OCR - לאחר שינוי מנוע/הגדרות."""
        n = catalog.mark_ocr_rerun()
        indexer.ocr_status["pending"] = catalog.count_pending_ocr()
        log.info("הרצת OCR מחדש: %d קבצים הוחזרו לתור", n)
        return {"queued": n}

    # ---- התקנת מנוע Surya ----
    @app.get("/api/ocr/surya/status")
    def surya_status() -> dict:
        from .extractors.ocr_engines import surya_install

        return surya_install.get_status()

    @app.post("/api/ocr/surya/install")
    def surya_install_start() -> dict:
        from .extractors.ocr_engines import surya_install

        started = surya_install.start_install()
        if not started:
            raise HTTPException(409, "התקנה כבר רצה")
        return {"started": True}

    @app.post("/api/ocr/surya/vulkan")
    def surya_vulkan_install() -> dict:
        """הורדת בניית Vulkan - להאצה ניסיונית על GPU משולב."""
        from .extractors.ocr_engines import surya_install

        if surya_install.has_vulkan_build():
            return {"started": False, "installed": True}
        started = surya_install.start_install_vulkan()
        if not started:
            raise HTTPException(409, "פעולה אחרת כבר רצה")
        return {"started": True}

    # ---- ייצוא/ייבוא נתוני התוכנה (העברה בין מחשבים / אופליין) ----
    @app.get("/api/transfer/components")
    def transfer_components() -> dict:
        from . import transfer

        return {"components": transfer.available_components()}

    @app.post("/api/transfer/export")
    def transfer_export(req: TransferRequest) -> dict:
        from . import transfer

        res = transfer.start_export(req.path, req.components)
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res

    @app.post("/api/transfer/inspect")
    def transfer_inspect(req: TransferRequest) -> dict:
        from . import transfer

        res = transfer.inspect_bundle(req.path)
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res

    @app.post("/api/transfer/import")
    def transfer_import(req: TransferRequest) -> dict:
        from . import transfer

        res = transfer.start_import(req.path, req.components)
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res

    @app.get("/api/transfer/status")
    def transfer_status() -> dict:
        from . import transfer

        return transfer.get_status()

    @app.delete("/api/ocr/surya")
    def surya_uninstall() -> dict:
        from .extractors import ocr_engines
        from .extractors.ocr_engines import surya_install

        surya_install.uninstall()
        ocr_engines.invalidate()
        # אם Surya היה המנוע הנבחר - חוזרים ל-Tesseract
        if catalog.get_setting("ocr_engine") == "surya":
            catalog.set_setting("ocr_engine", "tesseract")
        if catalog.get_setting("ocr_region_engine") == "surya":
            catalog.set_setting("ocr_region_engine", "tesseract")
        log.info("מנוע Surya הוסר")
        return {"ok": True}

    # ---- אימון מודל לפי גופן ----
    @app.get("/api/training/check")
    def training_check() -> dict:
        from .training import font_trainer

        return font_trainer.check_environment()

    @app.get("/api/training/fonts")
    def training_fonts() -> dict:
        from .training import font_trainer

        return {"fonts": font_trainer.list_hebrew_fonts()}

    @app.post("/api/training/start")
    def training_start(req: TrainingRequest) -> dict:
        from .training import font_trainer

        res = font_trainer.start_training(
            font_paths=req.font_paths,
            model_name=req.name,
            noise_level=req.noise,
            num_lines=req.lines,
            iterations=req.iterations,
        )
        if "error" in res:
            raise HTTPException(409, res["error"])
        return res

    @app.get("/api/training/status")
    def training_status() -> dict:
        from .training import font_trainer

        return font_trainer.get_status()

    @app.post("/api/training/cancel")
    def training_cancel() -> dict:
        from .training import font_trainer

        font_trainer.cancel()
        return {"ok": True}

    @app.get("/api/training/models")
    def training_models() -> dict:
        from .training import font_trainer

        return {"models": font_trainer.list_models()}

    @app.delete("/api/training/models/{name}")
    def training_delete_model(name: str) -> dict:
        from .extractors import ocr_engines
        from .training import font_trainer

        ok = font_trainer.delete_model(name)
        if not ok:
            raise HTTPException(404, "המודל לא נמצא")
        # אם המודל שנמחק היה בשימוש - חוזרים למודל המובנה
        if catalog.get_setting("ocr_traineddata") == name:
            catalog.set_setting("ocr_traineddata", "")
        ocr_engines.invalidate()
        return {"ok": True}

    # ---- הגדרות ----
    @app.get("/api/settings")
    def get_settings() -> dict:
        from .extractors.ocr_engines import ocr_settings

        defaults = {
            "font_size": "30",          # גודל גופן לטקסט מוצג (דרישת לקוח)
            "result_font_size": "25",   # גודל גופן לתוצאות חיפוש (דרישת לקוח)
            "font_family": "FrankRuehl",
            "result_limit": "0",        # 0 = ללא הגבלה
            "snippet_words": "50",
            "at_default": "text",       # text / pdf
            "proximity_words": "30",    # מרחק מרבי בין מילים בחיפוש לא-מדויק
        }
        defaults.update(ocr_settings.DEFAULTS)
        stored = catalog.all_settings()
        defaults.update(stored)
        return {"settings": defaults}

    @app.put("/api/settings")
    def put_settings(req: SettingsRequest) -> dict:
        from .extractors import ocr_engines

        for k, v in req.values.items():
            catalog.set_setting(k, str(v))
        if any(k.startswith("ocr_") for k in req.values):
            ocr_engines.invalidate()
        log.info("הגדרות עודכנו: %s", list(req.values.keys()))
        return {"ok": True}

    @app.get("/api/fonts")
    def fonts() -> dict:
        return {"fonts": _installed_fonts()}

    # ---- לוח העתקה (נרשם גם בהיסטוריית Windows+V) ----
    @app.post("/api/clipboard")
    def set_clipboard(req: ClipboardRequest) -> dict:
        if not _copy_to_clipboard(req.text):
            raise HTTPException(500, "ההעתקה ללוח נכשלה")
        return {"ok": True}

    # ---- שמירת טקסט לקובץ (TXT / WORD) בנתיב שנבחר בדיאלוג ----
    @app.post("/api/export/text-file")
    def export_text_file(req: SaveTextFileRequest) -> dict:
        target = Path(req.path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if req.format == "docx" or target.suffix.lower() == ".docx":
                _write_docx(target, req.text)
            else:
                if not target.suffix:
                    target = target.with_suffix(".txt")
                target.write_text(req.text, encoding="utf-8-sig")
            log.info("טקסט נשמר לקובץ: %s", target)
            return {"ok": True, "path": str(target)}
        except Exception as exc:
            log.warning("שמירת קובץ נכשלה: %s", exc)
            raise HTTPException(500, f"השמירה נכשלה: {exc}")

    # ---- סימניות ----
    @app.get("/api/bookmarks")
    def bookmarks() -> dict:
        return {"bookmarks": catalog.list_bookmarks()}

    @app.post("/api/bookmarks")
    def add_bookmark(req: BookmarkRequest) -> dict:
        bid = catalog.add_bookmark(req.book_path, req.book_name, req.view, req.position, req.label)
        return {"id": bid}

    @app.delete("/api/bookmarks/{bookmark_id}")
    def delete_bookmark(bookmark_id: int) -> dict:
        catalog.delete_bookmark(bookmark_id)
        return {"ok": True}

    @app.post("/api/bookmarks/delete")
    def delete_bookmarks_bulk(req: BookmarksDeleteRequest) -> dict:
        catalog.delete_bookmarks(req.ids)
        return {"ok": True, "deleted": len(req.ids)}

    # ---- לוגים לאבחון ----
    @app.get("/api/logs")
    def logs(after: int = 0, level: str = "ALL") -> dict:
        return {"records": ring_buffer.records(after_id=after, level=level)}

    @app.get("/api/errors")
    def errors() -> dict:
        return {"errors": catalog.list_errors()}

    # ---- הגשת ה-frontend ----
    _mount_frontend(app)

    return app


# ---- עזרי מערכת ----
def _installed_fonts() -> List[str]:
    """רשימת כל משפחות הגופנים המותקנות ב-Windows (HKLM + HKCU)."""
    names: set = set()
    if sys.platform != "win32":
        return []
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name, _, _ = winreg.EnumValue(key, i)
                    i += 1
                except OSError:
                    break
                # "David (TrueType)" -> "David"
                clean = name.split("(")[0].strip()
                # הסרת סגנונות משם המשפחה
                for style in (
                    " Bold Italic", " Bold", " Italic", " Light", " Medium",
                    " SemiBold", " Semibold", " Black", " Thin", " ExtraLight",
                ):
                    if clean.endswith(style):
                        clean = clean[: -len(style)].strip()
                if clean:
                    names.add(clean)
            winreg.CloseKey(key)
    except Exception as exc:
        log.warning("קריאת גופנים נכשלה: %s", exc)
    return sorted(names)


def _bundled_fonts_dir() -> Path:
    """תיקיית הגופנים המצורפים (בתוך ה-frontend הבנוי)."""
    return settings.frontend_dir / "fonts"


def _install_bundled_fonts() -> None:
    """מתקין את הגופנים המצורפים למשתמש הנוכחי אם אינם מותקנים.

    התקנת-משתמש (ללא אדמין): העתקה ל-%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts,
    רישום ב-HKCU, טעינה עם AddFontResourceW ו-broadcast של WM_FONTCHANGE.
    """
    if sys.platform != "win32":
        return
    src_dir = _bundled_fonts_dir()
    if not src_dir.exists():
        return
    try:
        import ctypes
        import shutil
        import winreg

        installed = {f.lower() for f in _installed_fonts()}
        fonts_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)

        # (קובץ, שם רישום, משפחה לבדיקה-אם-כבר-קיימת)
        wanted = [
            ("FrankRuehlCLM-Bold.ttf", "Frank Ruehl CLM Bold (TrueType)", "frank ruehl clm"),
            ("FrankRuehlCLM-Medium.ttf", "Frank Ruehl CLM Medium (TrueType)", "frank ruehl clm"),
        ]
        changed = False
        for fname, regname, family in wanted:
            src = src_dir / fname
            if not src.exists():
                continue
            dst = fonts_dir / fname
            if not dst.exists():
                shutil.copy2(src, dst)
            key = winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
            )
            winreg.SetValueEx(key, regname, 0, winreg.REG_SZ, str(dst))
            winreg.CloseKey(key)
            ctypes.windll.gdi32.AddFontResourceW(str(dst))
            if family not in installed:
                changed = True
        if changed:
            HWND_BROADCAST, WM_FONTCHANGE = 0xFFFF, 0x001D
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_FONTCHANGE, 0, 0, 0x0002, 1000, None
            )
            log.info("הגופנים המצורפים הותקנו למשתמש")
    except Exception as exc:
        log.warning("התקנת הגופנים המצורפים נכשלה: %s", exc)


def _copy_to_clipboard(text: str) -> bool:
    """כתיבה ללוח Windows כ-CF_UNICODETEXT - נקלט בהיסטוריית Windows+V."""
    if sys.platform != "win32":
        return False
    import ctypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # חתימות מפורשות - בלעדיהן מצביעי 64-ביט נחתכים ל-int של 32-ביט
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    data = text.replace("\n", "\r\n")
    size = (len(data) + 1) * ctypes.sizeof(ctypes.c_wchar)
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, ctypes.create_unicode_buffer(data), size)
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


def _write_docx(target: Path, text: str) -> None:
    """שמירת טקסט כקובץ Word (docx) עם כיווניות RTL."""
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement

    doc = docx.Document()
    for line in text.splitlines() or [""]:
        p = doc.add_paragraph(line)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        try:
            pPr = p._p.get_or_add_pPr()
            pPr.append(OxmlElement("w:bidi"))
        except Exception:
            pass
    if not target.suffix:
        target = target.with_suffix(".docx")
    doc.save(str(target))


def _restart_watch_async() -> None:
    """מרענן את המעקב החי ברקע כדי לכלול את שינוי התיקיות."""
    import threading

    threading.Thread(target=watcher.restart, daemon=True).start()


def _open_with_default(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


def _text_download(content: str, filename: str) -> StreamingResponse:
    buf = io.BytesIO(content.encode("utf-8-sig"))
    return StreamingResponse(
        buf,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _ocr_available() -> bool:
    try:
        from .extractors import ocr

        return ocr.available()
    except Exception:
        return False


def _mount_frontend(app: FastAPI) -> None:
    dist = settings.frontend_dir
    if dist.exists() and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
        log.info("frontend מוגש מ: %s", dist)
    else:
        @app.get("/")
        def _placeholder() -> PlainTextResponse:
            return PlainTextResponse(
                "ה-frontend עדיין לא נבנה. הריצו: npm --prefix frontend run build",
                media_type="text/plain; charset=utf-8",
            )
        log.warning("frontend/dist לא נמצא - מוגש דף ממלא מקום")


app = create_app()
