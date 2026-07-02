# -*- coding: utf-8 -*-
"""שרת פיתוח לבדיקות UI: ספרייה סינתטית + נתונים נפרדים."""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

DATA = HERE / "ui_data"
if DATA.exists():
    shutil.rmtree(DATA, ignore_errors=True)
os.environ["HEBREW_SEARCH_DATA"] = str(DATA)

LIB = HERE / "ui_lib"
if LIB.exists():
    shutil.rmtree(LIB, ignore_errors=True)

r = LIB / "אוצר ספרים"
(r / "1_רבינו הקדוש" / "ליקוטי מוהרן@").mkdir(parents=True)
(r / "1_רבינו הקדוש" / "ליקוטי מוהרן@מפרשים").mkdir(parents=True)
(r / "4_גליונות").mkdir(parents=True)

paras = []
paras.append('$ ליקוטי מוהר"ן קמא')
for torah in range(1, 6):
    paras.append(f"@ תורה {torah}")
    for ot in range(1, 4):
        paras.append(f"~ אות {ot}")
        paras.append(
            f"דע כי צריך לחפש את הצדיק האמת מאוד מאוד תורה {torah} אות {ot}. "
            + "כי על ידי התקרבות לצדיקים אמיתיים זוכים לתשובה שלמה ולתיקון הנפש. " * 25
        )
book_txt = r / "1_רבינו הקדוש" / "ליקוטי מוהרן@" / "02_ליקוטי מוהרן מנוקד.txt"
book_txt.write_text("\n".join(paras), encoding="utf-8")

shutil.copy2(HERE / "twocol.pdf", r / "1_רבינו הקדוש" / "ליקוטי מוהרן@" / "ליקוטי מוהרן.pdf")

(r / "1_רבינו הקדוש" / "ליקוטי מוהרן@מפרשים" / "ביאור הליקוטים.txt").write_text(
    "@ תורה 1\nביאור נפלא על תורה 1 בעניין הצדיק.\n@ תורה 2\nביאור לתורה 2.\n",
    encoding="utf-8",
)
(r / "4_גליונות" / "03_עלון אבקשה.txt").write_text("טקסט עלון לדוגמה עם הצדיק האמת.\n", encoding="utf-8")

import uvicorn  # noqa: E402
from backend.server import app  # noqa: E402
from backend.catalog import catalog  # noqa: E402

@app.on_event("startup")
def _add_root():
    catalog.add_root(str(r))
    from backend.indexer import indexer
    indexer.start_index_roots([str(r)])

uvicorn.run(app, host="127.0.0.1", port=8123, log_level="info")
