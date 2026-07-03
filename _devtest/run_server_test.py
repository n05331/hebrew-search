# -*- coding: utf-8 -*-
"""בדיקת שרת מקצה-לקצה: עץ, TOC, חיפוש-בספר, הגדרות, מפרשים, אינדוקס וחיפוש."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="hsr_srv_data_"))
os.environ["HEBREW_SEARCH_DATA"] = str(DATA)

LIB = Path(tempfile.mkdtemp(prefix="hsr_srv_lib_"))
r = LIB / "אוצר"
(r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@").mkdir(parents=True)
(r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@מפרשים").mkdir(parents=True)
book_txt = r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@" / "02_ליקוטי מוהרן.txt"
book_txt.write_text(
    "$ ליקוטי מוהר\"ן קמא\n@ תורה א\nדע כי צריך לחפש את הצדיק האמת מאוד מאוד.\n@ תורה ב\nעוד עניין גדול ונורא כאן.\n",
    encoding="utf-8",
)
(r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@מפרשים" / "ביאור.txt").write_text(
    "@ תורה א\nביאור נפלא.\n", encoding="utf-8"
)
# PDF סינתטי עם שכבת טקסט - לבדיקות ייצוא ו-OCR בכפייה (נבנה גם ב-CI)
sys.path.insert(0, str(Path(__file__).parent))
from make_pdf_test import build_twocol_pdf  # noqa: E402

test_pdf = build_twocol_pdf(r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@" / "twocol.pdf")

import uvicorn  # noqa: E402
from backend.server import app  # noqa: E402

PORT = 8977
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(100):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.2)

FAILS = []

def call(method, path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def check(name, cond, extra=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILS.append(name)

from urllib.parse import quote  # noqa: E402

# הוספת שורש + אינדוקס
call("POST", "/api/roots", {"path": str(r)})
call("POST", "/api/index", {"paths": [str(r)]})
for _ in range(60):
    p = call("GET", "/api/progress")
    if not p["running"] and p["phase"] in ("done", "idle", "error"):
        break
    time.sleep(0.3)
check("אינדוקס הסתיים", p["phase"] == "done", str(p["phase"]))

tree = call("GET", "/api/tree")["tree"]
check("עץ נבנה", len(tree) == 1)
rabenu = tree[0]["children"][0]
check("שם תיקייה ללא קידומת", rabenu["name"] == "רבינו הקדוש", rabenu["name"])
book = rabenu["children"][0]
check("מפרשים בעץ", bool(book.get("mefarshim")))

mef = call("GET", "/api/mefarshim?folder=" + quote(book["mefarshim"]))
check("מפרשים API", len(mef["books"]) == 1, str(len(mef["books"])))

toc_res = call("GET", "/api/book/toc?path=" + quote(str(book_txt)))
check("TOC API", len(toc_res["headings"]) == 3, str(len(toc_res["headings"])))

bs = call("POST", "/api/book/search", {"path": str(book_txt), "q": "הצדיק האמת", "exact": True})
check("חיפוש בספר API", bs["total"] == 1 and bs["kind"] == "text", str(bs["total"]))
check("snippet בחיפוש בספר", "הצדיק" in bs["hits"][0]["snippet"])

# חיפוש ראשי
sr = call("POST", "/api/search", {"q": "לחפש את הצדיק"})
check("חיפוש ראשי", sr["total"] >= 1, str(sr["total"]))
if sr["results"]:
    check("שם תוצאה", "ליקוטי" in sr["results"][0]["name"])

prog = call("GET", "/api/search/progress")
check("search progress API", "running" in prog)

st = call("GET", "/api/settings")["settings"]
check("ברירות מחדל הגדרות", st["font_size"] == "30" and st["result_font_size"] == "25" and st["font_family"] == "FrankRuehl", str((st["font_size"], st["result_font_size"], st["font_family"])))

sync = call("POST", "/api/book/sync-position", {"text_path": str(book_txt), "pdf_path": str(book_txt), "direction": "to_pdf", "offset": 10})
check("sync-position API", "ok" in sync)

clip = None
try:
    clip = call("POST", "/api/clipboard", {"text": "בדיקת לוח"})
except Exception as e:
    clip = {"ok": False, "err": str(e)}
check("clipboard API", clip.get("ok") is True, str(clip))

# שמירת קובץ טקסט + docx
out_txt = DATA / "out_test.txt"
sv = call("POST", "/api/export/text-file", {"path": str(out_txt), "text": "שלום\nעולם", "format": "txt"})
check("שמירת TXT", sv["ok"] and out_txt.exists())
out_docx = DATA / "out_test.docx"
sv2 = call("POST", "/api/export/text-file", {"path": str(out_docx), "text": "שלום\nעולם", "format": "docx"})
check("שמירת DOCX", sv2["ok"] and out_docx.exists())

fonts = call("GET", "/api/fonts")["fonts"]
check("רשימת גופנים", len(fonts) > 10, str(len(fonts)))

# מנועי OCR
engines = call("GET", "/api/ocr/engines")["engines"]
check("רשימת מנועי OCR", any(e["id"] == "tesseract" for e in engines), str([e["id"] for e in engines]))
tess = next(e for e in engines if e["id"] == "tesseract")
check("סכימת הגדרות למנוע", len(tess["settings"]) >= 4, str(len(tess["settings"])))
check("ברירות מחדל OCR בהגדרות", st.get("ocr_engine") == "tesseract" and st.get("ocr_psm") == "3", str((st.get("ocr_engine"), st.get("ocr_psm"))))

# שמירת הגדרת OCR ואימות שהיא נקלטת
call("PUT", "/api/settings", {"values": {"ocr_psm": "6"}})
st2 = call("GET", "/api/settings")["settings"]
check("שמירת הגדרת OCR", st2.get("ocr_psm") == "6")

rerun = call("POST", "/api/ocr/rerun")
check("הרצת OCR מחדש", "queued" in rerun, str(rerun))

# סטטוס Surya (לא דורש התקנה)
ss = call("GET", "/api/ocr/surya/status")
check("סטטוס Surya", "installed" in ss and "nvidia" in ss, str(ss))

# ייצוא/ייבוא נתונים
tc2 = call("GET", "/api/transfer/components")["components"]
check("רכיבי ייצוא", all(k in tc2 for k in ("settings", "index", "models", "surya")), str(list(tc2)))
try:
    call("POST", "/api/transfer/import", {"path": "C:/nonexistent/bundle.zip", "components": ["index"]})
    check("ייבוא דוחה קובץ חסר", False)
except Exception as e:
    check("ייבוא דוחה קובץ חסר", "400" in str(e) or "Bad Request" in str(e), str(e))

# ייצוא אמיתי של הגדרות+אינדקס וייבוא חוזר (אותו שרת - רשומות קיימות נשמרות)
exp_dir = DATA / "transfer_out"
exp_dir.mkdir()
call("POST", "/api/transfer/export", {"path": str(exp_dir), "components": ["settings", "index"]})
for _ in range(100):
    ts = call("GET", "/api/transfer/status")
    if not ts["running"]:
        break
    time.sleep(0.2)
bundle_path = exp_dir / "HebrewSearch-Transfer.zip"
check("ייצוא הפיק קובץ", ts["error"] == "" and bundle_path.exists(), str(ts))

insp = call("POST", "/api/transfer/inspect", {"path": str(bundle_path)})
check("בדיקת manifest", "settings" in insp["manifest"]["components"], str(insp["manifest"]["components"]))

call("POST", "/api/transfer/import", {"path": str(bundle_path), "components": ["settings", "index"]})
for _ in range(100):
    ts = call("GET", "/api/transfer/status")
    if not ts["running"]:
        break
    time.sleep(0.2)
check("ייבוא הושלם", ts["error"] == "" and ts["percent"] == 100, str(ts))

# מידע על קובץ + ייצוא טקסט כמשימת רקע
fi = call("GET", "/api/file/info?path=" + quote(str(test_pdf)))
check("file info API", fi.get("has_text") is True and fi.get("page_count", 0) >= 1, str(fi))

exp_txt = DATA / "export_extract.txt"
call("POST", "/api/export/extract", {
    "path": str(test_pdf), "target": str(exp_txt), "source": "text", "format": "txt",
})
for _ in range(100):
    es = call("GET", "/api/export/extract/status")
    if not es["running"]:
        break
    time.sleep(0.2)
check("ייצוא טקסט הושלם", es["error"] == "" and es["done"], str(es))
check("קובץ הייצוא נוצר", exp_txt.exists() and exp_txt.stat().st_size > 10)

# ייצוא מהטקסט השמור (הקובץ אונדקס קודם) - עמוד ראשון בלבד
exp_saved = DATA / "export_saved.txt"
call("POST", "/api/export/extract", {
    "path": str(test_pdf), "target": str(exp_saved), "source": "saved",
    "format": "txt", "page_from": 1, "page_to": 1,
})
for _ in range(100):
    es2 = call("GET", "/api/export/extract/status")
    if not es2["running"]:
        break
    time.sleep(0.2)
check("ייצוא מטקסט שמור", es2["error"] == "" and es2["done"], str(es2))

# OCR בכפייה לקובץ בודד (התעלמות משכבת הטקסט); ברצי CI אין Tesseract -
# ואז הצפי הוא 503 מסודר
ocr_ok = call("GET", "/api/stats").get("ocr_available")
if ocr_ok:
    fo = call("POST", "/api/file/force-ocr", {"path": str(test_pdf)})
    check("force-ocr API", fo.get("queued") is True, str(fo))
    fi2 = call("GET", "/api/file/info?path=" + quote(str(test_pdf)))
    check("force-ocr נרשם", fi2.get("force_ocr") is True and fi2.get("status") == "pending_ocr", str(fi2))
else:
    try:
        call("POST", "/api/file/force-ocr", {"path": str(test_pdf)})
        check("force-ocr ללא OCR מחזיר 503", False)
    except Exception as e:
        check("force-ocr ללא OCR מחזיר 503", "503" in str(e), str(e))

# אימון: בדיקת סביבה + רשימת גופנים עבריים
tc = call("GET", "/api/training/check")
check("בדיקת סביבת אימון", "ok" in tc, str(tc))
tf = call("GET", "/api/training/fonts")["fonts"]
check("גופנים עבריים לאימון", len(tf) >= 1, str(len(tf)))
tm = call("GET", "/api/training/models")
check("רשימת מודלים מאומנים", "models" in tm)
ts = call("GET", "/api/training/status")
check("סטטוס אימון", "running" in ts)

print()
print("FAILED:" if FAILS else "ALL PASSED", FAILS if FAILS else "")
server.should_exit = True
time.sleep(0.5)
sys.exit(1 if FAILS else 0)
