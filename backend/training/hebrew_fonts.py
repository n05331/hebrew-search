"""איתור גופנים עבריים מותקנים במחשב.

הסינון נעשה בבדיקת כיסוי אמיתית של טבלת ה-cmap (באמצעות fontTools) - גופן
נחשב עברי רק אם הוא מכיל את כל אותיות הא'-ב' - ולא בניחוש לפי שם הקובץ.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Dict, List

from ..logging_setup import get_logger

log = get_logger("training.fonts")

# גופנים ישנים רבים מכילים טבלאות post/name מעט פגומות; fontTools מציף על כך
# אזהרות שאינן משפיעות על קריאת ה-cmap (בדיקת הכיסוי העברי) - משתיקים
logging.getLogger("fontTools").setLevel(logging.ERROR)

# כל אותיות העברית כולל סופיות
_HEBREW_LETTERS = [chr(c) for c in range(0x05D0, 0x05EB)]


def _font_dirs() -> List[Path]:
    dirs = []
    windir = os.environ.get("WINDIR", r"C:\Windows")
    dirs.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return [d for d in dirs if d.exists()]


def _check_font(path: Path) -> List[Dict]:
    """מחזיר רשומות (שם משפחה, נתיב, אינדקס) לגופנים עבריים בקובץ."""
    from fontTools.ttLib import TTFont, TTLibError

    results = []
    try:
        # קובצי TTC מכילים כמה גופנים
        if path.suffix.lower() == ".ttc":
            from fontTools.ttLib.ttCollection import TTCollection

            fonts = TTCollection(str(path), lazy=True).fonts
        else:
            fonts = [TTFont(str(path), lazy=True)]
    except (TTLibError, Exception):
        return results

    for idx, font in enumerate(fonts):
        try:
            cmap = font.getBestCmap()
            if not all(ord(ch) in cmap for ch in _HEBREW_LETTERS):
                continue
            name_tbl = font["name"]
            family = (
                name_tbl.getDebugName(16)  # Typographic family
                or name_tbl.getDebugName(1)
                or path.stem
            )
            sub = name_tbl.getDebugName(17) or name_tbl.getDebugName(2) or ""
            results.append({
                "family": family,
                "style": sub,
                "path": str(path),
                "index": idx if path.suffix.lower() == ".ttc" else 0,
            })
        except Exception:
            continue
        finally:
            try:
                font.close()
            except Exception:
                pass
    return results


def list_hebrew_fonts() -> List[Dict]:
    """סורק את תיקיות הגופנים ומחזיר גופנים עם כיסוי עברי מלא.

    מחזיר רשימה ממוינת של {family, style, path, index}, סגנון Regular מועדף
    כשיש כמה קבצים לאותה משפחה.
    """
    if sys.platform != "win32":
        return []
    seen: Dict[str, Dict] = {}
    for d in _font_dirs():
        for path in sorted(d.iterdir()):
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            for rec in _check_font(path):
                key = rec["family"]
                style = (rec["style"] or "").lower()
                is_regular = style in ("regular", "", "normal", "book", "medium")
                if key not in seen or (is_regular and not seen[key].get("_regular")):
                    rec["_regular"] = is_regular
                    seen[key] = rec
    out = []
    for rec in sorted(seen.values(), key=lambda r: r["family"].lower()):
        rec.pop("_regular", None)
        out.append(rec)
    return out
