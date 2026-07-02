"""התקנת מנוע Surya לפי דרישה - סביבה מבודדת לצד האפליקציה.

Surya דורש PyTorch ומשקולות בהיקף ג'יגה-בייטים וברישיון OpenRAIL-M, ולכן
אינו נארז ב-EXE אלא מותקן בלחיצה מתוך ההגדרות אל
``%LOCALAPPDATA%\\HebrewSearch\\engines\\surya``:

1. Python embeddable (רשמי, python.org) - מבודד לחלוטין מהמערכת.
2. pip (ל-embeddable אין pip - מותקן עם get-pip).
3. PyTorch גרסת CPU (מודל זיהוי השורות הקל) + חבילת surya-ocr.
4. בינארי llama-server מ-llama.cpp - גרסת CUDA אם זוהה NVIDIA, אחרת CPU
   (בניית CPU אינה מנסה Vulkan - עוקף קריסה מוכרת על GPU משולב ב-Windows).

ההתקנה רצה ב-thread רקע עם דיווח התקדמות ל-UI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from ...config import settings
from ...logging_setup import get_logger

log = get_logger("ocr.surya.install")

PY_EMBED_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
SURYA_SPEC = "surya-ocr==0.20.0"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
LLAMA_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

# משקולות ה-VLM (GGUF): קודם מהמראה שלנו ב-GitHub Releases - ה-CDN של
# HuggingFace חסום אצל חלק ממסנני האינטרנט (נטפרי) בעוד GitHub פתוח.
# ההעלאה למראה נעשית ב-CI (workflow ייעודי) יחד עם קובץ הרישיון.
_MIRROR_BASE = "https://github.com/n05331/hebrew-search/releases/download/models-surya-2"
_HF_BASE = "https://huggingface.co/datalab-to/surya-ocr-2-gguf/resolve/main"
GGUF_FILES = [
    ("surya-2.gguf", 1_400_000_000),          # ~1.27GB
    ("surya-2-mmproj.gguf", 250_000_000),     # ~205MB
]

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def env_dir() -> Path:
    return settings.data_dir / "engines" / "surya"


def python_exe() -> Path:
    return env_dir() / "python" / "python.exe"


def llama_dir() -> Path:
    return env_dir() / "llama"


def hf_cache_dir() -> Path:
    return env_dir() / "hf-cache"


def models_dir() -> Path:
    return env_dir() / "models"


def gguf_paths() -> dict:
    """נתיבי קובצי המודל המקומיים (אם הושלמו בהתקנה)."""
    d = models_dir()
    model = d / GGUF_FILES[0][0]
    mmproj = d / GGUF_FILES[1][0]
    if model.exists() and mmproj.exists():
        return {"model": str(model), "mmproj": str(mmproj)}
    return {}


def marker_file() -> Path:
    return env_dir() / "install_ok.json"


def is_installed() -> bool:
    return marker_file().exists() and python_exe().exists() and bool(gguf_paths())


def has_nvidia() -> bool:
    if shutil.which("nvidia-smi"):
        return True
    return Path(r"C:\Windows\System32\nvidia-smi.exe").exists()


# ---- סטטוס התקנה משותף ל-API ----
status = {
    "running": False,
    "step": "",
    "detail": "",
    "percent": 0,
    "error": "",
    "installed": False,
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
        status["installed"] = is_installed()


def get_status() -> dict:
    with _lock:
        s = dict(status)
    s["installed"] = is_installed()
    s["nvidia"] = has_nvidia()
    return s


def _download(url: str, target: Path, label: str, pct_from: int, pct_to: int) -> None:
    """הורדת קובץ עם דיווח התקדמות לפי Content-Length."""
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "HebrewSearch"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with target.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    frac = done / total
                    _set(
                        detail=f"{label} ({done // (1024*1024)}MB/{total // (1024*1024)}MB)",
                        percent=int(pct_from + (pct_to - pct_from) * frac),
                    )


def _run_pip(args: list, step_label: str) -> None:
    """הרצת pip בסביבה המבודדת; הפלט נכתב ללוג ההתקנה."""
    log_file = env_dir() / "install.log"
    cmd = [str(python_exe()), "-m", "pip"] + args + ["--no-warn-script-location"]
    log.info("מריץ: %s", " ".join(cmd))
    with log_file.open("a", encoding="utf-8", errors="replace") as lf:
        lf.write(f"\n===== {step_label}: {' '.join(cmd)}\n")
        lf.flush()
        proc = subprocess.run(
            cmd, stdout=lf, stderr=subprocess.STDOUT,
            creationflags=_CREATE_NO_WINDOW, timeout=3600,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"{step_label} נכשל (קוד {proc.returncode}) - ראו {log_file}")


def _install_python(tmp: Path) -> None:
    _set(step="הורדת Python", percent=1)
    zip_path = tmp / "python-embed.zip"
    _download(PY_EMBED_URL, zip_path, "Python", 1, 4)
    pydir = env_dir() / "python"
    pydir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(pydir)
    # ל-embeddable אין site-packages פעיל - חובה לאפשר import site כדי ש-pip יעבוד
    for pth in pydir.glob("python3*._pth"):
        content = pth.read_text(encoding="utf-8")
        content = content.replace("#import site", "import site")
        pth.write_text(content, encoding="utf-8")

    _set(step="התקנת pip", percent=5)
    get_pip = tmp / "get-pip.py"
    _download(GET_PIP_URL, get_pip, "get-pip", 5, 7)
    with (env_dir() / "install.log").open("a", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.run(
            [str(python_exe()), str(get_pip), "--no-warn-script-location"],
            stdout=lf, stderr=subprocess.STDOUT,
            creationflags=_CREATE_NO_WINDOW, timeout=600,
        )
    if proc.returncode != 0:
        raise RuntimeError("התקנת pip נכשלה")


def _pick_llama_assets(release: dict) -> list:
    """בוחר את קובצי llama.cpp המתאימים: CUDA אם יש NVIDIA, אחרת CPU."""
    assets = release.get("assets", [])
    names = {a["name"]: a["browser_download_url"] for a in assets}
    chosen = []
    if has_nvidia():
        cuda = [n for n in names if "win" in n and "cuda" in n and "x64" in n and n.endswith(".zip")]
        cudart = [n for n in names if n.startswith("cudart") and "win" in n and n.endswith(".zip")]
        if cuda:
            # הגרסה החדשה ביותר של cu (מיון לקסיקוגרפי מספיק לבחירה יציבה)
            chosen.append(names[sorted(cuda)[-1]])
            if cudart:
                chosen.append(names[sorted(cudart)[-1]])
            return chosen
    cpu = [n for n in names if "win" in n and "cpu" in n and "x64" in n and n.endswith(".zip")]
    if cpu:
        return [names[sorted(cpu)[-1]]]
    raise RuntimeError("לא נמצא בינארי llama-server מתאים ל-Windows בגרסה האחרונה")


def _install_llama(tmp: Path) -> None:
    _set(step="הורדת llama-server", percent=85)
    req = urllib.request.Request(LLAMA_RELEASES_API, headers={"User-Agent": "HebrewSearch"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        release = json.loads(resp.read().decode("utf-8"))
    urls = _pick_llama_assets(release)
    ldir = llama_dir()
    ldir.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(urls):
        zpath = tmp / f"llama_{i}.zip"
        _download(url, zpath, "llama.cpp", 85 + i * 5, 90 + i * 5)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(ldir)
    # חלק מהחבילות נפרשות לתת-תיקייה - מאתרים את llama-server.exe ומשטחים
    exe = ldir / "llama-server.exe"
    if not exe.exists():
        found = list(ldir.rglob("llama-server.exe"))
        if not found:
            raise RuntimeError("llama-server.exe לא נמצא בחבילה שהורדה")
        src_dir = found[0].parent
        for item in src_dir.iterdir():
            target = ldir / item.name
            if not target.exists():
                shutil.move(str(item), str(target))


def _install_models(tmp: Path) -> None:
    """הורדת משקולות ה-GGUF: קודם מהמראה ב-GitHub, ואם אין - מ-HuggingFace."""
    d = models_dir()
    d.mkdir(parents=True, exist_ok=True)
    pct = 60
    for i, (fname, approx) in enumerate(GGUF_FILES):
        target = d / fname
        if target.exists() and target.stat().st_size > approx // 2:
            continue
        pct_to = pct + (20 if i == 0 else 4)
        last_err = None
        for base in (_MIRROR_BASE, _HF_BASE):
            try:
                _set(step="הורדת מודל הזיהוי", percent=pct)
                _download(f"{base}/{fname}", target, fname, pct, pct_to)
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                log.warning("הורדת %s מ-%s נכשלה: %s", fname, base, exc)
                try:
                    target.unlink(missing_ok=True)
                except Exception:
                    pass
        if last_err is not None:
            raise RuntimeError(
                f"הורדת מודל הזיהוי ({fname}) נכשלה מכל המקורות: {last_err}"
            )
        pct = pct_to


def _run_install() -> None:
    import tempfile

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="hs_surya_inst_"))
    try:
        env_dir().mkdir(parents=True, exist_ok=True)
        _set(step="מתחיל", detail="", percent=0, error="")

        if not python_exe().exists():
            _install_python(tmp)

        _set(step="התקנת PyTorch (CPU)", detail="הורדה גדולה - כמה דקות", percent=10)
        _run_pip(["install", "torch", "--index-url", TORCH_INDEX], "התקנת torch")

        _set(step="התקנת Surya", detail="", percent=55)
        _run_pip(["install", SURYA_SPEC], "התקנת surya")

        _install_models(tmp)

        if not (llama_dir() / "llama-server.exe").exists():
            _install_llama(tmp)

        hf_cache_dir().mkdir(parents=True, exist_ok=True)
        marker_file().write_text(
            json.dumps({
                "surya": SURYA_SPEC,
                "nvidia": has_nvidia(),
                "installed_at": time.time(),
            }),
            encoding="utf-8",
        )
        _set(step="הושלם", detail="", percent=100)
        log.info("התקנת Surya הושלמה תוך %.0f שניות", time.time() - started)
    except Exception as exc:
        log.exception("התקנת Surya נכשלה: %s", exc)
        _set(step="שגיאה", error=str(exc))
    finally:
        with _lock:
            status["running"] = False
        shutil.rmtree(tmp, ignore_errors=True)


def start_install() -> bool:
    """מפעיל התקנה ברקע. מחזיר False אם התקנה כבר רצה."""
    global _thread
    with _lock:
        if status["running"]:
            return False
        status["running"] = True
        status["error"] = ""
    _thread = threading.Thread(target=_run_install, daemon=True)
    _thread.start()
    return True


def uninstall() -> None:
    """מסיר את הסביבה כולה (לאחר עצירת ה-worker)."""
    from . import get_engine

    try:
        eng = get_engine("surya")
        if eng.id == "surya":
            eng.idle()
    except Exception:
        pass
    shutil.rmtree(env_dir(), ignore_errors=True)
