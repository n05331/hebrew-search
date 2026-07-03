"""מנוע OCR מבוסס Surya 2 (Datalab) - דיוק גבוה בעברית + ניתוח פריסת עמוד.

המנוע רץ בסביבה מבודדת (ראו ``surya_install``) כתת-תהליך worker שמתקשר
ב-JSON על stdin/stdout: התמונה נשמרת ל-PNG זמני, ה-worker מזהה ומחזיר
טקסט לפי סדר הקריאה (עמודות RTL, כותרות, טבלאות).

שרת ההרצה (llama-server) מנוהל על ידי Surya בתוך ה-worker, אך הבינארי
שאנו מתקינים נבחר לפי החומרה: בניית CUDA למחשבי NVIDIA, אחרת בניית CPU
טהורה - שאינה מנסה Vulkan ולכן עוקפת קריסה מוכרת על GPU משולב ב-Windows.
ה-worker נשאר חי לאורך כל תור ה-OCR (עלות עליית השרת משולמת פעם אחת),
ומכובה כשהתור מתרוקן.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

from ...logging_setup import get_logger
from . import ocr_settings, surya_install
from .base import OcrEngine

log = get_logger("extract.ocr.surya")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# זמן המתנה לעליית ה-worker: בהרצה ראשונה מורדים המודלים (ג'יגה-בייטים)
_READY_TIMEOUT = 3600
# זמן מרבי לעמוד בודד (על CPU חלש עיבוד עמוד יכול לקחת דקות ארוכות)
_PAGE_TIMEOUT = 2400

# קוד ה-worker שרץ בסביבת ה-Python המבודדת (נכתב לדיסק בעת ההפעלה, כדי
# שיעבוד גם מתוך EXE ארוז שבו אין קובצי מקור)
_WORKER_SOURCE = r'''# -*- coding: utf-8 -*-
"""Surya OCR worker: JSON in (image path) -> JSON out (text)."""
import html
import json
import re
import sys
import traceback


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _block_text(block):
    h = getattr(block, "html", None) or ""
    if not h:
        return (getattr(block, "text", "") or "").strip()
    t = re.sub(r"<br\s*/?>", "\n", h)
    t = re.sub(r"</(p|div|tr|h\d|li|caption)>", "\n", t)
    t = re.sub(r"</t[dh]>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()


def extract_text(pred):
    blocks = getattr(pred, "blocks", None)
    if blocks:
        parts = [_block_text(b) for b in blocks]
        return "\n\n".join(p for p in parts if p)
    lines = getattr(pred, "text_lines", None)
    if lines is not None:
        return "\n".join((getattr(ln, "text", "") or "") for ln in lines)
    return ""


def main():
    emit({"event": "status", "detail": "loading-models"})
    try:
        from PIL import Image
        from surya.inference import SuryaInferenceManager
        from surya.recognition import RecognitionPredictor

        manager = SuryaInferenceManager()
        rec = RecognitionPredictor(manager)
    except Exception as exc:
        emit({"event": "fatal", "error": "%s\n%s" % (exc, traceback.format_exc())})
        return 1
    emit({"event": "ready"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        if req.get("cmd") == "exit":
            break
        rid = req.get("id")
        try:
            with Image.open(req["image"]) as img:
                rgb = img.convert("RGB")
            preds = rec([rgb])
            text = extract_text(preds[0]) if preds else ""
            emit({"id": rid, "ok": True, "text": text})
        except Exception as exc:
            emit({"id": rid, "ok": False, "error": "%s\n%s" % (exc, traceback.format_exc())})
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class SuryaEngine(OcrEngine):
    id = "surya"
    label = "Surya 2 (דיוק גבוה, איטי)"
    pdf_batch = 1  # ה-worker מעבד עמוד-עמוד; ההקבלה פנימית ב-Surya

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._ready = False
        self._gpu_active = False  # האם ה-worker הנוכחי הופעל במצב Vulkan
        # תור הודעות מה-worker: thread קריאה קבוע אחד ממלא אותו. אסור לקרוא
        # מ-stdout ב-threads מזדמנים - thread שקריאתו פגה נשאר תקוע על הצינור
        # ובולע את התשובה הבאה (עמודים ארוכים "נעלמו" כך עד timeout מלא).
        self._msgs: "queue.Queue[dict]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None

    # ---- זמינות ----
    def available(self) -> bool:
        return surya_install.is_installed()

    def status(self) -> str:
        if self.available():
            return "מוכן" + (" (NVIDIA)" if surya_install.has_nvidia() else " (מעבד - איטי)")
        return "לא מותקן - התקינו מהגדרות ה-OCR"

    def invalidate(self) -> None:
        pass

    def settings_schema(self) -> List[dict]:
        return []

    # ---- ניהול ה-worker ----
    def _worker_script(self) -> Path:
        path = surya_install.env_dir() / "surya_worker.py"
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
        except Exception:
            existing = ""
        if existing != _WORKER_SOURCE:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_WORKER_SOURCE, encoding="utf-8")
        return path

    def _use_gpu(self) -> bool:
        """האם להריץ במצב Vulkan: ההגדרה דלוקה והבנייה מותקנת."""
        return (
            ocr_settings.get_bool("ocr_surya_gpu")
            and surya_install.has_vulkan_build()
        )

    def _disable_gpu(self, reason: str) -> None:
        """כיבוי קבוע של מצב ה-GPU לאחר כשל - חוזרים ל-CPU היציב."""
        log.warning("האצת GPU (Vulkan) כובתה אוטומטית: %s", reason)
        try:
            from ...catalog import catalog

            catalog.set_setting("ocr_surya_gpu", "0")
        except Exception:
            pass
        ocr_settings.invalidate()

    def _spawn(self) -> None:
        env = dict(os.environ)
        self._gpu_active = self._use_gpu()
        llama = str(surya_install.vulkan_dir() if self._gpu_active else surya_install.llama_dir())
        env["PATH"] = llama + os.pathsep + env.get("PATH", "")
        if self._gpu_active:
            # העברת כל השכבות ל-GPU המשולב (בניית Vulkan)
            env["LLAMA_ARG_N_GPU_LAYERS"] = "999"
            log.info("Surya מופעל במצב GPU משולב (Vulkan) - ניסיוני")
        env["HF_HOME"] = str(surya_install.hf_cache_dir())
        env["HF_HUB_DISABLE_XET"] = "1"
        # משקולות ה-GGUF הורדו בהתקנה (מהמראה שלנו) - מפנים אליהן ישירות,
        # כדי ש-Surya לא ינסה להוריד מ-HuggingFace (ה-CDN חסום בחלק מהמסננים)
        ggufs = surya_install.gguf_paths()
        if ggufs:
            env["SURYA_GGUF_LOCAL_MODEL_PATH"] = ggufs["model"]
            env["SURYA_GGUF_LOCAL_MMPROJ_PATH"] = ggufs["mmproj"]
        env["SURYA_INFERENCE_BACKEND"] = "llamacpp"
        env["SURYA_INFERENCE_PARALLEL"] = "4"
        env.setdefault("SURYA_INFERENCE_TIMEOUT_SECONDS", str(_PAGE_TIMEOUT - 100))
        # llama.cpp קורא משתני LLAMA_ARG_*: בלי זה llama-server משתמש רק
        # בחלק קטן מהליבות והעיבוד על CPU איטי פי כמה
        try:
            n_threads = max(2, (os.cpu_count() or 4) - 1)
        except Exception:
            n_threads = 4
        env.setdefault("LLAMA_ARG_THREADS", str(n_threads))
        env.setdefault("LLAMA_ARG_THREADS_HTTP", "4")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        stderr_log = (surya_install.env_dir() / "worker.log").open("ab")
        self._proc = subprocess.Popen(
            [str(surya_install.python_exe()), "-u", str(self._worker_script())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_log,
            env=env, creationflags=_CREATE_NO_WINDOW,
            cwd=str(surya_install.env_dir()),
        )
        self._ready = False
        self._msgs = queue.Queue()
        self._reader = threading.Thread(
            target=self._reader_loop, args=(self._proc, self._msgs), daemon=True
        )
        self._reader.start()
        log.info("Surya worker הופעל (pid %s)", self._proc.pid)

    @staticmethod
    def _reader_loop(proc: subprocess.Popen, msgs: "queue.Queue[dict]") -> None:
        """ה-thread היחיד שקורא מ-stdout של ה-worker - כל שורה נכנסת לתור."""
        try:
            for raw in proc.stdout:
                try:
                    msgs.put(json.loads(raw.decode("utf-8", errors="replace")))
                except Exception:
                    continue
        except Exception:
            pass

    def _read_line(self, timeout: float) -> Optional[dict]:
        """שליפת ההודעה הבאה מהתור (מוזן על ידי thread הקריאה הקבוע)."""
        try:
            return self._msgs.get(timeout=timeout)
        except queue.Empty:
            return None

    def _ensure_ready(self) -> bool:
        if self._proc is not None and self._proc.poll() is None and self._ready:
            return True
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()
        deadline = time.time() + _READY_TIMEOUT
        while time.time() < deadline:
            msg = self._read_line(timeout=30)
            if msg is None:
                # קודם מרוקנים את התור - רק אז בודקים אם התהליך מת
                if self._proc.poll() is not None:
                    log.warning("Surya worker קרס בעת עלייה (קוד %s) - ראו worker.log", self._proc.returncode)
                    return False
                continue
            event = msg.get("event")
            if event == "ready":
                self._ready = True
                log.info("Surya worker מוכן")
                return True
            if event == "fatal":
                log.warning("Surya worker נכשל: %s", msg.get("error", "")[:500])
                self.idle()
                return False
            if event == "status":
                log.info("Surya worker: %s", msg.get("detail"))
        log.warning("Surya worker לא עלה בזמן")
        self.idle()
        return False

    def idle(self) -> None:
        """כיבוי ה-worker (והשרת שבתוכו) - נקרא כשתור ה-OCR מתרוקן."""
        proc, self._proc, self._ready = self._proc, None, False
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.write(b'{"cmd": "exit"}\n')
                    proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
            log.info("Surya worker כובה")
        except Exception as exc:
            log.debug("כיבוי Surya worker: %s", exc)

    # ---- זיהוי ----
    def ocr_image(self, image) -> str:
        if not self.available():
            return ""
        with self._lock:
            text, ok = self._ocr_once(image)
            if ok:
                return text
            # מצב GPU ניסיוני שנכשל (קריסה/חריגת זמן): כיבוי קבוע של ההאצה
            # וניסיון חוזר יחיד על CPU - המשתמש לא מאבד את העמוד
            if self._gpu_active:
                self._disable_gpu("כשל בזיהוי במצב Vulkan - חוזרים ל-CPU")
                text, ok = self._ocr_once(image)
                if ok:
                    return text
            return ""

    def _ocr_once(self, image) -> tuple:
        """ניסיון זיהוי יחיד. מחזיר (טקסט, האם_הצליח_טכנית)."""
        if not self._ensure_ready():
            return "", False
        tmp = Path(tempfile.gettempdir()) / f"hs_surya_{uuid.uuid4().hex}.png"
        try:
            image.save(tmp, format="PNG")
            rid = uuid.uuid4().hex
            req = json.dumps({"id": rid, "cmd": "ocr", "image": str(tmp)}) + "\n"
            self._proc.stdin.write(req.encode("utf-8"))
            self._proc.stdin.flush()
            deadline = time.time() + _PAGE_TIMEOUT
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    log.warning("Surya worker קרס בזמן זיהוי")
                    self.idle()
                    return "", False
                msg = self._read_line(timeout=15)
                if msg is None:
                    continue
                if msg.get("event"):
                    log.info("Surya worker: %s", msg.get("detail") or msg.get("error", "")[:200])
                    continue
                if msg.get("id") == rid:
                    if msg.get("ok"):
                        return msg.get("text", ""), True
                    log.warning("Surya OCR נכשל: %s", (msg.get("error") or "")[:300])
                    return "", False
            log.warning("Surya OCR חרג מהזמן לעמוד")
            self.idle()
            return "", False
        except Exception as exc:
            log.warning("תקשורת עם Surya worker נכשלה: %s", exc)
            self.idle()
            return "", False
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
