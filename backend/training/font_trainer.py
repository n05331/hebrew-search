"""אשף אימון מודל Tesseract לפי גופן - צינור מלא ואוטומטי.

השלבים (רצים ב-thread רקע עם דיווח התקדמות):
1. רינדור שורות אימון ב-Pillow עם הגופן הנבחר + הרעשה (רעש, סיבוב, טשטוש).
   בלי ``text2image`` - הכלי ידוע כשביר על Windows, ורינדור עצמי נותן
   שליטה מלאה בכיווניות (python-bidi) ובעיוותים.
2. יצירת קובצי ‎.lstmf עם tesseract.exe הארוז (config של lstm.train).
3. חילוץ ה-LSTM ממודל הבסיס העברי (float) ו-fine-tuning עם lstmtraining.
4. אריזת המודל (--stop_training) והעתקה ל-tessdata_custom - זמין מיד
   לבחירה בהגדרות ה-OCR.
5. אימות עצמי: זיהוי שורות ביקורת עם המודל החדש והשוואה למודל הבסיס.

העבודה נעשית בתיקייה זמנית בנתיב ASCII (short path) - כלי Tesseract אינם
מתמודדים עם נתיבים בעברית.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..config import settings
from ..extractors.ocr_engines.tesseract_engine import (
    custom_tessdata_dir,
    find_tesseract,
    short_path,
)
from ..logging_setup import get_logger
from . import corpus
from .hebrew_fonts import list_hebrew_fonts

log = get_logger("training")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# ---- סטטוס משותף ל-API ----
status: Dict = {
    "running": False,
    "step": "",
    "detail": "",
    "percent": 0,
    "error": "",
    "result": None,   # בסיום: {name, base_score, new_score, iterations}
}
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_cancel = threading.Event()

# תוכן הקונפיג lstm.train של Tesseract - נכתב לקובץ בזמן ריצה, כי תיקיית
# ה-tessdata שלנו אינה כוללת configs/ (הקונפיג נטען לפי נתיב מלא)
_LSTM_TRAIN_CONFIG = """file_type .bl
textord_fast_pitch_test T
tessedit_zero_rejection T
tessedit_minimal_rejection F
tessedit_write_rep_codes F
edges_children_fix F
edges_childarea 0.65
edges_boxarea 0.9
tessedit_train_line_recognizer T
textord_no_rejects T
tessedit_init_config_only T
"""

# רמות הרעשה: (סיכוי רעש, עוצמת רעש, טשטוש מרבי, סיבוב מרבי במעלות)
_NOISE_LEVELS = {
    "low": (0.4, 12, 0.6, 0.5),
    "medium": (0.7, 22, 1.0, 1.0),
    "high": (0.9, 34, 1.4, 1.8),
}


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


def is_running() -> bool:
    with _lock:
        return bool(status["running"])


def cancel() -> None:
    _cancel.set()


# ---- איתור כלי האימון ----
def _tools_dir() -> Optional[Path]:
    """תיקיית כלי האימון - ליד tesseract.exe (ארוז או מותקן)."""
    cmd = find_tesseract()
    if not cmd:
        return None
    d = Path(cmd).parent
    if (d / "lstmtraining.exe").exists() and (d / "combine_tessdata.exe").exists():
        return d
    return None


def check_environment() -> Dict:
    """בדיקת תקינות סביבת האימון - לפני שהאשף מציג את הטופס."""
    problems = []
    tools = _tools_dir()
    if tools is None:
        problems.append("כלי האימון (lstmtraining, combine_tessdata) לא נמצאו ליד Tesseract")
    base = settings.tessdata_dir / "heb.traineddata"
    if not base.exists():
        problems.append("מודל הבסיס heb.traineddata לא נמצא")
    try:
        import bidi  # noqa: F401
    except ImportError:
        problems.append("החבילה python-bidi חסרה")
    return {"ok": not problems, "problems": problems, "tools_dir": str(tools) if tools else ""}


# ---- רינדור שורות אימון ----
def _render_line(text: str, font, noise_level: str, rng: random.Random):
    """מרנדר שורת טקסט עברי לתמונת אימון עם הרעשה אקראית."""
    from bidi.algorithm import get_display
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    noise_p, noise_sigma, blur_max, rot_max = _NOISE_LEVELS.get(noise_level, _NOISE_LEVELS["medium"])

    visual = get_display(text)
    # מדידת הטקסט
    probe = Image.new("L", (10, 10), 255)
    d = ImageDraw.Draw(probe)
    box = d.textbbox((0, 0), visual, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = 24, 16
    img = Image.new("L", (tw + pad_x * 2, th + pad_y * 2), 255)
    d = ImageDraw.Draw(img)
    d.text((pad_x - box[0], pad_y - box[1]), visual, font=font, fill=0)

    # סיבוב קל (סריקות עקומות)
    angle = rng.uniform(-rot_max, rot_max)
    if abs(angle) > 0.05:
        img = img.rotate(angle, expand=True, fillcolor=255, resample=Image.BICUBIC)

    # רעש גרעיני (נייר/סורק)
    if rng.random() < noise_p:
        noise = Image.effect_noise(img.size, rng.uniform(noise_sigma * 0.6, noise_sigma))
        img = ImageChops.darker(img, ImageChops.lighter(noise, Image.new("L", img.size, 140)))

    # טשטוש עדין (מיקוד לא מושלם)
    r = rng.uniform(0, blur_max)
    if r > 0.2:
        img = img.filter(ImageFilter.GaussianBlur(radius=r))

    return img.convert("L")


def _write_box(box_path: Path, text: str, w: int, h: int) -> None:
    """קובץ box בפורמט WordStr לשורה שלמה (המוסכמה של tesstrain)."""
    content = f"WordStr 0 0 {w} {h} 0 #{text}\n\t 0 0 {w} {h} 0\n"
    box_path.write_text(content, encoding="utf-8", newline="\n")


def _run(cmd: List[str], log_file: Path, label: str, timeout: int = 7200,
         on_line=None) -> int:
    """מריץ כלי חיצוני; הפלט נכתב ללוג ואופציונלית מפוענח שורה-שורה."""
    with log_file.open("a", encoding="utf-8", errors="replace") as lf:
        lf.write(f"\n===== {label}: {' '.join(cmd)}\n")
        lf.flush()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=_CREATE_NO_WINDOW,
        )
        start = time.time()
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace")
            lf.write(line)
            if on_line:
                try:
                    on_line(line)
                except Exception:
                    pass
            if _cancel.is_set():
                proc.kill()
                return -9
            if time.time() - start > timeout:
                proc.kill()
                return -15
        proc.wait()
        return proc.returncode


def _ocr_with_model(image_paths: List[Path], tessdata_dir: Path, lang: str) -> List[str]:
    """זיהוי רשימת תמונות עם מודל נתון - לאימות עצמי."""
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = find_tesseract()
    out = []
    config = f"--tessdata-dir {short_path(str(tessdata_dir))} --psm 7"
    for p in image_paths:
        from PIL import Image

        try:
            with Image.open(p) as img:
                out.append(pytesseract.image_to_string(img, lang=lang, config=config))
        except Exception:
            out.append("")
    return out


def _score(texts: List[str], truths: List[str]) -> float:
    """אחוז המילים מהאמת שזוהו (מדד פשוט וברור למשתמש)."""
    total = hit = 0
    for text, truth in zip(texts, truths):
        words = truth.split()
        total += len(words)
        hit += sum(1 for w in words if w in text)
    return round(100.0 * hit / total, 1) if total else 0.0


def _sanitize_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_\-]", "_", name.strip())[:40].strip("_")
    return clean or "custom"


# ---- הצינור המלא ----
def _run_training(font_paths: List[str], model_name: str, noise_level: str,
                  num_lines: int, iterations: int) -> None:
    from PIL import ImageFont

    started = time.time()
    work = Path(tempfile.mkdtemp(prefix="hstrain_", dir=short_path(tempfile.gettempdir())))
    log_file = settings.log_dir / "training.log"
    try:
        env_check = check_environment()
        if not env_check["ok"]:
            raise RuntimeError("; ".join(env_check["problems"]))
        tools = Path(env_check["tools_dir"])
        tesseract_exe = find_tesseract()

        base_traineddata = settings.tessdata_dir / "heb.traineddata"
        # עותק בנתיב ASCII
        base_copy = work / "heb.traineddata"
        shutil.copy2(base_traineddata, base_copy)

        rng = random.Random(1234)
        lines = corpus.make_lines(num_lines, seed=1234)
        # שורות ביקורת נפרדות (לא משתתפות באימון)
        val_lines = corpus.make_lines(24, seed=987, min_words=4, max_words=7)

        fonts = []
        for fp in font_paths:
            try:
                fonts.append(ImageFont.truetype(fp, 48))
            except Exception as exc:
                raise RuntimeError(f"טעינת הגופן {Path(fp).name} נכשלה: {exc}")

        # 1. רינדור
        from bidi.algorithm import get_display

        gt_dir = work / "gt"
        gt_dir.mkdir()
        _set(step="יצירת שורות אימון", percent=2, error="")
        for i, line in enumerate(lines):
            if _cancel.is_set():
                raise RuntimeError("בוטל על ידי המשתמש")
            font = fonts[i % len(fonts)]
            img = _render_line(line, font, noise_level, rng)
            stem = gt_dir / f"line_{i:05d}"
            img.save(str(stem) + ".tif", format="TIFF", compression="tiff_deflate")
            Path(str(stem) + ".gt.txt").write_text(line + "\n", encoding="utf-8", newline="\n")
            # אמת-הקרקע בסדר חזותי (שמאל-לימין): ה-LSTM של Tesseract סורק את
            # השורה חזותית ופולט בסדר הזה; היפוך ה-bidi ללוגי קורה אחר כך.
            _write_box(Path(str(stem) + ".box"), get_display(line), img.width, img.height)
            if (i + 1) % 50 == 0:
                _set(detail=f"{i + 1}/{len(lines)} שורות", percent=2 + int(18 * (i + 1) / len(lines)))

        # שורות ביקורת (רינדור נקי יותר - בלי הרעשה כבדה)
        val_dir = work / "val"
        val_dir.mkdir()
        for i, line in enumerate(val_lines):
            font = fonts[i % len(fonts)]
            img = _render_line(line, font, "low", rng)
            img.save(str(val_dir / f"val_{i:03d}.tif"), format="TIFF")

        # 2. יצירת lstmf
        _set(step="הכנת נתוני אימון (lstmf)", percent=20)
        train_config = work / "lstm.train"
        train_config.write_text(_LSTM_TRAIN_CONFIG, encoding="ascii")
        lstmf_files: List[str] = []
        tifs = sorted(gt_dir.glob("*.tif"))
        for i, tif in enumerate(tifs):
            if _cancel.is_set():
                raise RuntimeError("בוטל על ידי המשתמש")
            stem = tif.with_suffix("")
            rc = _run(
                [tesseract_exe, str(tif), str(stem), "--psm", "13",
                 "--tessdata-dir", short_path(str(settings.tessdata_dir)),
                 "-l", "heb", str(train_config)],
                log_file, f"lstmf {tif.name}", timeout=120,
            )
            lstmf = stem.with_suffix(".lstmf")
            if rc == 0 and lstmf.exists():
                lstmf_files.append(str(lstmf))
            if (i + 1) % 50 == 0:
                _set(detail=f"{i + 1}/{len(tifs)}", percent=20 + int(20 * (i + 1) / len(tifs)))
        if len(lstmf_files) < max(20, len(tifs) // 2):
            raise RuntimeError(
                f"נוצרו רק {len(lstmf_files)} קובצי אימון מתוך {len(tifs)} - ראו {log_file}"
            )

        rng.shuffle(lstmf_files)
        split = max(1, len(lstmf_files) // 10)
        eval_list, train_list = lstmf_files[:split], lstmf_files[split:]
        # LF בלבד: lstmtraining קורא שמות קבצים כולל \r ונכשל בפתיחתם
        (work / "train.txt").write_text("\n".join(train_list) + "\n", encoding="utf-8", newline="\n")
        (work / "eval.txt").write_text("\n".join(eval_list) + "\n", encoding="utf-8", newline="\n")

        # 3. חילוץ LSTM הבסיס ו-fine-tuning
        _set(step="חילוץ מודל הבסיס", percent=40, detail="")
        rc = _run(
            [str(tools / "combine_tessdata.exe"), "-e", str(base_copy), str(work / "heb.lstm")],
            log_file, "חילוץ lstm", timeout=120,
        )
        if rc != 0 or not (work / "heb.lstm").exists():
            raise RuntimeError(f"חילוץ ה-LSTM ממודל הבסיס נכשל - ראו {log_file}")

        _set(step="אימון המודל", percent=42)
        ckpt_prefix = work / "out" / "model"
        ckpt_prefix.parent.mkdir()
        iter_re = re.compile(r"At iteration (\d+)/(\d+)/")
        err_re = re.compile(r"BCER train=([\d.]+)%")
        last = {"iter": 0, "err": None}

        def on_line(line: str) -> None:
            m = iter_re.search(line)
            if m:
                last["iter"] = int(m.group(2))
                pct = 42 + int(48 * min(1.0, last["iter"] / max(1, iterations)))
                m2 = err_re.search(line)
                if m2:
                    last["err"] = m2.group(1)
                detail = f"איטרציה {last['iter']}/{iterations}"
                if last["err"]:
                    detail += f", שגיאת תווים {last['err']}%"
                _set(detail=detail, percent=pct)

        rc = _run(
            [str(tools / "lstmtraining.exe"),
             "--model_output", str(ckpt_prefix),
             "--continue_from", str(work / "heb.lstm"),
             "--traineddata", str(base_copy),
             "--train_listfile", str(work / "train.txt"),
             "--eval_listfile", str(work / "eval.txt"),
             "--max_iterations", str(iterations),
             "--target_error_rate", "0.5",
             "--debug_interval", "0"],
            log_file, "lstmtraining", timeout=6 * 3600, on_line=on_line,
        )
        if rc == -9:
            raise RuntimeError("בוטל על ידי המשתמש")
        checkpoint = Path(str(ckpt_prefix) + "_checkpoint")
        if not checkpoint.exists():
            raise RuntimeError(f"האימון לא הפיק checkpoint (קוד {rc}) - ראו {log_file}")

        # 4. אריזת traineddata סופי
        _set(step="אריזת המודל", percent=92, detail="")
        final = work / f"{model_name}.traineddata"
        rc = _run(
            [str(tools / "lstmtraining.exe"), "--stop_training",
             "--continue_from", str(checkpoint),
             "--traineddata", str(base_copy),
             "--model_output", str(final)],
            log_file, "stop_training", timeout=600,
        )
        if rc != 0 or not final.exists():
            raise RuntimeError(f"אריזת המודל נכשלה (קוד {rc}) - ראו {log_file}")

        # 5. אימות עצמי: המודל החדש מול הבסיס על שורות הביקורת
        _set(step="אימות המודל", percent=94)
        val_tifs = sorted(val_dir.glob("*.tif"))
        vd = work / "valdata"
        vd.mkdir()
        shutil.copy2(final, vd / f"{model_name}.traineddata")
        shutil.copy2(base_copy, vd / "heb.traineddata")
        new_texts = _ocr_with_model(val_tifs, vd, model_name)
        base_texts = _ocr_with_model(val_tifs, vd, "heb")
        new_score = _score(new_texts, val_lines)
        base_score = _score(base_texts, val_lines)

        # התקנה ל-tessdata_custom
        dest_dir = custom_tessdata_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final, dest_dir / f"{model_name}.traineddata")

        with _lock:
            status["result"] = {
                "name": model_name,
                "base_score": base_score,
                "new_score": new_score,
                "iterations": last["iter"] or iterations,
                "train_error": last["err"],
            }
        _set(step="הושלם", percent=100,
             detail=f"זיהוי בגופן הנבחר: {base_score}% במודל הבסיס ← {new_score}% במודל החדש")
        log.info(
            "אימון %s הושלם תוך %.0f שניות (בסיס %.1f%% -> חדש %.1f%%)",
            model_name, time.time() - started, base_score, new_score,
        )
    except Exception as exc:
        log.exception("אימון נכשל: %s", exc)
        _set(step="שגיאה", error=str(exc))
    finally:
        with _lock:
            status["running"] = False
        shutil.rmtree(work, ignore_errors=True)


def start_training(font_paths: List[str], model_name: str, noise_level: str = "medium",
                   num_lines: int = 400, iterations: int = 400) -> Dict:
    """מפעיל אימון ברקע. מחזיר {started} או {error}."""
    global _thread
    if not font_paths:
        return {"error": "לא נבחר גופן"}
    name = _sanitize_name(model_name)
    with _lock:
        if status["running"]:
            return {"error": "אימון כבר רץ"}
        status.update({"running": True, "step": "מתחיל", "detail": "", "percent": 0,
                       "error": "", "result": None})
    _cancel.clear()
    num_lines = max(100, min(2000, int(num_lines)))
    iterations = max(100, min(5000, int(iterations)))
    _thread = threading.Thread(
        target=_run_training, args=(font_paths, name, noise_level, num_lines, iterations),
        daemon=True,
    )
    _thread.start()
    return {"started": True, "name": name}


# ---- ניהול מודלים ----
def list_models() -> List[Dict]:
    d = custom_tessdata_dir()
    out = []
    if d.exists():
        for p in sorted(d.glob("*.traineddata")):
            if p.stem in ("heb", "eng", "osd"):
                continue
            out.append({"name": p.stem, "size": p.stat().st_size, "mtime": p.stat().st_mtime})
    return out


def delete_model(name: str) -> bool:
    p = custom_tessdata_dir() / f"{_sanitize_name(name)}.traineddata"
    if p.exists():
        p.unlink()
        return True
    return False


__all__ = [
    "check_environment", "start_training", "get_status", "cancel",
    "list_models", "delete_model", "list_hebrew_fonts",
]
