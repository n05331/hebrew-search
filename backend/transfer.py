"""ייצוא וייבוא נתוני התוכנה - חבילה אחת עם בחירת רכיבים.

רכיבים: הגדרות, אינדקס (טקסטים מחולצים כולל OCR), מודלים מאומנים, ומנוע
Surya (להתקנת אופליין). הכל נארז ל-zip יחיד עם manifest, וביבוא בוחרים
אילו רכיבים להחיל.

האינדקס מיוצא כ-JSONL נייד (לא קובצי SQLite/Tantivy בינאריים) - עמיד
לשינויי גרסה ולנתיבים שונים: ביבוא, קובץ שקיים בדיסק נכנס לאינדקס מיד,
וקובץ שאינו קיים נשמר כרשומת 'cache' שמשמשת את מנגנון השימוש-החוזר
ב-OCR לפי תוכן (sha1) כשהקבצים יתווספו ממיקום אחר.

הפעולות רצות ב-thread רקע עם דיווח התקדמות ל-UI.
"""

from __future__ import annotations

import json
import threading
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from .catalog import Segment, catalog
from .config import settings
from .logging_setup import get_logger

log = get_logger("transfer")

BUNDLE_NAME = "HebrewSearch-Transfer.zip"
MANIFEST_NAME = "hebrewsearch-manifest.json"
COMPONENTS = ("settings", "index", "models", "surya")

# קבצים שלא נכללים ברכיב Surya (לוגים; מטמון נבנה מחדש)
_SKIP_SUFFIXES = (".log",)

status: Dict = {
    "running": False,
    "op": "",          # export / import
    "step": "",
    "detail": "",
    "percent": 0,
    "error": "",
    "result": None,
}
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def _set(step: str = None, detail: str = None, percent: int = None, error: str = None) -> None:
    with _lock:
        if step is not None:
            status["step"] = step
        if detail is not None:
            status["detail"] = detail
        if percent is not None:
            status["percent"] = percent
        if error is not None:
            status["error"] = error


def get_status() -> dict:
    with _lock:
        return dict(status)


# ---- עזרי רכיבים ----
def _settings_payload() -> dict:
    return {
        "settings": catalog.all_settings(),
        "roots": catalog.list_roots(),
    }


def _iter_index_rows():
    """רשומות האינדקס עם תוכן מלא ומיקומי עמודים."""
    rows = catalog.conn.execute(
        "SELECT * FROM files WHERE status='indexed' AND full_text IS NOT NULL"
    ).fetchall()
    for row in rows:
        segs = catalog.get_segments(row["id"])
        yield {
            "path": row["path"], "name": row["name"], "ext": row["ext"],
            "size": row["size"], "mtime": row["mtime"], "sha1": row["sha1"],
            "source": row["source"], "page_count": row["page_count"],
            "full_text": row["full_text"],
            "segments": [[s["page"], s["char_start"], s["char_end"]] for s in segs],
        }


def _surya_files() -> List[Path]:
    from .extractors.ocr_engines import surya_install

    src = surya_install.env_dir()
    if not src.exists():
        return []
    return [
        p for p in src.rglob("*")
        if p.is_file() and p.suffix.lower() not in _SKIP_SUFFIXES
    ]


def available_components() -> dict:
    """אילו רכיבים קיימים במחשב הזה לייצוא (+נתוני היקף)."""
    from .extractors.ocr_engines import surya_install
    from .extractors.ocr_engines.tesseract_engine import list_custom_models

    indexed = catalog.conn.execute(
        "SELECT COUNT(*) c FROM files WHERE status='indexed' AND full_text IS NOT NULL"
    ).fetchone()["c"]
    return {
        "settings": {"available": True},
        "index": {"available": indexed > 0, "count": indexed},
        "models": {"available": bool(list_custom_models()), "names": list_custom_models()},
        "surya": {"available": surya_install.is_installed(), "size_gb": 2.4},
    }


# ---- ייצוא ----
def _run_export(target_dir: Path, components: List[str]) -> None:
    from .extractors.ocr_engines import surya_install

    try:
        target = target_dir / BUNDLE_NAME
        _set(step="מכין ייצוא", detail="", percent=0, error="")
        manifest = {
            "app": "HebrewSearch",
            "format": 1,
            "created_at": time.time(),
            "components": {},
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
            if "settings" in components:
                _set(step="ייצוא הגדרות", percent=2)
                z.writestr("settings.json", json.dumps(_settings_payload(), ensure_ascii=False))
                manifest["components"]["settings"] = True

            if "index" in components:
                _set(step="ייצוא אינדקס", percent=5)
                count = 0
                with z.open("index.jsonl", "w") as f:
                    for rec in _iter_index_rows():
                        f.write((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
                        count += 1
                        if count % 100 == 0:
                            _set(detail=f"{count} קבצים", percent=min(30, 5 + count // 100))
                manifest["components"]["index"] = {"count": count}

            if "models" in components:
                _set(step="ייצוא מודלים מאומנים", percent=32)
                from .extractors.ocr_engines.tesseract_engine import custom_tessdata_dir

                names = []
                d = custom_tessdata_dir()
                if d.exists():
                    for p in sorted(d.glob("*.traineddata")):
                        z.write(p, f"tessdata_custom/{p.name}")
                        names.append(p.stem)
                manifest["components"]["models"] = {"names": names}

            if "surya" in components:
                # ללא דחיסה - המודלים כבר דחוסים ו-ZIP_STORED מהיר פי כמה
                files = _surya_files()
                if not files:
                    raise RuntimeError("מנוע Surya אינו מותקן - אין מה לייצא")
                src = surya_install.env_dir()
                total = len(files)
                _set(step="ייצוא מנוע Surya", percent=35)
                for i, p in enumerate(files):
                    z.write(
                        p, "surya/" + p.relative_to(src).as_posix(),
                        compress_type=zipfile.ZIP_STORED,
                    )
                    if (i + 1) % 100 == 0 or i + 1 == total:
                        _set(
                            detail=f"{i + 1}/{total} קבצים",
                            percent=35 + int(60 * (i + 1) / total),
                        )
                manifest["components"]["surya"] = True

            z.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False))

        with _lock:
            status["result"] = {"target": str(target)}
        _set(step="הייצוא הושלם", detail=str(target), percent=100)
        log.info("ייצוא הושלם: %s (רכיבים: %s)", target, components)
    except Exception as exc:
        log.exception("ייצוא נכשל: %s", exc)
        _set(step="שגיאה", error=str(exc))
    finally:
        with _lock:
            status["running"] = False


# ---- ייבוא ----
def inspect_bundle(zip_path: str) -> dict:
    """קורא את ה-manifest של חבילה - לתצוגת בחירת רכיבים לפני ייבוא."""
    p = Path(zip_path)
    if not p.is_file():
        return {"error": "קובץ החבילה לא נמצא"}
    try:
        with zipfile.ZipFile(p) as z:
            if MANIFEST_NAME not in z.namelist():
                return {"error": "הקובץ אינו חבילת ייצוא של התוכנה"}
            manifest = json.loads(z.read(MANIFEST_NAME).decode("utf-8"))
            return {"manifest": manifest}
    except zipfile.BadZipFile:
        return {"error": "הקובץ אינו קובץ zip תקין"}
    except Exception as exc:
        return {"error": str(exc)}


def _import_settings(z: zipfile.ZipFile) -> None:
    data = json.loads(z.read("settings.json").decode("utf-8"))
    for k, v in (data.get("settings") or {}).items():
        catalog.set_setting(k, str(v))
    # תיקיות מקור: מוסיפים רק נתיבים שקיימים במחשב הזה
    for root in data.get("roots") or []:
        if Path(root).exists():
            catalog.add_root(root)
    from .extractors import ocr_engines

    ocr_engines.invalidate()


def _import_index(z: zipfile.ZipFile) -> dict:
    from .search_engine import engine

    imported = cached = 0
    with z.open("index.jsonl") as f:
        for i, raw in enumerate(f):
            try:
                rec = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            segments = [
                Segment(page=s[0], char_start=s[1], char_end=s[2])
                for s in rec.get("segments") or []
            ]
            exists = False
            try:
                exists = Path(rec["path"]).exists()
            except Exception:
                pass
            file_id = catalog.import_content_row(
                path=rec["path"], name=rec.get("name") or "", ext=rec.get("ext") or "",
                size=rec.get("size") or 0, mtime=rec.get("mtime") or 0,
                sha1=rec.get("sha1") or "", full_text=rec.get("full_text") or "",
                segments=segments, source=rec.get("source") or "extracted",
                page_count=rec.get("page_count") or 0,
                status="indexed" if exists else "cache",
            )
            if exists:
                engine.add_document(
                    file_id=file_id, path=rec["path"], name=rec.get("name") or "",
                    ext=rec.get("ext") or "", mtime=int(rec.get("mtime") or 0),
                    content=rec.get("full_text") or "",
                )
                imported += 1
            else:
                cached += 1
            if (i + 1) % 100 == 0:
                _set(detail=f"{i + 1} רשומות", percent=min(60, 10 + (i + 1) // 100))
                engine.commit()
    engine.commit()
    return {"indexed": imported, "cached": cached}


def _import_models(z: zipfile.ZipFile) -> List[str]:
    from .extractors.ocr_engines.tesseract_engine import custom_tessdata_dir

    d = custom_tessdata_dir()
    d.mkdir(parents=True, exist_ok=True)
    names = []
    for name in z.namelist():
        if name.startswith("tessdata_custom/") and name.endswith(".traineddata"):
            fname = Path(name).name
            (d / fname).write_bytes(z.read(name))
            names.append(Path(fname).stem)
    return names


def _import_surya(z: zipfile.ZipFile) -> None:
    from .extractors.ocr_engines import surya_install

    names = [n for n in z.namelist() if n.startswith("surya/") and not n.endswith("/")]
    if not names:
        raise RuntimeError("החבילה אינה כוללת את מנוע Surya")
    dest = surya_install.env_dir()
    dest.mkdir(parents=True, exist_ok=True)
    total = len(names)
    for i, name in enumerate(names):
        rel = name[len("surya/"):]
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(name) as src, target.open("wb") as out:
            while True:
                chunk = src.read(1024 * 512)
                if not chunk:
                    break
                out.write(chunk)
        if (i + 1) % 100 == 0 or i + 1 == total:
            _set(detail=f"{i + 1}/{total} קבצים", percent=60 + int(38 * (i + 1) / total))
    if not surya_install.is_installed():
        raise RuntimeError("ייבוא Surya הסתיים אך ההתקנה אינה שלמה (קבצים חסרים)")


def _run_import(zip_path: Path, components: List[str]) -> None:
    try:
        _set(step="פותח חבילה", detail="", percent=0, error="")
        result = {}
        with zipfile.ZipFile(zip_path) as z:
            names = set(z.namelist())
            if MANIFEST_NAME not in names:
                raise RuntimeError("הקובץ אינו חבילת ייצוא של התוכנה")

            if "settings" in components and "settings.json" in names:
                _set(step="ייבוא הגדרות", percent=5)
                _import_settings(z)
                result["settings"] = True

            if "index" in components and "index.jsonl" in names:
                _set(step="ייבוא אינדקס", percent=10)
                result["index"] = _import_index(z)

            if "models" in components:
                _set(step="ייבוא מודלים מאומנים", percent=58)
                result["models"] = _import_models(z)

            if "surya" in components:
                _set(step="ייבוא מנוע Surya", percent=60)
                _import_surya(z)
                result["surya"] = True

        with _lock:
            status["result"] = result
        _set(step="הייבוא הושלם", detail="", percent=100)
        log.info("ייבוא הושלם מ-%s: %s", zip_path, result)
    except Exception as exc:
        log.exception("ייבוא נכשל: %s", exc)
        _set(step="שגיאה", error=str(exc))
    finally:
        with _lock:
            status["running"] = False


# ---- הפעלה ----
def _start(op: str, target, components: List[str]) -> dict:
    global _thread
    comps = [c for c in components if c in COMPONENTS]
    if not comps:
        return {"error": "לא נבחרו רכיבים"}
    with _lock:
        if status["running"]:
            return {"error": "פעולה אחרת כבר רצה"}
        status.update({"running": True, "op": op, "step": "", "detail": "",
                       "percent": 0, "error": "", "result": None})
    fn = _run_export if op == "export" else _run_import
    _thread = threading.Thread(target=fn, args=(target, comps), daemon=True)
    _thread.start()
    return {"started": True}


def start_export(target_dir: str, components: List[str]) -> dict:
    d = Path(target_dir)
    if not d.is_dir():
        return {"error": "תיקיית היעד אינה קיימת"}
    return _start("export", d, components)


def start_import(zip_path: str, components: List[str]) -> dict:
    p = Path(zip_path)
    if not p.is_file():
        return {"error": "קובץ החבילה לא נמצא"}
    return _start("import", p, components)
