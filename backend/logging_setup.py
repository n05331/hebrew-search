"""תשתית לוגים לאבחון.

מספקת:
- כתיבה לקובץ לוג מסתובב (rotating) בתיקיית הנתונים.
- מאגר טבעתי בזיכרון (ring buffer) שממנו מסך "יומן/אבחון" בממשק שואב רשומות.
- פורמט אחיד עם חותמת זמן, רמה, שם רכיב והודעה.
"""

from __future__ import annotations

import logging
import logging.handlers
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Deque, Dict, List

from .config import settings


class RingBufferHandler(logging.Handler):
    """שומר את N הרשומות האחרונות בזיכרון עבור מסך האבחון."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._buffer: Deque[Dict] = deque(maxlen=capacity)
        self._lock = Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._seq += 1
                self._buffer.append(
                    {
                        "id": self._seq,
                        "time": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                    }
                )
        except Exception:  # לעולם לא מפילים את האפליקציה בגלל לוג
            pass

    def records(self, after_id: int = 0, level: str | None = None) -> List[Dict]:
        with self._lock:
            items = list(self._buffer)
        result = [r for r in items if r["id"] > after_id]
        if level and level != "ALL":
            result = [r for r in result if r["level"] == level]
        return result


ring_buffer = RingBufferHandler()

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """מגדיר את מערכת הלוגים פעם אחת."""
    global _configured
    if _configured:
        return

    settings.ensure_dirs()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    log_file = settings.log_dir / "hebrew_search.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(level)

    ring_buffer.setLevel(logging.DEBUG)

    root.addHandler(file_handler)
    root.addHandler(console)
    root.addHandler(ring_buffer)

    _configured = True
    logging.getLogger("hebrew_search.startup").info(
        "לוגים אותחלו. קובץ לוג: %s", log_file
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"hebrew_search.{name}")
