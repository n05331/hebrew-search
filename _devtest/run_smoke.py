# -*- coding: utf-8 -*-
"""בדיקות עשן ל-backend: toc, library, חיפוש-בספר, קידומות, מפרשים."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="hsr_test_data_"))
os.environ["HEBREW_SEARCH_DATA"] = str(DATA)

from backend import library, toc  # noqa: E402
from backend.catalog import catalog  # noqa: E402
from backend import matching  # noqa: E402

FAILS = []

def check(name, cond, extra=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    if not cond:
        FAILS.append(name)


# ---- 1. toc.parse_book ----
raw = """!קוד ישן בראש קובץ
$ ליקוטי מוהר"ן קמא
@ תורה א
~ אות א
זהו טקסט רגיל שורה ראשונה.
שורה שנייה של טקסט.
<h2>תורה ב</h2>
עוד טקסט כאן.
"""
display, headings = toc.parse_book(raw)
check("קוד בראש קובץ הוסר", "!קוד" not in display)
check("תווי סימון הוסרו", "$" not in display and "~" not in display and "<h2>" not in display)
check("מספר כותרות", len(headings) == 4, f"({len(headings)})")
check("רמות כותרות", [h["level"] for h in headings] == [1, 2, 3, 2])
for h in headings:
    check(f"היסט כותרת '{h['title']}'", display[h["start"]:h["end"]] == h["title"])

# ---- 2. עץ ספרייה עם קידומות ומפרשים ----
LIB = Path(tempfile.mkdtemp(prefix="hsr_test_lib_"))
r = LIB / "אוצר"
(r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@").mkdir(parents=True)
(r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@מפרשים").mkdir(parents=True)
(r / "4_גליונות").mkdir(parents=True)
(r / "תיקיה בלי מספר").mkdir(parents=True)

book_txt = r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@" / "02_ ליקוטי מוהרן מנוקד.txt"
book_txt.write_text(raw * 50, encoding="utf-8")
(r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@מפרשים" / "ביאור הליקוטים.txt").write_text(
    "@ תורה א\nביאור על תורה א\n", encoding="utf-8"
)
(r / "4_גליונות" / "03_עלון.txt").write_text("טקסט עלון\n", encoding="utf-8")
(r / "תיקיה בלי מספר" / "ספר אחר.txt").write_text("שלום עולם\n", encoding="utf-8")

catalog.connect()
catalog.add_root(str(r))
tree = library.build_tree()
top = tree[0]
names = [c["name"] for c in top["children"]]
check("סדר תיקיות לפי מספר", names[0] == "רבינו הקדוש" and names[1] == "גליונות", str(names))
check("קידומת מוסרת מתיקייה", "1_" not in names[0])
rabenu = top["children"][0]
book = rabenu["children"][0]
check("ספר @ זוהה", book["kind"] == "book" and book["name"] == "ליקוטי מוהר''ן")
check("מפרשים חובר לספר", bool(book.get("mefarshim")), str(book.get("mefarshim")))
mef = library.list_mefarshim(book["mefarshim"])
check("רשימת מפרשים", len(mef) == 1 and mef[0]["name"] == "ביאור הליקוטים", str(mef))

# ---- 3. קטעים + כותרות בקטע ----
chunk = library.get_book_chunk(str(book_txt), 0)
check("שם ללא קידומת", chunk["name"] == "ליקוטי מוהרן מנוקד", chunk["name"])
check("כותרות בקטע", len(chunk["headings"]) > 0)
h0 = chunk["headings"][0]
check("היסט כותרת בקטע", chunk["text"][h0["start"]:h0["end"]] == h0["title"])

toc_res = library.get_book_toc(str(book_txt))
check("TOC מלא", len(toc_res["headings"]) == 200, f"({len(toc_res['headings'])})")

# ---- 4. חיפוש-בספר עם אפשרויות ----
res = library.search_in_book(str(book_txt), "טקסט רגיל", matching.MatchOptions(exact=True, proximity=0))
check("חיפוש מדויק בספר", res["total"] == 50, f"({res['total']})")
hit = res["hits"][0]
cd = library.get_book_chunk(str(book_txt), hit["chunk"])
found = cd["text"][hit["start"]:hit["end"]]
check("היסט תוצאה תואם", "טקסט" in found and "רגיל" in found, repr(found))
check("snippet קיים", bool(hit["snippet"]))

res2 = library.search_in_book(str(book_txt), "טקסת רגיל", matching.MatchOptions(exact=True, proximity=0))
check("שאילתה שגויה - אפס", res2["total"] == 0)

# ---- 5. sync_position (ללא PDF בקטלוג - נפילה לאחוז) ----
fake_pdf = r / "1_רבינו הקדוש" / "ליקוטי מוהר''ן@" / "ליקוטי מוהרן.pdf"
fake_pdf.write_bytes(b"%PDF-1.4 fake")
sp = library.sync_position(str(book_txt), str(fake_pdf), "to_pdf", offset=100)
check("sync נפילה לאחוז", sp["ok"] and "page" in sp, str(sp))

print()
print("FAILED:" if FAILS else "ALL PASSED", FAILS if FAILS else "")
sys.exit(1 if FAILS else 0)
