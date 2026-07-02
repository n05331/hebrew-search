"""משגר האפליקציה השולחנית.

מריץ את שרת ה-FastAPI בתהליך רקע (thread) ופותח חלון שולחני נייטיב באמצעות
pywebview שמצביע לשרת המקומי. חושף גשר JS לבחירת תיקייה דרך דיאלוג מערכת.
כך כל האפליקציה רצה מתהליך יחיד - חיוני לאריזה ל-EXE.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from contextlib import closing

import uvicorn
import webview

from backend.config import settings
from backend.logging_setup import get_logger, setup_logging

log = get_logger("launcher")

HOST = "127.0.0.1"


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


class Bridge:
    """גשר JS <-> Python לפעולות שדורשות דיאלוג מערכת."""

    def pick_folder(self):
        try:
            windows = webview.windows
            if not windows:
                return None
            # pywebview 6: webview.FileDialog.FOLDER; נפילה ל-FOLDER_DIALOG בגרסאות ישנות
            folder_type = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
            if folder_type is None:
                folder_type = getattr(webview, "FOLDER_DIALOG", 2)
            result = windows[0].create_file_dialog(folder_type)
            if result:
                return result[0] if isinstance(result, (list, tuple)) else result
        except Exception as exc:
            log.warning("בחירת תיקייה נכשלה: %s", exc)
        return None

    def save_file_dialog(self, default_name="", file_type="txt"):
        """דיאלוג 'שמירה בשם' נייטיב. מחזיר את הנתיב שנבחר או None."""
        try:
            windows = webview.windows
            if not windows:
                return None
            save_type = getattr(getattr(webview, "FileDialog", None), "SAVE", None)
            if save_type is None:
                save_type = getattr(webview, "SAVE_DIALOG", 3)
            if file_type == "docx":
                types = ("קובץ Word (*.docx)",)
            else:
                types = ("קובץ טקסט (*.txt)",)
            result = windows[0].create_file_dialog(
                save_type, save_filename=default_name, file_types=types
            )
            if result:
                return result[0] if isinstance(result, (list, tuple)) else result
        except Exception as exc:
            log.warning("דיאלוג שמירה נכשל: %s", exc)
        return None


def _run_server(port: int) -> None:
    # מייבאים את אובייקט האפליקציה ישירות (אמין יותר בגרסה הארוזה מ-import string)
    from backend.server import app as fastapi_app

    config = uvicorn.Config(
        fastapi_app,
        host=HOST,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            if s.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _acquire_single_instance() -> bool:
    """נעילת מופע-יחיד (Windows): מונע שני תהליכים שכותבים לאותו אינדקס."""
    if sys.platform != "win32":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "HebrewSearch_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None,
            "התוכנה כבר פתוחה. חלון נוסף עלול לפגוע באינדקס החיפוש.",
            "חיפוש עברי",
            0x40,  # MB_ICONINFORMATION
        )
        return False
    return True


def main() -> None:
    setup_logging()
    settings.ensure_dirs()

    if not _acquire_single_instance():
        log.info("מופע נוסף כבר רץ - יוצא.")
        sys.exit(0)

    port = _free_port()
    log.info("מפעיל שרת מקומי על פורט %d", port)

    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        log.error("השרת לא עלה בזמן. יוצא.")
        sys.exit(1)

    log.info("השרת פעיל. פותח חלון…")
    url = f"http://{HOST}:{port}/"

    webview.create_window(
        "חיפוש עברי",
        url,
        js_api=Bridge(),
        width=1280,
        height=820,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start()
    log.info("החלון נסגר. יוצא.")


if __name__ == "__main__":
    main()
